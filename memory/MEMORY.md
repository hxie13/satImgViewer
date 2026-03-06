# 项目记忆：卫星图像查看器 (satImgViewer)

## 项目架构（当前状态）

### 模块化重构（进行中）

旧架构（已弃用但保留）：
- `core/satpy_driver.py` → `SatpyDriver(ISatelliteDataProvider)` - 标记弃用

新架构（主要代码路径）：
- `core/manager.py` → `SatelliteImageManager` (Facade)
- `core/drivers/` → 各卫星驱动
- `core/geometry/projections.py` → `ProjectionFactory`
- `core/config.py` → `PROJECTION_GRID_SHAPES`, `PROJECTION_GRID_EXTENTS`, 波段配置
- `ui/controllers/` → `ImageViewController`, `TimeSeriesController`, `ExportController`

### 数据流

```
用户 → MainWindow → ImageViewController → ImageLoaderWorker
→ SatelliteImageManager.process_image()
→ [XxxDriver].request_image(params) → (img_array, AreaDefinition)
→ GeoCanvas.update_image(img, area_def)
→ Cartopy imshow(img, transform=..., extent=...)
```

## 驱动支持状态

| 卫星 | 驱动文件 | 类型 | 状态 |
|------|---------|------|------|
| FY4A/FY4B | `core/drivers/fengyun.py` | 静止，全圆盘 | ✅ 正常 |
| Himawari-8/9 | `core/drivers/himawari.py` | 静止，全圆盘 | ✅ 正常 |
| FY3D MERSI | `core/drivers/fengyun3d.py` | 极轨，Swath | ✅ 已修复 |

## 已修复的关键 Bug（2026-02-26）

### Bug A: FY3D `needs_resampling` 逻辑错误
**文件**: `core/drivers/fengyun3d.py` 第 1165 行
**问题**: 默认投影 `geostationary_native` 时极轨 Swath 数据跳过重采样
**修复**: `is_swath=True` 时始终 `needs_resampling=True`；`geostationary_native` 时 `effective_proj=None` 触发自定义格网路径

### Bug B: Canvas 缺少 longlat 动态格网处理路径
**文件**: `ui/canvas.py`，`update_image()` 第 169 行
**问题**: `proj='longlat'` 的动态尺寸 AreaDefinition 无专用路径，`target_extent=None`
**修复**: 插入情况3b：识别 `proj in ('longlat', 'latlong', 'eqc')`，正确提取 `area_extent`

### Bug C: `create_from_extent` 返回 `ProjectionConfig` 而非 `AreaDefinition`
**文件**: `core/drivers/fengyun3d.py` 第 1199 行
**问题**: `ProjectionFactory.create_from_extent()` 返回数据类不是 pyresample 对象
**修复**: 直接用 `pyresample.geometry.AreaDefinition(...)` 构建，与 `polar_base.py` 模式一致

### Bug D: `geo_utils.py` 检查不存在的 `satellite_coverage` 属性
**文件**: `core/geo_utils.py` 第 30 行
**修复**: 替换为 longlat AreaDefinition 的快速路径（直接读取 `area_extent`）

### Bug E: FY3D 地理定位获取失败（2026-02-26）
**文件**: `core/drivers/fengyun3d.py`
**问题**: 三重失败 —
1. `load()` 只用主文件创建 satpy Scene，不含 GEO 文件，导致 `scene['4'].attrs['area']` 为 None
2. GEO 文件查找代码用 `self._scene.filenames`（不存在），永远为 False
3. `_extract_geolocation_from_hdf()` 用 `self._scene.filenames` 获取路径，同样失败
**修复**:
1. `load()` 中保存 `self._primary_file_path`，并调用 `_find_geo_file()` 将 GEO 文件加入 `scene_filenames`
2. 自动检测路径（auto-detection fallback）也使用 `scene_filenames`
3. `request_image()` 中改用 `self._primary_file_path` 查找 GEO 文件
4. `_extract_geolocation_from_hdf()` 改用 `self._primary_file_path` 获取 HDF 文件路径
5. `unload()` 中增加清理 `_primary_file_path`, `_swath_lons`, `_swath_lats`, `_geo_file_path`
6. 删除了 `__pycache__` 中的两个 stale `.pyc` 文件（Python 3.11 和 3.12）

## Canvas 投影判断逻辑（canvas.py update_image）

| 情况 | 条件 | CRS | extent来源 |
|------|------|-----|-----------|
| 1 | `is_global_grid`（3600×1800） | PlateCarree | PROJECTION_GRID_EXTENTS |
| 2 | `is_china_region`（1240×700） | PlateCarree | PROJECTION_GRID_EXTENTS |
| 3 | `is_geos and not is_global_grid` | Geostationary | area_extent（米） |
| 3b | `proj in ('longlat',...)` | PlateCarree | area_extent（度，西南东北） |
| 4 | 其他 | PlateCarree | area_extent（通用） |

**注意**：`area_extent` 格式为 `(west, south, east, north)`，imshow extent 格式为 `(west, east, south, north)`，转换：`(ae[0], ae[2], ae[1], ae[3])`

## 重要约束

- `ProjectionFactory.create_from_extent()` 返回 `ProjectionConfig`（数据类），不是 pyresample `AreaDefinition` — 不能直接传给 `resample_nearest()`
- `BasePolarDriver.resample_swath_to_grid()` 是正确的 Swath→Grid 封装，内部构建正确的 AreaDefinition
- 极轨卫星数据必须提供 GEO 文件（`_GEO1K_MS.HDF`）或 HDF5 内嵌 lon/lat 以获取地理位置

## 调试命令

```bash
conda activate satImgLib
SATIMG_DEBUG=1 python main.py
```

## 文件结构速查

```
satImgViewer/
├── main.py
├── core/
│   ├── manager.py          # SatelliteImageManager (Facade)
│   ├── config.py           # PROJECTION_GRID_SHAPES, 波段配置
│   ├── geo_utils.py        # get_geographic_extent()
│   ├── image_proc.py       # normalize_percentile(), apply_gamma()
│   ├── app_state.py        # AppState dataclass
│   ├── drivers/
│   │   ├── base.py         # BaseSatelliteDriver, ProcessingParams
│   │   ├── polar_base.py   # BasePolarDriver, resample_swath_to_grid()
│   │   ├── fengyun.py      # FY4A/FY4B
│   │   ├── fengyun3d.py    # FY3D MERSI (极轨)
│   │   └── himawari.py     # Himawari-8/9
│   ├── geometry/
│   │   └── projections.py  # ProjectionFactory
│   └── pipelines/
│       └── compositors.py
├── ui/
│   ├── canvas.py           # GeoCanvas (2D Cartopy)
│   ├── globe_canvas.py     # Globe3DCanvas (3D VisPy)
│   ├── main_window.py
│   ├── widgets.py
│   └── controllers/
│       ├── image_controller.py
│       ├── timeseries_controller.py
│       └── export_controller.py
└── utils/
    └── workers.py          # ImageLoaderWorker, VideoExportWorker
```

## 2026-03-04 Engineering Memory Update

### What changed
- Added FY3D-China projection risk warning in `ui/main_window.py`:
  - Triggered on projection selection.
  - Re-checked before `run_process()` when needed.
- Extended FY3D metadata in `core/drivers/fengyun3d.py`:
  - Added `swath_extent`.
  - Added `swath_overlaps_china`.
- Reworked 3D globe seam handling in `ui/globe_canvas.py`:
  - Replaced default sphere creation with seam-safe UV sphere topology.
  - Added texture horizontal wrap enforcement for seam columns.
  - Disabled graticule by default to avoid visual confusion with seam lines.

### Important implementation details
- `QComboBox` signal is `currentIndexChanged` (not `currentDataChanged`) in this runtime.
- Projection risk warning key uses current frame/time metadata to avoid repeated popups.
- Seam fix is geometric-first (mesh topology), not only texture post-processing.

### Validation done
- Compile checks passed:
  - `python -m compileall -q core ui utils main.py`
  - `python -m compileall -q ui/globe_canvas.py ui/main_window.py core/drivers/fengyun3d.py`

### Next recommended verification in satImgLib
- Launch app and validate:
  - FY3D frame with/without China coverage under `plate_carree_china`.
  - 3D globe view seam visibility under multiple camera azimuth angles.

## 2026-03-04 Engineering Memory Update (Projection Extent)

### What changed
- Replaced hardcoded geostationary extent heuristics in `core/geometry/projections.py`:
  - Removed fixed FY4/Himawari ranges used in `_get_satellite_actual_extent()`.
  - Added dynamic extent extraction from `source_area.get_lonlats()` valid pixels.
- Added longitude circular-span analysis helpers:
  - `_wrap_longitudes_180()`
  - `_compute_circular_lon_bounds()`
  - `_sample_area_lonlats()`
  - `_extract_valid_lonlat_extent()`
- Updated both projection entry points to use the same dynamic logic:
  - `ProjectionFactory._get_satellite_actual_extent()`
  - module-level `get_geographic_extent()`

### Dateline handling strategy
- Dateline crossing is detected from circular longitude gaps.
- Current project pipeline expects a single non-wrapping longlat bbox.
- For crossing scenes, code falls back to a conservative non-wrapping envelope to avoid pixel loss and avoid invalid target-area behavior in current render/resample paths.

### Validation done
- `conda run -n satImgLib ruff check core/geometry/projections.py`
- `python -m py_compile core/geometry/projections.py`
- `python -m compileall -q core ui utils main.py`
- Runtime smoke in `satImgLib`:
  - `ProjectionFactory._get_satellite_actual_extent(src_geos)` now returns dynamic bounds from lon/lat samples instead of fixed ranges.

## 2026-03-06 Engineering Memory Update (Scene + Recipe Refactor)

### Core refactor focus
- Raised the runtime object model from raw file groups to normalized scenes:
  - `SourceFileRecord` / `NormalizedScene` / `SceneCollection`
  - shared analysis-grid baseline via `AnalysisGridDefinition`
- Continued pushing the same idea downstream:
  - scene-aware loading in manager / time-series controller
  - scene-aware video export path
  - unified render/export request objects and `ProductRecipe`

### Current architecture progress
- Ingest layer is now explicit:
  - `core/ingest/` handles scan + recognize + scene normalization
  - `core/scene/` defines normalized scene/grid models
- Runtime loading is now dual-compatible but scene-first:
  - `SatelliteImageManager.load_scene(scene)` added
  - `FrameLoaderWorker` and `VideoExportWorker` can consume normalized scenes
  - `AppState` now owns normalized scenes and keeps compatibility `file_groups`
- Product request layer is now explicit:
  - `RenderRequest`
  - `StillExportRequest`
  - `VideoExportRequest`
  - `ProductRecipe`

### What the UI now does
- Folder loading builds `SceneCollection` first, instead of directly grouping raw files.
- Main window now builds a `ProductRecipe` from current UI selections, then derives:
  - preview request
  - 3D texture request
  - still export request
  - video export request
- This reduces duplicated parameter assembly in `main_window.py`.

### Verification status
- Passed:
  - `python -m compileall -q core ui utils tests`
  - `pytest tests/test_product_requests.py tests/test_manager_render_requests.py tests/test_app_state.py tests/test_scene_ingest.py tests/test_manager_scene_loading.py tests/test_driver_factory.py tests/test_timeseries_controller.py`
- Latest result:
  - `27 passed, 1 skipped`
- Skipped item:
  - Qt controller tests remain environment-dependent because current CLI runtime lacks usable PyQt6 runtime libraries.

### Next recommended step
- Promote `ProductRecipe` from a transient UI selection wrapper into a registry-backed standard product template system:
  - examples: `NaturalColor`, `DustRGB`, `FogRGB`, `CTT Export`
  - this would become the base for batch processing and formal product generation.
