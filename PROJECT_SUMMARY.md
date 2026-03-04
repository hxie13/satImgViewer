# satImgViewer 项目评审报告（产品 Review 版）

> 更新时间：2026-03-03
> 评审依据：当前仓库代码实现（`core/`、`ui/`、`utils/`），面向“功能闭环 + 工程质量 + 交付风险”。

## 1. Executive Summary（结论先行）

- 项目已具备可用的业务闭环：`加载数据 -> 选波段 -> 投影处理 -> 2D/3D显示 -> 时序播放 -> 图片/视频导出`。
- 现阶段判断为 `Beta/重构过渡期`：新架构（`manager + drivers + controllers`）已建立，但 UI 层仍存在新旧逻辑并行。
- 主要优势：多卫星驱动抽象较清晰，投影与处理流水线具备扩展基础，功能覆盖面较完整。
- 主要风险：线程终止方式、并发访问同一 manager、导出维度约定、依赖清单不完整、调试代码外泄到生产路径。
- 总体建议：下一迭代优先做稳定性与架构收口，再推进性能与体验优化。

---

## 2. 产品定位与目标用户

### 2.1 产品定位

satImgViewer 是面向遥感/气象业务的桌面端卫星影像处理与可视化工具，重点解决“多源数据快速浏览与导出”的效率问题。

### 2.2 目标用户

- 遥感算法工程师：需要快速验证波段组合、投影效果与时序变化。
- 气象业务分析人员：需要快速生成可视化产品（PNG/GeoTIFF/MP4）。
- 研发测试人员：需要对不同数据源 reader 与处理链路做兼容性验证。

---

## 3. 当前功能矩阵（基于代码实现）

| 功能域 | 现状 | 关键实现 | 备注 |
|---|---|---|---|
| 数据扫描与识别 | 已实现 | `core/manager.py`、`core/drivers/__init__.py` | 支持目录扫描与文件类型自动识别 |
| 卫星驱动 | 已实现 | `FengYunDriver`、`HimawariDriver`、`FengYun3DDriver` | 覆盖 FY4A/FY4B、H08/H09、FY3D(MERSI) |
| 波段管理与映射 | 已实现 | `core/config.py`、各 driver `dataset_map` | 统一 canonical band 设计已落地 |
| 图像处理流水线 | 已实现（有优化空间） | `core/pipeline.py`、`core/pipelines/*` | 支持 normalize/composite/resample/gamma |
| 2D 地图可视化 | 已实现 | `ui/canvas.py` (Cartopy + Matplotlib) | 支持多投影显示与降级像素模式 |
| 3D 地球显示 | 已实现 | `ui/globe_canvas.py` (VisPy) | 支持底图叠加、透明度调节 |
| 时序播放 | 已实现 | `ui/main_window.py`、`TimeSeriesController` | slider + 前后帧 + 元数据时间显示 |
| 图片导出 | 已实现 | `SatelliteImageManager.export_image` | PNG / GeoTIFF |
| 视频导出 | 已实现 | `utils/workers.VideoExportWorker` | MP4 导出，支持取消 |
| 控制层解耦（MVP） | 部分实现 | `ui/controllers/*` | 控制器已建，但 MainWindow 仍保留较多直连逻辑 |

---

## 4. 端到端功能逻辑（用户视角）

### 4.1 数据加载

1. 用户选择数据目录。  
2. `SatelliteImageManager.scan_directory()` 扫描文件。  
3. `DriverFactory.identify_files()` 识别卫星类型。  
4. 按时间分组并加载首帧，更新可选波段列表与时间标签。

### 4.2 图像生成与显示

1. 用户选择单波段或 RGB 三波段，选择投影与 gamma。  
2. `ImageLoaderWorker` 后台调用 `manager.process_image()`。  
3. manager 将请求转发给当前 driver，driver 负责 band 解析、scene load、重采样与归一化组合。  
4. 返回图像后更新 2D 画布；3D 视图根据投影情况使用当前图像或额外生成 plate-carree 纹理。

### 4.3 时序播放

1. 用户通过滑条/前后按钮切换 frame。  
2. frame 对应文件组重新加载。  
3. 若 RGB 已选定，自动触发重新出图。  
4. UI 更新时间与帧序号。

### 4.4 导出

1. 用户选择输出路径和格式（PNG/GeoTIFF）。  
2. manager 重新执行目标投影下的处理流程并落盘。  
3. 视频导出遍历全部 frame，逐帧写入 MP4。

---

## 5. 工程架构审查

### 5.1 当前架构分层（方向正确）

- `core/drivers/*`：数据源与 reader 适配层。  
- `core/manager.py`：对上提供统一 Facade。  
- `core/geometry/*`：投影配置与 AreaDefinition 生成。  
- `core/pipeline.py` + `core/pipelines/*`：图像处理节点化。  
- `ui/*`：窗口、画布、交互组件。  
- `ui/controllers/*`：MVP 控制器（处于接管中）。  
- `utils/workers.py`：异步任务执行（图像、批导、视频）。

### 5.2 架构亮点

- 驱动工厂模式清晰，便于后续扩展更多卫星源。  
- 波段 canonical 统一策略有助于跨卫星复用 UI/算法逻辑。  
- 投影工厂支持预设与动态创建，具备业务扩展弹性。  
- AppState 已建立，具备向“可维护状态管理”演进基础。

### 5.3 核心风险清单（按优先级）

| 优先级 | 问题 | 影响 | 证据（模块） | 建议 |
|---|---|---|---|---|
| P0 | 使用 `QThread.terminate()` 强制终止线程 | 资源泄露/状态破坏/随机崩溃风险 | `ui/controllers/image_controller.py` | 改为协作式取消（cancel flag + 安全退出） |
| P0 | 多 worker 共享同一 manager/driver，缺少并发隔离 | 竞态条件，可能导致帧错乱或场景被覆盖 | `ui/main_window.py`、`utils/workers.py` | 引入任务串行队列或每任务独立 processing context |
| P0 | GeoTIFF 导出可能存在 `HWC/CHW` 维度约定不一致 | 导出影像通道错位或空间维度异常 | `core/manager.py::_export_geotiff` | 统一图像内存格式并在导出前显式转换 |
| P1 | `requirements.txt` 与真实依赖不一致 | 新环境启动失败概率高 | 代码中使用 `dask/scipy/vispy/h5py` | 补齐并锁定关键版本 |
| P1 | 主窗口仍有大量控制逻辑，控制器未完全接管 | 维护成本高，回归风险高 | `ui/main_window.py` | 完成 UI 逻辑收口到 controllers |
| P1 | 调试 `print` 大量存在于主链路 | 性能抖动、日志污染 | `ui/canvas.py`、`ui/main_window.py` 等 | 统一切换为 logging + debug 开关 |
| P1 | Dask 流水线中存在中途 `compute()` | 懒执行收益下降，内存压力上升 | `core/pipeline.py::NormalizeNode` | 改为图内 percentile 计算或分块统计 |
| P1 | 配置字典存在重复 key 与命名不一致风险 | 产品信息错配、业务歧义 | `core/config.py`（`CTT` 重复等） | 建立配置校验脚本（启动时 fail-fast） |
| P1 | 增强模块中存在 API 拼写错误 | 功能分支运行时报错 | `core/pipelines/enhancement.py` (`fastNlMeansDening`) | 修复拼写并补单元测试 |
| P2 | 旧版 `satpy_driver` 与新架构并存 | 认知负担和维护分叉 | `core/satpy_driver.py`（deprecated） | 明确退役计划与迁移边界 |

---

## 6. 当前版本能力边界（需对外明确）

- 已支持多卫星类型，但 reader 兼容性仍依赖 SatPy 环境完整度。  
- 3D 展示依赖 VisPy 和 OpenGL 环境，部分机器可能不可用（代码已做 `available` 保护）。  
- 导出与时序在大数据量场景下仍偏重 CPU/内存，缺少系统化性能基准。  
- 自动识别主要基于文件名规则，边界命名场景需人工兜底。

---

## 7. 迭代建议（面向下一个版本）

### M1：稳定性收口（建议 1-2 周）

- 替换所有 `terminate()` 为协作式取消。  
- manager 并发隔离（任务串行或实例隔离）。  
- 修复导出维度与增强模块拼写问题。  
- 补齐 `requirements.txt`，确保一键可运行。

### M2：架构收口（建议 1-2 周）

- MainWindow 仅保留 View 职责，业务逻辑统一下沉 controller。  
- 清理 deprecated 路径，减少双轨逻辑。  
- 建立配置校验与启动自检。

### M3：质量与性能（建议 2 周）

- 引入最小测试集（驱动识别、投影、导出、时序）。  
- 建立关键路径 profiling（加载、重采样、导出）。  
- 增加用户侧错误提示分级（可恢复/不可恢复）。

---

## 8. 依赖与环境建议

### 8.1 当前 `requirements.txt`

- PyQt6  
- satpy  
- cartopy  
- matplotlib  
- numpy  
- xarray  
- pyresample  
- pyproj  
- pillow  
- gdal  
- opencv-python

### 8.2 建议补充

- dask（处理流水线已使用）  
- scipy（重采样/插值已使用）  
- vispy（3D 画布必需）  
- h5py（部分极轨数据处理使用）

---

## 9. 评审结语

项目方向和架构升级路径是正确的，核心业务链路已跑通，具备继续产品化的基础。  
当前最关键的是“先稳住，再提速”：优先解决并发与导出稳定性问题，并完成控制层收口。  
完成上述动作后，项目可进入更可靠的可交付状态。


---

## 10. 本轮针对性改动与进度（2026-03-03）

> 目标：按“时序预览优先 + 视频导出联动提速”策略，优先消除重复加载、无效重算与不必要并发开销。  
> 范围：`core/manager.py`、`ui/controllers/*`、`utils/workers.py`、`ui/main_window.py`。

### 10.1 模块改动清单（按功能链路）

| 模块 | 本轮目标 | 关键改动 | 完成度 |
|---|---|---|---|
| `core/manager.py` | driver 会话复用，减少重复识别 | `load_files` 新增 `reuse_session`、`pinned_driver_type`；新增 `reload_current()`；新增 `current_driver_type` | 100% |
| `ui/controllers/timeseries_controller.py` | 切帧不重复走工厂识别 | 新增 `_pinned_driver_type`；`load_frame` 优先 `reload_current()`，失败回退 `load_files(..., pinned_driver_type=...)` | 100% |
| `utils/workers.py`（`VideoExportWorker`） | 视频逐帧导出去重复 | 首帧初始化会话，后续逐帧 `reload_current()`；`gc.collect()` 调整为每 20 帧；增加 `load/process/encode` 分段耗时与 P50/P90 汇总日志 | 100% |
| `ui/controllers/image_controller.py` | 预览缓存升级 + 按需 3D | 增加 LRU 缓存（预览 6 / 3D 2）；`generate_image(..., need_3d_texture=False)`；仅在需要时生成 3D 纹理 | 100% |
| `ui/main_window.py` | 收口 3D 双路径 + 帧切换去重 | 移除 `_3d_cached_*` 决策依赖，统一到 `AppState.img_3d/extent_3d`；增加 `dataset_signature` 与渲染签名去重；3D 页签懒触发纹理 | 100% |
| `ui/controllers/export_controller.py` | 固化平衡导出策略 | 视频导出默认 `resample_method='bilinear'`、`quality_profile='default'`，透传 `driver_type` 与 `output_size`（worker 内 1920x1080 上限） | 100% |

### 10.2 本轮修复的运行时问题

1. 修复 `ui/main_window.py` 语法错误（`on_opacity_change` 文档字符串破损导致 `SyntaxError`）。  
2. 消除旧 3D 缓存路径与新 controller 路径并行造成的重复计算风险。  
3. 修复视频导出中逐帧 `load_files()` + 高频 `gc.collect()` 引起的明显额外开销。

### 10.3 验证结果（本地）

1. 语法校验通过：  
`python -m py_compile core/manager.py ui/controllers/image_controller.py ui/controllers/timeseries_controller.py ui/controllers/export_controller.py utils/workers.py ui/main_window.py`
2. 全量编译校验通过：  
`python -m compileall -q core ui utils main.py`
3. 导入校验通过：  
`python -c "import ui.main_window"`  
`python -c "import main"`

### 10.4 完成进度（针对本轮计划）

| 任务项 | 状态 |
|---|---|
| driver 会话复用与 `reload_current` 主干 | 已完成 |
| 时序切帧复用链路（固定 driver 类型） | 已完成 |
| 视频导出去重复与分段耗时观测 | 已完成 |
| 2D/3D 缓存与按需 3D 任务 | 已完成 |
| MainWindow 带签名的去重重算控制 | 已完成 |
| `satImgLib` 环境下编译/导入级 smoke 验证 | 已完成 |
| 基于真实 FY3D/FY4B 样本的端到端性能验收 | 待执行 |
| 单元测试补齐（LRU 命中、过期丢弃、reload 无工厂识别） | 待执行 |

### 10.5 风险与后续建议（短期）

1. `BatchExportWorker` 仍沿用逐帧 `load_files` 旧路径，建议下一轮复用 `reload_current` 策略。  
2. 建议补充自动化性能基准脚本输出（切帧 P50/P90、导出总时长对比基线），用于客观验收“提速比例”。  
3. 建议在真实 FY3D/FY4B 样本上执行一次完整回归（加载、切帧、投影切换、2D/3D、PNG/GeoTIFF/MP4）。

---

## 11. 卫星数据链路修复与 UI 视觉重设计（2026-03-03）

> 本轮目标：修复 FY-3D MERSI-2 热红外波段全链路 Bug、对齐 FY-4A/B 配置与 Satpy 实际输出、同步完成 GUI 与地图渲染的视觉升级。

### 11.1 卫星数据链路 Bug 修复（P0/P1）

| 文件 | 修复内容 | 级别 |
|---|---|---|
| `core/config.py` | `THERMAL_BAND_SETS['MERSI_L1']`：从错误的 `{B08~B13}` 改为正确的 `{B20~B25}`（B08~B13 是可见光/洋色波段） | P0 |
| `core/config.py` | `SATELLITE_BAND_MAPS['MERSI_L1']` 全部 `name` 字段：从 HDF5 路径改为 Satpy `mersi2_l1b` 实际返回的整数字符串 `'1'~'25'`，并补全 B20~B25 热红外条目 | P0 |
| `core/drivers/fengyun3d.py` | `_canonical_from_dataset()`：新增对纯整数字符串 `'1'~'25'` 的快速路径识别；修正 Emissive 偏移 +7→**+19**（正确映射 Emissive01→B20）；修正回退范围 1~19→1~25 | P0 |
| `core/drivers/fengyun3d.py` | `_resolve_dataset_name()` Strategy 3：各波段分支均以 Satpy 整数字符串模式优先；新增 `elif num <= 25` 分支处理热红外 Emissive 模式字符串 | P0 |
| `core/drivers/fengyun3d.py` | `scene.load()` 调用拆分：热红外波段使用 `calibration='brightness_temperature'`，反射波段使用 `calibration='reflectance'`，由 Satpy 内建校准完成 BT 转换 | P0 |
| `core/drivers/fengyun3d.py` | `_convert_to_brightness_temp()`：改为值域检测——若输入已在 `[170, 340]K` 范围内（Satpy 已校准），直接透传；否则执行线性缩放兜底 | P1 |
| `core/config.py` | `SATELLITE_BAND_MAPS['AGRI_L1']`：`name` 字段从 `'Channel01'~'Channel14'` 改为 Satpy `agri_fy4a/fy4b` 实际输出 `'C01'~'C14'` | P1 |
| `core/config.py` | `L2_PRODUCT_CONFIG`：重复键 `'CTT'`（云顶温度）中的第二条改为 `'CTP'`（Cloud Top Pressure），消除 Python 字典静默覆盖问题 | P1 |
| `ui/canvas.py` | `update_image()` 入口新增 `SwathDefinition` 防护：若接收到未重采样的 Swath 数据，显示错误文本并返回，避免图像错位拉伸至全球范围 | P1 |

### 11.2 MERSI-2 波段规格（已落地到代码）

| 范围 | 数量 | 分辨率 | 类型 | Satpy 数据集名 |
|---|---|---|---|---|
| B01~B04 | 4 | 250m | 可见光反射 | `'1'`~`'4'` |
| B05~B07 | 3 | 1000m | SWIR 反射 | `'5'`~`'7'` |
| B08~B19 | 12 | 1000m | 可见光/NIR/洋色 | `'8'`~`'19'` |
| B20~B25 | 6 | 1000m | **热红外发射（BT）** | `'20'`~`'25'` |

### 11.3 GUI 视觉重设计

#### 主题（`ui/style.py`）

完全重写 `_THEME_TEMPLATE` + `THEME_TOKENS_DARK`，从 22 个语义化 token 渲染 QSS：

- **色彩升级**：主背景从 `#1A1A2E` 系列深化为 `#080E1C`（bg_app）/ `#0E1828`（bg_panel）的海军黑蓝家族。
- **按钮层级**：Primary（青色渐变 teal）/ Secondary（透明+描边）/ Ghost（轻边框）/ Danger（暗红）/ `clear_band`（22×22 圆形 × 按钮）。
- **频道着色**：`BandDropZone[channel="R/G/B"][dropState="active"]` 分别呈现 Rose / Emerald / Blue 边框色。
- **Tab 样式**：下划线风格（2px bottom border），去除重型 box tab。
- **Slider 填充**：`QSlider::sub-page:horizontal` 显示已选值的青色填充段。
- **自定义滚动条**：8px 窄条，hover 时点亮 accent_primary。
- **QToolTip**：深色样式与主题对齐。

#### 组件（`ui/widgets.py`）

`BandDropZone.__init__` 新增 `channel: str = ""` 可选参数，传入后设置 `dropState` 属性，供 QSS channel 选择器驱动颜色。

#### 主窗口（`ui/main_window.py`）

- 工具栏按钮带 Unicode 图标：`⊞ Load Folder` / `↺ Reset` / `▶ Generate` / `↗ Export` / `▤ Video` / `⊗ Cancel`。
- R/G/B 通道行改为 `QHBoxLayout`：彩色 channel 标签（14px 固定宽）+ `BandDropZone` + `×` 清除按钮，视觉上即可区分三通道。
- `GroupBox` 标题精简（`"Time Series Player"` → `"Time Series"` 等）。
- 导航按钮添加方向符：`◀  Prev` / `Next  ▶`。

### 11.4 地图渲染风格升级

#### 2D 画布（`ui/canvas.py`）

- `Figure` / `axes` 背景色：`#2b2b2b` 全部替换为深海军色（`#080E1C` / `#0E1828`），消除中灰色与深色 UI 面板的色调断裂。
- `init_map()` 重写为分层 Cartopy 特征：
  - OCEAN fill `#050D1A` / LAND fill `#0D1F2D`（深空地图美学）
  - COASTLINE `#3B7EC8` 0.7px / BORDERS `#1C3A5C` 0.4px 虚线
  - 网格线 `#1E3050` 带彩色轴标签（`#8BA5C5`，7pt）
- `update_image()` overlay 层：`COASTLINE #5BAEDE 0.75px` / `BORDERS #2A5A8A 0.35px 虚线` / 轻量网格 alpha=0.18。

#### 3D 地球（`ui/globe_canvas.py`）

`_generate_base_map()` 重写为深空配色方案：
- 海洋底色 `#050B14`，陆地 `#0E1F16`（深橄榄）
- 河流 `#0B2540` alpha=0.7 / 国界 `#1A3A5A` / 海岸线 `#2A6CA0` 0.7px
- 经纬网格 `#0D1E30` alpha=0.8

### 11.5 本轮待执行验证

| 验证项 | 状态 |
|---|---|
| FY-3D B24（10.8μm）热红外波段端到端出图验证 | **待执行** |
| FY-3D B03（可见光）回归验证 | **待执行** |
| FY-4A C13（IR105）全圆盘显示回归 | **待执行** |
| GUI 视觉冒烟（启动后界面色调、R/G/B 行、× 按钮） | **待执行** |
| 地图底图与 UI 背景色一致性目视验证 | **待执行** |

## 2026-03-04 Engineering Update (Runtime Fixes + Style Consolidation)

### Implemented fixes
- Added FY3D-China projection risk warning flow in `ui/main_window.py`.
- Added FY3D coverage metadata (`swath_extent`, `swath_overlaps_china`) in `core/drivers/fengyun3d.py`.
- Fixed 3D globe seam artifacts in `ui/globe_canvas.py` with seam-safe UV sphere topology.
- Disabled default graticule rendering in 3D base map to avoid visual confusion with seam-like lines.

### Style and naming consolidation
- Corrected PyQt signal usage to `currentIndexChanged`.
- Unified new handler signatures and removed unused parameters.
- Added/normalized type hints in newly added methods.
- Split compact semicolon statements into explicit one-line assignments.

### Validation
- `python -m compileall -q core ui utils main.py`
- `python -m compileall -q ui/globe_canvas.py ui/main_window.py core/drivers/fengyun3d.py`

## 2026-03-04 Engineering Update (Dynamic Plate-Carree Extent)

### Objective
- Ensure plate-carree projection extent uses actual satellite coverage pixels instead of fixed geostationary preset boxes.

### Implemented changes
- In `core/geometry/projections.py`:
  - Added sampled lon/lat extent extraction from `source_area.get_lonlats()`.
  - Replaced fixed geostationary range branches in:
    - `ProjectionFactory._get_satellite_actual_extent()`
    - `get_geographic_extent()`
  - Added helper methods for longitude wrap normalization and circular span detection.

### Dateline behavior
- Dateline crossing is explicitly detected from longitude distribution.
- Because the current pipeline uses a single non-wrapping target bbox for longlat areas, crossing scenes currently fallback to a conservative non-wrapping envelope to preserve valid coverage.

### Quality checks
- `conda run -n satImgLib ruff check core/geometry/projections.py` passed.
- `python -m py_compile core/geometry/projections.py` passed.
- `python -m compileall -q core ui utils main.py` passed.
