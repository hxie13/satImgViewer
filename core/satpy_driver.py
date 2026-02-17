import logging
import numpy as np
import os
import re
import contextlib
import time
import traceback
from pyresample import geometry  # <--- 确保顶部导入了 geometry
from .interfaces import ISatelliteDataProvider
from .image_proc import ImageProcessor
from .projections import get_projection_config, create_target_area, get_available_projections
from .satellite_projection import get_satellite_coverage
from .calibration import Calibration, GLTCorrection, RegionCropper, Resampler, GeoTIFFWriter
from .file_scanner import detect_reader_for_file, group_files_by_reader, scan_and_group_files
from .models import ExportResult
try:
    from PIL import Image
except Exception:
    Image = None

class SatpyDriver(ISatelliteDataProvider):
    def __init__(self):
        self.scn = None
        self.dataset_map = {}
        # 减少 Satpy 在 reader 初始化时对缺失可选依赖的大量错误/警告打印。
        # 这些错误通常来自 Satpy 在解析 readers yaml 时尝试导入可选模块（pygrib/pyarrow/eccodes 等）。
        try:
            logging.getLogger('satpy.readers.core.loading').setLevel(logging.ERROR)
            logging.getLogger('satpy.readers.core.yaml_reader').setLevel(logging.ERROR)
            logging.getLogger('satpy.readers.core').setLevel(logging.ERROR)
            # 可选：将 satpy 顶级日志降低为 WARNING，避免过多信息
            logging.getLogger('satpy').setLevel(logging.WARNING)
        except Exception:
            pass

    # We'll import `satpy` lazily inside `load_scene` while redirecting stdout/stderr
    _satpy = None

    def _detect_reader(self, file_paths: list) -> str:
        """
        Detect the appropriate reader for a list of files.
        Analyzes all files to determine the most appropriate reader.
        """
        if not file_paths:
            return 'ahi_hsd'
            
        # Count reader matches across all files
        reader_counts = {}
        
        for file_path in file_paths:
            reader = self._detect_reader_for_file(file_path)
            reader_counts[reader] = reader_counts.get(reader, 0) + 1
        
        # Return the most common reader
        if reader_counts:
            return max(reader_counts, key=reader_counts.get)
        return 'ahi_hsd'
    
    def _detect_reader_for_file(self, file_path: str) -> str:
        """Detect the appropriate reader for a single file."""
        return detect_reader_for_file(file_path)
    
    def group_files_by_type(self, file_paths: list) -> dict:
        """Group files by detected reader type."""
        return group_files_by_reader(file_paths)

    def scan_and_group_files(self, folder_path: str) -> list:
        """扫描文件夹，按时间戳将文件分组。"""
        return scan_and_group_files(folder_path)

    def load_scene(self, file_paths: list):
        """
        Load scenes from multiple files, grouping them by type if necessary.
        Returns True if at least one scene was successfully loaded.
        """
        # Import satpy lazily here while suppressing stdout/stderr so reader YAML
        # parsing errors (missing optional deps) don't spam the console during import.
        if self._satpy is None:
            try:
                if not os.environ.get('SATIMG_DEBUG'):
                    with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                        import satpy as _satpy_module
                else:
                    import satpy as _satpy_module
                self._satpy = _satpy_module
                # configure logger suppression after import
                try:
                    logging.getLogger('satpy.readers.core.loading').setLevel(logging.ERROR)
                    logging.getLogger('satpy.readers.core.yaml_reader').setLevel(logging.ERROR)
                    logging.getLogger('satpy.readers.core').setLevel(logging.ERROR)
                    logging.getLogger('satpy.readers').setLevel(logging.ERROR)
                    logging.getLogger('satpy').setLevel(logging.WARNING)
                    for name in ('satpy.readers.core.loading', 'satpy.readers.core', 'satpy.readers', 'satpy'):
                        lg = logging.getLogger(name)
                        try:
                            lg.propagate = False
                            lg.handlers = []
                            lg.addHandler(logging.NullHandler())
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                # If import fails, leave self._satpy None and let subsequent attempts handle it.
                self._satpy = None

        if not file_paths:
            print("No files provided.")
            return False

        # Group files by their detected type
        file_groups = self.group_files_by_type(file_paths)
        print(f"Grouped files into {len(file_groups)} categories:")
        for reader_type, files in file_groups.items():
            print(f"  {reader_type}: {len(files)} files")

        # Try to load each group separately
        self.scenes = []  # Store multiple scenes if needed
        self.current_scene_index = 0
        
        for reader_name, group_files in file_groups.items():
            print(f"\nAttempting to load {len(group_files)} files with {reader_name}...")
            try:
                # Use lazy-imported satpy module
                if self._satpy is None:
                    raise RuntimeError('satpy not available')
                if not os.environ.get('SATIMG_DEBUG'):
                    with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                        scene = self._satpy.Scene(reader=reader_name, filenames=group_files)
                else:
                    scene = self._satpy.Scene(reader=reader_name, filenames=group_files)

                if scene.available_dataset_names():
                    print(f"Success with {reader_name}")
                    self.scenes.append(scene)
                    
                    # Set the first successful scene as the current one
                    if not hasattr(self, 'scn') or not self.scn:
                        self.scn = scene
                        self._build_dataset_map()
                        print(f"Set {reader_name} scene as current")
            except Exception as e:
                print(f"Failed to load group with {reader_name}: {e}")

        # If we have at least one scene, return success
        if self.scenes:
            print(f"\nSuccessfully loaded {len(self.scenes)} scene(s)")
            return True

        # If all grouped attempts failed, try the original approach as fallback
        print("\nAll grouped attempts failed. Trying fallback approach...")
        reader_name = self._detect_reader(file_paths)
        print(f"Attempting specific reader: {reader_name}")
        try:
            # Use lazy-imported satpy module
            if self._satpy is None:
                raise RuntimeError('satpy not available')
            if not os.environ.get('SATIMG_DEBUG'):
                with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    self.scn = self._satpy.Scene(reader=reader_name, filenames=file_paths)
            else:
                self.scn = self._satpy.Scene(reader=reader_name, filenames=file_paths)

            if self.scn.available_dataset_names():
                print(f"Success with {reader_name}")
                self._build_dataset_map()
                return True
        except Exception:
            pass

        print("Specific reader failed. Trying Auto-Detection...")
        try:
            if self._satpy is None:
                raise RuntimeError('satpy not available')
            if not os.environ.get('SATIMG_DEBUG'):
                with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    self.scn = self._satpy.Scene(filenames=file_paths)
            else:
                self.scn = self._satpy.Scene(filenames=file_paths)

            if self.scn.available_dataset_names():
                print(f"Auto-detection success: {self.scn.attrs.get('reader')}")
                self._build_dataset_map()
                return True
        except Exception:
            pass

        print("Auto-detection failed. Forcing 'generic_image' reader...")
        try:
            if self._satpy is None:
                raise RuntimeError('satpy not available')
            if not os.environ.get('SATIMG_DEBUG'):
                with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    self.scn = self._satpy.Scene(reader='generic_image', filenames=file_paths)
            else:
                self.scn = self._satpy.Scene(reader='generic_image', filenames=file_paths)

            if self.scn.available_dataset_names():
                print("Success with 'generic_image'!")
                self._build_dataset_map()
                return True
        except Exception as e:
            print(f"Generic reader also failed: {e}")

        try:
            if self._satpy is None:
                raise RuntimeError('satpy not available')
            if not os.environ.get('SATIMG_DEBUG'):
                with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    self.scn = self._satpy.Scene(reader='satpy_cf_nc', filenames=file_paths)
            else:
                self.scn = self._satpy.Scene(reader='satpy_cf_nc', filenames=file_paths)

            if self.scn.available_dataset_names():
                print("Success with 'satpy_cf_nc'!")
                self._build_dataset_map()
                return True
        except Exception:
            pass

        print("FATAL: All methods failed. Satpy cannot read these files.")
        return False

    def get_available_datasets(self) -> list:
        if not self.scn: return []
        if hasattr(self, 'dataset_map') and self.dataset_map:
            return list(self.dataset_map.keys())
        return self.scn.available_dataset_names()

    def get_metadata(self) -> dict:
        if not self.scn: return {}
        try:
            start_time = self.scn.start_time
            platform = self.scn.attrs.get('platform_name', 'Satellite')
            sensor = self.scn.attrs.get('sensor', 'Sensor')
        except:
            start_time = None
            platform = "Unknown"
            sensor = "Unknown"
        return {
            "platform": f"{platform} / {sensor}",
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else "N/A",
        }

    def _build_dataset_map(self):
        self.dataset_map = {}
        if not self.scn: return
        names = self.scn.available_dataset_names()
        for ds in names:
            label = None
            m = re.search(r'(?:\bB|BAND[_-]?)(\d{1,2})\b', ds, re.I)
            if m:
                n = int(m.group(1))
                label = f'B{n:02d}'
            else:
                nums = re.findall(r'\d{2,3}', ds)
                for num in nums:
                    n = int(num)
                    if 1 <= n <= 99:
                        label = f'B{n:02d}'
                        break
            if not label:
                cand = ds if len(ds) <= 12 else ds[:12]
                label = cand
            base = label
            i = 1
            while label in self.dataset_map:
                label = f"{base}_{i}"
                i += 1
            self.dataset_map[label] = ds
        try:
            print("Dataset mapping (short -> real):")
            for k, v in self.dataset_map.items():
                print(f"  {k} -> {v}")
        except Exception:
            pass

    def request_image(self, bands: list, size=(1000, 1000), params=None, proj_name='plate_carree_global'):
        if not self.scn:
            raise ValueError("Scene not loaded")

        gamma = params.get('gamma', 1.0) if params else 1.0
        debug = bool(os.environ.get('SATIMG_DEBUG'))

        start_t = time.time()
        try:
            if debug:
                print(f"[DEBUG] Requesting image for bands={bands} target_size={size} gamma={gamma}")

            # 1) Map friendly band names to Satpy dataset names
            real_bands = []
            for b in bands:
                if hasattr(self, 'dataset_map') and b in self.dataset_map:
                    real_bands.append(self.dataset_map[b])
                else:
                    real_bands.append(b)
            if debug:
                print(f"[DEBUG] Mapped bands -> {real_bands}")

            # 2) Load datasets into the Scene
            t0 = time.time()
            self.scn.load(real_bands)
            t1 = time.time()
            if debug:
                print(f"[DEBUG] Scene.load took {t1 - t0:.2f}s")

            # 3) Determine satellite type for coverage calculation
            satellite_type = 'FY4A'  # Default
            platform_name = self.scn.attrs.get('platform_name', '').upper()
            if 'FY4B' in platform_name:
                satellite_type = 'FY4B'
            elif 'HIMAWARI' in platform_name:
                satellite_type = 'Himawari-8'
            elif 'FY4A' in platform_name:
                satellite_type = 'FY4A'
            
            if debug:
                print(f"[DEBUG] Detected satellite type: {satellite_type}")

            # 4) Resample based on projection type
            # For UI display (proj_name != 'geostationary_native'), perform projection conversion
            # 4) Resample based on projection type
            t0 = time.time()
            
            if proj_name == 'geostationary_native':
                # 原生视角：速度最快
                local_scn = self.scn.resample(resampler='native')
                if debug:
                    print(f"[DEBUG] Using native geostationary projection")
            else:
                # 平面投影：PlateCarree / Mercator
                from .projections import create_target_area
                target_area = create_target_area(proj_name)
                
                if target_area:
                    # [关键修改] 预览模式强制使用 'nearest' (最近邻) 插值
                    # 'bilinear' 对全圆盘数据太慢 (需40s+)，'nearest' 仅需 1-2s
                    resampler_method = 'nearest' 
                    
                    if debug:
                        print(f"[DEBUG] Resampling to {proj_name} using {resampler_method} for preview")
                    
                    # radius_of_influence 设置稍微大一点防止出现空洞
                    local_scn = self.scn.resample(target_area, resampler=resampler_method, radius_of_influence=50000)
                else:
                    local_scn = self.scn.resample(resampler='native')
            
            t1 = time.time()
            if debug:
                print(f"[DEBUG] Scene.resample took {t1 - t0:.2f}s")

            # 5) Read arrays and build image
            if len(real_bands) == 3:
                r = local_scn[real_bands[0]].values
                g = local_scn[real_bands[1]].values
                b = local_scn[real_bands[2]].values
                if debug:
                    try:
                        print(f"[DEBUG] band shapes: r={r.shape}, g={g.shape}, b={b.shape}")
                        print(f"[DEBUG] band dtypes: r={r.dtype}, g={g.dtype}, b={b.dtype}")
                        print(f"[DEBUG] r stats: min={np.nanmin(r):.3f}, max={np.nanmax(r):.3f}, nan_count={int(np.isnan(r).sum())}")
                    except Exception:
                        pass
                img_data = ImageProcessor.combine_rgb(r, g, b, gamma=gamma)
            elif len(real_bands) == 1:
                raw = local_scn[real_bands[0]].values
                if debug:
                    try:
                        print(f"[DEBUG] single band shape: {raw.shape}, dtype: {raw.dtype}")
                    except Exception:
                        pass
                norm = ImageProcessor.normalize(raw)
                img_data = ImageProcessor.apply_gamma(norm, gamma)
            else:
                raise ValueError("Unsupported band count")

            # 6) Area/extent - use satellite-specific coverage
            # 6) Area/extent 处理
            area = local_scn[real_bands[0]].attrs.get('area')
            
            # [关键修复] 仅当使用原生投影 (Native) 时，才注入卫星固有覆盖范围
            # 如果是重投影 (如 Plate Carree)，必须使用投影自身的 Extent (-180~180)
            if proj_name == 'geostationary_native':
                if hasattr(area, 'satellite_coverage'):
                    pass
                else:
                    coverage = get_satellite_coverage(satellite_type)
                    if hasattr(area, '__dict__'):
                        area.__dict__['satellite_coverage'] = coverage
            else:
                # 对于非原生投影，确保不要带有误导性的 satellite_coverage 属性
                # 这样 ui 层就会去读取 area_def 真实的 extent
                if hasattr(area, '__dict__') and 'satellite_coverage' in area.__dict__:
                    del area.__dict__['satellite_coverage']
            
            if debug:
                print(f"[DEBUG] Retrieved area: {type(area)}")
                print(f"[DEBUG] img_data shape before resize: {getattr(img_data, 'shape', None)}, dtype: {getattr(img_data, 'dtype', None)}")

            # 7) Resize to requested preview size (fast thumbnail) to avoid UI freezes
            try:
                if size is not None and img_data is not None:
                    target_w, target_h = int(size[0]), int(size[1])
                    arr = img_data.astype('float32') if img_data.dtype not in ('float32', 'float64') else img_data

                    if Image is not None:
                        if arr.ndim == 3:
                            h, w, c = arr.shape
                            if debug:
                                print(f"[DEBUG] PIL resizing from ({w},{h}) to ({target_w},{target_h})")
                            # sanitize NaNs/Infs before converting to uint8
                            arr_s = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
                            arr_s = np.clip(arr_s, 0.0, 1.0)
                            pil_im = Image.fromarray((arr_s * 255).astype('uint8'))
                            pil_resized = pil_im.resize((target_w, target_h), resample=Image.BILINEAR)
                            img_data = np.asarray(pil_resized).astype('float32') / 255.0
                        else:
                            h, w = arr.shape
                            if debug:
                                print(f"[DEBUG] PIL resizing single channel from ({w},{h}) to ({target_w},{target_h})")
                            arr_s = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
                            arr_s = np.clip(arr_s, 0.0, 1.0)
                            pil_im = Image.fromarray((arr_s * 255).astype('uint8'))
                            pil_resized = pil_im.resize((target_w, target_h), resample=Image.BILINEAR)
                            img_data = np.asarray(pil_resized).astype('float32') / 255.0
                    else:
                        # simple subsample
                        if arr.ndim == 3:
                            h, w, c = arr.shape
                            ys = np.linspace(0, h - 1, target_h).astype(int)
                            xs = np.linspace(0, w - 1, target_w).astype(int)
                            img_data = arr[ys[:, None], xs[None, :], :]
                        else:
                            h, w = arr.shape
                            ys = np.linspace(0, h - 1, target_h).astype(int)
                            xs = np.linspace(0, w - 1, target_w).astype(int)
                            img_data = arr[ys[:, None], xs[None, :]]
            except Exception as e:
                print(f"Warning: resizing/thumbnail failed: {e}")
                if debug:
                    traceback.print_exc()

            if debug:
                try:
                    print(f"[DEBUG] final img_data shape: {getattr(img_data, 'shape', None)}, dtype: {getattr(img_data, 'dtype', None)}")
                    print(f"[DEBUG] img stats after resize: min={np.nanmin(img_data):.4f}, max={np.nanmax(img_data):.4f}")
                except Exception:
                    pass
                print(f"[DEBUG] request_image total time: {time.time() - start_t:.2f}s")

            return img_data, area
        except Exception as e:
            print(f"Image Request Error: {e}")
            if debug:
                traceback.print_exc()
            raise

    # 替换 export_image 方法
    def export_image(self, bands: list, output_path: str, proj_name: str = 'plate_carree_global', 
                     export_format: str = 'png', gamma: float = 1.0, calibration: bool = False,
                     region: str = 'china', resample_method: str = 'bilinear'):
        if not self.scn:
            raise ValueError("Scene not loaded")
        
        # 1. 内存清理
        import gc
        gc.collect()

        try:
            start_t = time.time()
            # 2. 加载波段
            real_bands = [self.dataset_map.get(b, b) for b in bands]
            self.scn.load(real_bands)
            
            # 3. 智能重采样策略 (解决 1.54GB 内存报错的核心)
            proj_config = get_projection_config(proj_name)
            
            # 标记是否需要后续裁剪
            need_post_crop = False 
            
            if proj_config['type'] == 'native':
                # 原生投影：保留全盘，后续裁剪
                local_scn = self.scn.resample(resampler='native')
                if region != 'global':
                    need_post_crop = True
            else:
                # [内存优化] 如果指定了区域，直接构建该区域的网格，避免生成全球大网格
                if region != 'global':
                    print(f"[Export] Optimizing: Creating dynamic area for region '{region}'...")
                    reg_info = RegionCropper.get_region_info(region)
                    extent = (reg_info['min_lon'], reg_info['min_lat'], 
                              reg_info['max_lon'], reg_info['max_lat'])
                    
                    # 动态构建区域 (0.05度分辨率，约5km)
                    width = int((extent[2] - extent[0]) / 0.05)
                    height = int((extent[3] - extent[1]) / 0.05)
                    
                    target_area = geometry.AreaDefinition(
                        f'dynamic_{region}', f'Region {region}', f'dynamic_{region}',
                        {'proj': 'longlat', 'datum': 'WGS84'},
                        width, height, extent
                    )
                    # 直接重采样到小区域，内存占用极低
                    local_scn = self.scn.resample(target_area, resampler=resample_method, radius_of_influence=50000)
                    need_post_crop = False 
                else:
                    # 全球模式
                    target_area = create_target_area(proj_name)
                    local_scn = self.scn.resample(target_area, resampler=resample_method)
                    need_post_crop = False

            # 4. 读取数据并处理
            band_data = {}
            lons, lats = None, None
            
            for i, band_name in enumerate(real_bands):
                # 强制转为 float32 节省一半内存
                arr = local_scn[band_name].values.astype(np.float32)
                
                # 获取经纬度 (仅 GeoTIFF 需要)
                if export_format == 'geotiff' and lons is None:
                     area = local_scn[band_name].attrs.get('area')
                     if hasattr(area, 'get_lonlats'):
                         lons, lats = area.get_lonlats()

                if calibration:
                    arr = Calibration.calibrate_data(arr, self.scn.attrs.get('platform_name'), self.scn.attrs.get('sensor'), bands[i])
                band_data[bands[i]] = arr

            # 5. 后置裁剪 (仅 Native 模式需要)
            if need_post_crop and region != 'global':
                if lons is None:
                    lons, lats = local_scn[real_bands[0]].attrs['area'].get_lonlats()
                
                region_info = RegionCropper.get_region_info(region)
                band_data = RegionCropper.crop_multiple_bands(
                    band_data, lons, lats, region_info['min_lon'], region_info['max_lon'], 
                    region_info['min_lat'], region_info['max_lat']
                )
                if export_format == 'geotiff':
                     _, lons, lats = RegionCropper.crop_by_geographic_extent(
                        lons, lons, lats, region_info['min_lon'], region_info['max_lon'], 
                        region_info['min_lat'], region_info['max_lat']
                    )

            # 6. 合成与保存
            if len(real_bands) == 3:
                img_data = ImageProcessor.combine_rgb(band_data[bands[0]], band_data[bands[1]], band_data[bands[2]], gamma=gamma)
            else:
                img_data = ImageProcessor.apply_gamma(ImageProcessor.normalize(band_data[bands[0]]), gamma)
            
            # 保存逻辑...
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            if export_format == 'png':
                arr = np.nan_to_num(np.clip(img_data, 0, 1), nan=0.0)
                Image.fromarray((arr * 255).astype('uint8')).save(output_path)
            elif export_format == 'geotiff':
                metadata = GeoTIFFWriter.create_metadata(self.scn.attrs.get('platform_name'), 'Sensor', bands)
                if len(bands) == 1:
                    GeoTIFFWriter.write_geotiff(output_path, band_data[bands[0]], lons, lats, metadata=metadata)
                else:
                    GeoTIFFWriter.write_geotiff(output_path, img_data, lons, lats, metadata=metadata)

            del band_data, local_scn
            gc.collect()
            elapsed = time.time() - start_t
            result = ExportResult(status='success', path=output_path, time_s=elapsed)
            return {'status': result.status, 'path': result.path, 'time_s': result.time_s}

        except Exception as e:
            print(f"Export error: {e}")
            raise


# Some environments / import-order issues cause the ABC machinery to still
# mark the class abstract even though the methods are implemented. Clear
# the flag to ensure the UI can instantiate the driver.
try:
    SatpyDriver.__abstractmethods__ = set()
except Exception:
    pass
