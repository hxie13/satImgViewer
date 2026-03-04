"""
Satellite Image Manager (Facade)

Central facade coordinating drivers, pipelines, and projections.
Provides simplified interface for satellite image processing.
"""
import os
import glob
import re
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
import numpy as np

from .drivers import DriverFactory, BaseSatelliteDriver
from .drivers.base import SatelliteFileInfo, ProcessingParams
from .geometry import ProjectionFactory, ProjectionType
from .pipelines import RGBCompositorFactory, EnhancementPipeline
from .config import get_satellite_config, get_band_display_name
from .file_recognizer import FileTypeRecognizer, get_recommended_reader

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result from image processing."""
    image: np.ndarray
    area_def: Any
    metadata: Dict[str, Any]
    driver_type: str
    processing_time: float


class SatelliteImageManager:
    """
    Facade for satellite image processing.

    Coordinates drivers, pipelines, and projections to provide
    unified interface for loading, processing, and exporting images.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize manager.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self._driver: Optional[BaseSatelliteDriver] = None
        self._driver_type: Optional[str] = None
        self._pipeline = EnhancementPipeline.create_default()
        self._compositor = RGBCompositorFactory.create('linear')

        # Cache for time-series data
        self._time_groups: List[List[str]] = []
        self._current_frame = 0
        self._lock = threading.RLock()

        # Initialize logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging."""
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    # =====================================================================
    # File Handling
    # =====================================================================

    def scan_directory(self, directory: str,
                      patterns: Optional[List[str]] = None) -> List[str]:
        """
        Scan directory for satellite data files.

        Args:
            directory: Directory to scan
            patterns: Optional file patterns (defaults to standard patterns)

        Returns:
            List of matching file paths
        """
        if patterns is not None:
            # Custom patterns: keep original glob behaviour for backward compatibility
            all_files = []
            for pattern in patterns:
                all_files.extend(glob.glob(os.path.join(directory, pattern)))
            return sorted(all_files)

        # Default: single-pass scandir is ~7× faster than 7 separate glob calls
        EXTS = {'.nc', '.NC', '.dat', '.DAT', '.bz2', '.h5', '.H5', '.hdf', '.HDF'}
        all_files = []
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.is_file() and os.path.splitext(entry.name)[1] in EXTS:
                        all_files.append(entry.path)
        except OSError as e:
            self.logger.warning(f"scan_directory error: {e}")
        return sorted(all_files)

    def identify_files(self, file_paths: List[str]) -> List[SatelliteFileInfo]:
        """
        Identify satellite types from file list.

        Args:
            file_paths: List of file paths

        Returns:
            List of SatelliteFileInfo objects
        """
        return DriverFactory.identify_files(file_paths)

    def get_time_series_groups(self, file_paths: List[str],
                               driver_type: Optional[str] = None) -> List[List[str]]:
        """
        Group file paths by timestamp for time-series processing.

        This method can be called without loading data first to preview
        the number of time frames available.

        Args:
            file_paths: List of file paths
            driver_type: Optional known driver type; when provided, skips
                         auto-detection (DriverFactory.create_from_files) and
                         directly instantiates the driver, avoiding a redundant
                         identify_files() call.

        Returns:
            List of file groups, each group represents one time point
        """
        try:
            if driver_type:
                # Known type: O(1) instantiation, no file scanning
                temp_driver = DriverFactory.create_driver(driver_type)
            else:
                # Unknown type: fall back to auto-detection
                temp_driver = DriverFactory.create_from_files(file_paths, auto_detect=True)
            return temp_driver.get_time_series_groups(file_paths)
        except Exception as e:
            self.logger.warning(f"Could not create driver for grouping: {e}")
            # Fallback: basic timestamp-based grouping (BaseSatelliteDriver method
            # is an instance method so we call it unbound with a dummy receiver)
            return BaseSatelliteDriver.get_time_series_groups(None, file_paths)

    def load_files(self, file_paths: List[str],
                   auto_detect: bool = True,
                   driver_type: Optional[str] = None,
                   reuse_session: bool = True,
                   pinned_driver_type: Optional[str] = None) -> bool:
        """
        Load satellite data from files.

        Args:
            file_paths: List of file paths
            auto_detect: Automatically detect satellite type
            driver_type: Explicit driver type if not auto-detecting
            reuse_session: Reuse current driver session when possible
            pinned_driver_type: Preferred/forced driver type for this session

        Returns:
            True if loading successful
        """
        t0 = time.perf_counter()
        with self._lock:
            try:
                if not file_paths:
                    self.logger.error("No file paths provided to load_files")
                    return False

                requested_type = pinned_driver_type or driver_type
                current_type = self._infer_current_driver_type()
                target_type = requested_type or current_type
                # Always compute reader hint once so explicit driver mode can also use smart path.
                recommended_reader = get_recommended_reader(file_paths)
                if recommended_reader:
                    self.logger.info(f"[SmartLoad] FileTypeRecognizer recommends: {recommended_reader}")

                # Resolve the driver type implied by the recommended reader so that
                # switching satellite type (e.g. FY-4 → FY-3D) always creates a fresh driver.
                recommended_driver = None
                if recommended_reader and recommended_reader != 'auto':
                    recommended_driver = DriverFactory._reader_to_driver_type(recommended_reader)
                    if recommended_driver is None:
                        recommended_driver = DriverFactory._infer_driver_type_from_generic_reader(
                            file_paths, recommended_reader
                        )

                should_reuse = (
                    reuse_session and
                    self._driver is not None and
                    (target_type is None or current_type == target_type) and
                    # Don't reuse if the recognizer says we've switched satellite families
                    (recommended_driver is None or current_type == recommended_driver)
                )

                if not should_reuse:
                    if requested_type:
                        self._driver = DriverFactory.create_driver(requested_type)
                        self._driver_type = requested_type
                    else:
                        self._driver = DriverFactory.create_from_files(
                            file_paths, 
                            auto_detect=auto_detect,
                            preferred_reader=recommended_reader
                        )
                        self._driver_type = self._infer_current_driver_type()
                elif self._driver_type is None:
                    self._driver_type = current_type

                success = bool(self._driver and self._driver.load(file_paths))

                if success:
                    self.logger.info(f"Successfully loaded data with {self._driver}")
                    # Build time groups
                    self._time_groups = self._driver.get_time_series_groups(file_paths)
                    self._current_frame = 0
                else:
                    # If reusing current driver failed and type wasn't explicit, fallback to auto-detection.
                    if should_reuse and requested_type is None:
                        self.logger.warning(
                            "Reuse-session load failed; retrying with driver auto-detection."
                        )
                        self._driver = DriverFactory.create_from_files(
                            file_paths, auto_detect=auto_detect
                        )
                        self._driver_type = self._infer_current_driver_type()
                        success = bool(self._driver and self._driver.load(file_paths))
                        if success:
                            self._time_groups = self._driver.get_time_series_groups(file_paths)
                            self._current_frame = 0
                    if not success:
                        self.logger.error("Failed to load files")

                return success

            except Exception as e:
                self.logger.error(f"Error loading files: {e}")
                return False
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                self.logger.info(f"[Perf] load_files: {dt_ms:.1f} ms")

    def reload_current(self, file_paths: List[str]) -> bool:
        """
        Reload frame files using the current driver instance without factory detection.

        Args:
            file_paths: Frame file list to load

        Returns:
            True if reloading successful
        """
        t0 = time.perf_counter()
        with self._lock:
            try:
                if not self._driver:
                    self.logger.error("reload_current called without an active driver")
                    return False
                if not file_paths:
                    self.logger.error("No file paths provided to reload_current")
                    return False

                ok = bool(self._driver.load(file_paths))
                if ok:
                    self._time_groups = [list(file_paths)]
                    self._current_frame = 0
                return ok
            except Exception as e:
                self.logger.error(f"Error in reload_current: {e}")
                return False
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                self.logger.info(f"[Perf] reload_current: {dt_ms:.1f} ms")

    def unload(self) -> None:
        """Unload current data and release resources."""
        with self._lock:
            if self._driver:
                self._driver.unload()
                self._driver = None
            self._driver_type = None
            self._time_groups.clear()
            self._current_frame = 0

    @property
    def is_loaded(self) -> bool:
        """Check if data is loaded."""
        return self._driver is not None and self._driver.is_loaded

    @property
    def current_driver(self) -> Optional[BaseSatelliteDriver]:
        """Get current driver."""
        return self._driver

    @property
    def current_driver_type(self) -> Optional[str]:
        """Get current driver type key as registered in DriverFactory."""
        if self._driver_type:
            return self._driver_type
        return self._infer_current_driver_type()

    def _infer_current_driver_type(self) -> Optional[str]:
        """Infer current driver type by matching class against DriverFactory registry."""
        if self._driver is None:
            return None
        for name, cls in DriverFactory.get_registry().items():
            if isinstance(self._driver, cls):
                return name
        return None

    # =====================================================================
    # Image Processing
    # =====================================================================

    def set_enhancement_pipeline(self, pipeline: EnhancementPipeline) -> None:
        """
        Set custom enhancement pipeline.

        Args:
            pipeline: EnhancementPipeline instance
        """
        self._pipeline = pipeline

    def set_compositor(self, method: str = 'linear') -> None:
        """
        Set RGB compositor method.

        Args:
            method: Compositing method ('linear', 'percentile', 'histogram')
        """
        self._compositor = RGBCompositorFactory.create(method)

    def get_available_bands(self) -> List[Dict[str, Any]]:
        """
        Get list of available bands with display information.

        Returns:
            List of band information dictionaries
        """
        if not self._driver:
            return []

        bands = self._driver.get_available_bands()
        return [
            {
                'canonical': band.canonical_name,
                'display': band.display_name,
                'resolution': band.resolution,
                'is_thermal': band.is_thermal,
                'is_visible': band.is_visible,
            }
            for band in bands
        ]

    def process_image(self,
                     bands: List[str],
                     gamma: float = 1.0,
                     proj_name: str = 'geostationary_native',
                     size: Optional[Tuple[int, int]] = None,
                     compositor: Optional[str] = None,
                     resample_method: Optional[str] = None,
                     quality_profile: str = "default") -> Tuple[np.ndarray, Any]:
        """
        Generate image from specified bands.

        Args:
            bands: List of band names (canonical)
            gamma: Gamma correction value
            proj_name: Output projection name
            size: Optional output size (width, height)
            compositor: Optional compositor override

        Returns:
            Tuple of (image_array, area_definition)
        """
        if not self.is_loaded:
            from .exceptions import SatDataLoadError
            raise SatDataLoadError("No satellite data is currently loaded. Please load data first.")

        t0 = time.perf_counter()
        with self._lock:
            # Pick runtime defaults by quality profile.
            if resample_method is None:
                if quality_profile == "preview_fast":
                    resample_method = "nearest"
                elif quality_profile == "export_high":
                    resample_method = "bilinear"
                else:
                    resample_method = "nearest"

            # Build processing params
            params = ProcessingParams(
                bands=bands,
                gamma=gamma,
                output_size=size,
                output_proj=proj_name,
                resample_method=resample_method,
                quality_profile=quality_profile,
            )

            # Generate image via driver
            image, area_def = self._driver.request_image(params)

            # Apply enhancements
            image = self._pipeline.enhance(image)

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.logger.info(f"[Perf] process_image: {dt_ms:.1f} ms (profile={quality_profile})")
        return image, area_def

    def generate_rgb(self,
                    r_band: str,
                    g_band: str,
                    b_band: str,
                    gamma: float = 1.0,
                    proj_name: str = 'geostationary_native',
                    compositor: Optional[str] = None) -> Tuple[np.ndarray, Any]:
        """
        Generate RGB composite image.

        Args:
            r_band: Red band (canonical name)
            g_band: Green band (canonical name)
            b_band: Blue band (canonical name)
            gamma: Gamma correction
            proj_name: Output projection
            compositor: Optional compositor override

        Returns:
            Tuple of (RGB image, area_definition)
        """
        if not self.is_loaded:
            raise ValueError("No data loaded")

        bands = [r_band, g_band, b_band]

        # Build params
        params = ProcessingParams(
            bands=bands,
            gamma=gamma,
            output_proj=proj_name,
        )

        # Generate image
        with self._lock:
            image, area_def = self._driver.request_image(params)

        # Apply compositor
        comp = compositor or self._compositor

        # Map bands to data
        band_order = [r_band, g_band, b_band]
        # The driver returns combined image, so we use it directly
        # For more control, we could load individual bands

        # Apply gamma
        if gamma != 1.0:
            image = comp.apply_gamma(image, gamma)

        return image, area_def

    def get_metadata(self) -> Dict[str, Any]:
        """Get current scene metadata."""
        if not self._driver:
            return {}

        metadata = self._driver.get_metadata()

        # Add driver info
        metadata['driver'] = self._driver.__class__.__name__

        return metadata

    # =====================================================================
    # Time Series Support
    # =====================================================================

    @property
    def time_groups(self) -> List[List[str]]:
        """Get time-sorted file groups."""
        return self._time_groups.copy()

    @property
    def current_frame(self) -> int:
        """Get current frame index."""
        return self._current_frame

    def set_frame(self, index: int) -> bool:
        """
        Set current frame by index.

        Args:
            index: Frame index

        Returns:
            True if successful
        """
        with self._lock:
            if not self._time_groups:
                return False

            if 0 <= index < len(self._time_groups):
                self._current_frame = index
                files = self._time_groups[index]
                return self._driver.load(files)

            return False

    def get_frame_count(self) -> int:
        """Get total number of frames."""
        return len(self._time_groups)

    # =====================================================================
    # Projection Support
    # =====================================================================

    def get_available_projections(self) -> List[Dict[str, str]]:
        """
        Get list of available projections.

        Returns:
            List of projection info dictionaries
        """
        return [
            {'id': name, 'name': config.name, 'description': config.description}
            for name, config in ProjectionFactory._registry.items()
        ]

    def create_custom_projection(self,
                                name: str,
                                center_lon: float,
                                center_lat: float,
                                width: int = 1000,
                                height: int = 1000,
                                resolution: float = 0.01,
                                proj_type: str = 'plate_carree') -> bool:
        """
        Create custom projection.

        Args:
            name: Projection name
            center_lon: Center longitude
            center_lat: Center latitude
            width: Output width
            height: Output height
            resolution: Resolution
            proj_type: Projection type

        Returns:
            True if creation successful
        """
        try:
            proj_enum = ProjectionType(proj_type)
            ProjectionFactory.create_custom(
                name=name,
                proj_type=proj_enum,
                center_lon=center_lon,
                center_lat=center_lat,
                width=width,
                height=height,
                resolution=resolution,
            )
            return True
        except (ValueError, Exception) as e:
            self.logger.error(f"Failed to create projection: {e}")
            return False

    # =====================================================================
    # Export Support
    # =====================================================================

    def export_image(self,
                    output_path: str,
                    bands: List[str],
                    gamma: float = 1.0,
                    proj_name: str = 'geostationary_native',
                    format: str = 'png') -> Dict[str, Any]:
        """
        Export image to file.

        Args:
            output_path: Output file path
            bands: Band names to use
            gamma: Gamma correction
            proj_name: Output projection
            format: Output format ('png', 'geotiff')

        Returns:
            Dictionary with export result
        """
        if not self.is_loaded:
            raise ValueError("No data loaded")

        t0 = time.perf_counter()

        # Generate image
        image, area_def = self.process_image(
            bands=bands,
            gamma=gamma,
            proj_name=proj_name,
            quality_profile='export_high',
        )

        # Convert to uint8
        img_uint8 = (np.clip(image, 0, 1) * 255).astype(np.uint8)

        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        # Save based on format
        try:
            from PIL import Image

            if format == 'png':
                img = Image.fromarray(img_uint8, mode='RGB')
                img.save(output_path)
            elif format == 'geotiff':
                self._export_geotiff(output_path, image, area_def)
            else:
                raise ValueError(f"Unsupported format: {format}")

            return {'success': True, 'path': output_path}

        except ImportError:
            self.logger.warning("PIL not available, using numpy save")
            np.save(output_path.replace('.png', '.npy'), image)
            return {'success': True, 'path': output_path}
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.logger.info(f"[Perf] export_image: {dt_ms:.1f} ms ({format})")

    def _export_geotiff(self, output_path: str, image: np.ndarray,
                        area_def: Any) -> None:
        """Export as GeoTIFF."""
        try:
            from osgeo import gdal, osr
            import numpy as np

            # Normalize to CHW layout for GDAL writing.
            if image.ndim == 2:
                chw = image[np.newaxis, ...]
            elif image.ndim == 3:
                # HWC if last dim is channel-like
                if image.shape[-1] in (1, 3, 4):
                    chw = np.moveaxis(image, -1, 0)
                # CHW if first dim is channel-like
                elif image.shape[0] in (1, 3, 4):
                    chw = image
                else:
                    # Conservative fallback: treat as HWC
                    chw = np.moveaxis(image, -1, 0)
            else:
                raise ValueError(f"Unsupported GeoTIFF image shape: {image.shape}")

            bands, height, width = chw.shape

            # Create driver
            driver = gdal.GetDriverByName('GTiff')
            out_ds = driver.Create(output_path, width, height, bands, gdal.GDT_Float32)

            # Set geotransform from area_def
            if area_def and hasattr(area_def, 'area_extent'):
                extent = area_def.area_extent
                x_res = (extent[2] - extent[0]) / width
                y_res = (extent[3] - extent[1]) / height
                geotransform = (extent[0], x_res, 0, extent[3], 0, -y_res)
                out_ds.SetGeoTransform(geotransform)

            # Set projection
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            out_ds.SetProjection(srs.ExportToWkt())

            # Write data
            for i in range(bands):
                out_ds.GetRasterBand(i + 1).WriteArray(chw[i])

            out_ds = None

        except ImportError:
            self.logger.error("GDAL not available for GeoTIFF export")
            raise

    # =====================================================================
    # Utility Methods
    # =====================================================================

    def get_driver_info(self) -> Dict[str, Any]:
        """Get information about current driver."""
        if not self._driver:
            return {}

        return {
            'class': self._driver.__class__.__name__,
            'satellite_type': self._driver.SATELLITE_TYPE.value,
            'is_loaded': self._driver.is_loaded,
        }

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for current satellite."""
        if not self._driver:
            return None
        return self._driver.get_satellite_coverage()

    def __repr__(self) -> str:
        driver_name = self._driver.__class__.__name__ if self._driver else "None"
        return f"SatelliteImageManager(driver={driver_name}, frames={len(self._time_groups)})"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.unload()
        return False
