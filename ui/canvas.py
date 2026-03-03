from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import warnings
import logging
from core.geo_utils import create_extent_array_for_imshow
from core.config import PROJECTION_GRID_SHAPES, PROJECTION_GRID_EXTENTS

logger = logging.getLogger(__name__)

# 忽略 Cartopy 的一些转换警告
warnings.filterwarnings("ignore", category=UserWarning)

class StableFigureCanvas(FigureCanvasQTAgg):
    """Reduce accidental wheel-zoom jitter on hover."""

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        event.accept()

class GeoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0) # 去掉边缘留白

        # === 样式适配关键点 ===
        # facecolor 必须与 QSS bg_app 一致 (#080E1C)
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor='#080E1C')

        self.canvas = StableFigureCanvas(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        # 隐藏 Matplotlib 工具栏的默认边框，使其融入
        self.toolbar.setStyleSheet("background-color: #0E1828; border: none; color: #8BA5C5;")
        # Enlarge coordinate label on the top-right to avoid clipping.
        if hasattr(self.toolbar, "locLabel") and self.toolbar.locLabel is not None:
            # Keep a fixed coordinate area so hover text will not reflow toolbar layout.
            self.toolbar.locLabel.setFixedWidth(460)
            self.toolbar.locLabel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            self.toolbar.locLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.layout.addWidget(self.toolbar)
        self.layout.addWidget(self.canvas)

        self.ax = None
        self.init_map()

    def init_map(self):
        self.fig.clear()
        self.geo_proj = ccrs.PlateCarree()
        self.ax = self.fig.add_subplot(111, projection=self.geo_proj)
        self.ax.format_coord = self._fast_format_coord
        self.ax.spines['geo'].set_visible(False)

        # Base axes background (areas outside land/ocean polygons)
        self.ax.set_facecolor('#050D1A')

        # ── Deep-space cartographic style ──────────────────────────────
        # Ocean: near-black deep blue
        self.ax.add_feature(cfeature.OCEAN.with_scale('110m'),
                            facecolor='#050D1A', edgecolor='none', zorder=0)
        # Land: dark slate, distinguishable from ocean
        self.ax.add_feature(cfeature.LAND.with_scale('110m'),
                            facecolor='#0D1F2D', edgecolor='none', zorder=1)
        # Coastlines: steel-blue — readable without harsh cyan glare
        self.ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                            edgecolor='#3B7EC8', linewidth=0.7, zorder=3)
        # Country borders: very subtle dark blue dashes
        self.ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                            edgecolor='#1C3A5C', linewidth=0.4,
                            linestyle='--', alpha=0.8, zorder=4)

        # Gridlines: near-invisible guide lines with styled labels
        gl = self.ax.gridlines(draw_labels=True, linestyle='-',
                               alpha=0.3, color='#1E3050', linewidth=0.5,
                               x_inline=False, y_inline=False)
        gl.xlabel_style = {'color': '#8BA5C5', 'fontsize': 7}
        gl.ylabel_style = {'color': '#8BA5C5', 'fontsize': 7}
        # ───────────────────────────────────────────────────────────────

        self.canvas.draw()

    def plot_pixel_mode(self, img_data):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)

        # 隐藏坐标轴刻度
        self.ax.axis('off')

        # 设置图像背景色 (防止缩放时露出白色)
        self.ax.set_facecolor('#0E1828')

        if img_data.ndim == 3:
            self.ax.imshow(img_data)
        else:
            self.ax.imshow(img_data, cmap='gray')

        self.ax.set_title("Preview (No Geo-Location)", color='#8BA5C5')

    def update_image(self, img_data, area_def):
        """
        核心绘图函数（带投影自适应逻辑）
        """
        logger.debug(f"[Canvas] update_image called with img_data shape: {img_data.shape}")
        logger.debug(f"[Canvas] img_data dtype: {img_data.dtype}")

        # Guard: SwathDefinition cannot be used for imshow — the caller must resample first.
        try:
            from pyresample.geometry import SwathDefinition
            if isinstance(area_def, SwathDefinition):
                logger.warning("[Canvas] Got SwathDefinition — cannot display; please resample first")
                self.fig.clear()
                self.ax = self.fig.add_subplot(111)
                self.ax.text(0.5, 0.5, "Error: unsampled swath data\n(resample to a grid first)",
                             ha='center', va='center', color='red',
                             transform=self.ax.transAxes)
                self.ax.axis('off')
                self.canvas.draw()
                return
        except ImportError:
            pass

        # 没有可用地理信息时，直接降级到像素显示，避免错误地理对齐。
        if area_def is None:
            logger.debug("[Canvas] area_def is None, fallback to pixel mode")
            self.plot_pixel_mode(img_data)
            try:
                self.canvas.draw()
            except Exception as e:
                logger.exception(f"[Canvas] Draw failed in pixel mode fallback: {e}")
            return

        # 检查图像数据是否有效
        try:
            # 更详细地检查数据
            img_min = np.nanmin(img_data)
            img_max = np.nanmax(img_data)

            # 检查 NaN 和黑色像素
            nan_pixels = np.sum(np.isnan(img_data))
            black_pixels = np.sum((img_data < 0.01).all(axis=-1)) if img_data.ndim == 3 else np.sum(img_data < 0.01)
            valid_data_pixels = np.sum((np.abs(img_data) > 0.01).any(axis=-1)) if img_data.ndim == 3 else np.sum(np.abs(img_data) > 0.01)
            total_pixels = img_data.shape[0] * img_data.shape[1]

            logger.debug(f"[Canvas] img_data stats: min={img_min:.6f}, max={img_max:.6f}")
            logger.debug(f"[Canvas] NaN pixels: {nan_pixels}, Black/near-black pixels: {black_pixels}")
            logger.debug(f"[Canvas] Valid data pixels: {valid_data_pixels}/{total_pixels} ({100*valid_data_pixels/total_pixels:.1f}%)")

            # 处理无效区域（NaN 或 全黑）- 设置为 NaN 以便 imshow 正确显示透明
            if nan_pixels < total_pixels or black_pixels > 0:
                # 创建 mask 来识别无效区域
                if img_data.ndim == 3:
                    # RGB 图像：检查所有通道
                    valid_mask = (img_data > 0.01).any(axis=-1)
                else:
                    # 灰度图像
                    valid_mask = img_data > 0.01

                # 如果有大量无效像素，设置为 NaN
                invalid_ratio = 1 - (valid_data_pixels / total_pixels)
                if invalid_ratio > 0.1:  # 超过10%是无效的
                    logger.debug(f"[Canvas] Setting {invalid_ratio*100:.1f}% invalid pixels to NaN for transparency")
                    img_data = img_data.copy()
                    img_data[~valid_mask] = np.nan

        except Exception as e:
            logger.exception(f"[Canvas] Error checking image data: {e}")

        self.ax.clear()
        self.fig.clear()

        if img_data.ndim < 2:
            self.ax = self.fig.add_subplot(111)
            self.ax.text(0.5, 0.5, "Data is 1D/Invalid", ha='center')
            self.canvas.draw()
            return

        h, w = img_data.shape[:2]

        # === 1. 确定投影类型 ===
        target_crs = None
        target_extent = None
        use_native_projection = False

        try:
            # 获取 area_def 信息
            proj_dict = getattr(area_def, 'proj_dict', {})
            is_geos = proj_dict.get('proj') == 'geos'
            lon_0 = float(proj_dict.get('lon_0', 105))

            # 根据图像尺寸判断投影类型 (使用配置表，无魔法数字)
            grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
            is_global_grid = grid_proj == 'plate_carree_global'
            is_china_region = grid_proj == 'plate_carree_china'

            logger.debug(f"[Canvas] is_geos: {is_geos}, grid_proj: {grid_proj}")

            if is_global_grid:
                # === 情况 1: 全球网格 ===
                logger.debug("[Canvas] Mode: Global Grid (-180 to 180)")
                target_crs = ccrs.PlateCarree()
                target_extent = PROJECTION_GRID_EXTENTS['plate_carree_global']
                logger.debug(f"[Canvas] Using global extent: {target_extent}")

            elif is_geos and is_china_region:
                # === 情况 2: 中国区域 (Plate Carree China) ===
                logger.debug("[Canvas] Mode: China Region")
                target_crs = ccrs.PlateCarree()
                target_extent = PROJECTION_GRID_EXTENTS['plate_carree_china']
                logger.debug(f"[Canvas] Using china extent: {target_extent}")

            elif is_geos and not is_global_grid:
                # === 情况 3: Geostationary 原生视图 ===
                logger.debug("[Canvas] Mode: Geostationary Native (Meters)")
                target_crs = ccrs.Geostationary(central_longitude=lon_0)
                use_native_projection = True

                # Geostationary 使用米单位的 extent
                ae = getattr(area_def, 'area_extent', None)
                if ae:
                    # area_extent 是 (xmin, ymin, xmax, ymax) 以米为单位
                    target_extent = (ae[0], ae[2], ae[1], ae[3])
                    logger.debug(f"[Canvas] Using native extent (meters): {target_extent}")

            elif proj_dict.get('proj') in ('longlat', 'latlong', 'eqc'):
                # === 情况 3b: 极轨数据重采样后的动态 PlateCarree 格网 ===
                # FY3D MERSI 等极轨卫星重采样后的 AreaDefinition 使用 proj='longlat'，
                # 动态尺寸不匹配 PROJECTION_GRID_SHAPES，需要专门路径处理。
                logger.debug("[Canvas] Mode: Polar Orbit PlateCarree (dynamic extent)")
                target_crs = ccrs.PlateCarree()

                ae = getattr(area_def, 'area_extent', None)
                if ae and len(ae) == 4:
                    # area_extent for longlat AreaDefinition: (west, south, east, north)
                    # imshow extent: (left=west, right=east, bottom=south, top=north)
                    target_extent = (float(ae[0]), float(ae[2]), float(ae[1]), float(ae[3]))
                    logger.debug(f"[Canvas] Polar orbit extent (W,E,S,N): {target_extent}")

            else:
                # === 情况 4: 其他投影 ===
                logger.debug("[Canvas] Mode: Generic Projection")
                target_crs = ccrs.PlateCarree()

                # 尝试获取 extent
                ae = getattr(area_def, 'area_extent', None)
                if ae:
                    target_extent = (ae[0], ae[2], ae[1], ae[3])

        except Exception as e:
            logger.exception(f"[Canvas] Projection setup failed: {e}")
            target_crs = None

        # === 2. 执行绘图 ===
        if target_crs:
            try:
                logger.debug(f"[Canvas] Using CRS: {type(target_crs).__name__}")
                if target_extent:
                    logger.debug(f"[Canvas] Using extent: {target_extent}")

                # 创建带投影的坐标轴
                self.ax = self.fig.add_subplot(111, projection=target_crs)
                self.ax.format_coord = self._fast_format_coord

                # 准备 imshow 参数
                kwargs = {
                    'origin': 'upper',
                }

                # 对于 geostationary，需要使用 Geostationary transform
                if use_native_projection:
                    kwargs['transform'] = ccrs.Geostationary(central_longitude=lon_0)
                else:
                    kwargs['transform'] = ccrs.PlateCarree()

                # 添加 extent
                if target_extent:
                    kwargs['extent'] = target_extent

                # 绘制图像
                if img_data.ndim == 3:
                    self.ax.imshow(img_data, **kwargs)
                else:
                    self.ax.imshow(img_data, cmap='gray', **kwargs)

                # ── Vector overlays above satellite imagery ──────────────
                # Coastlines: bright steel-blue, clearly visible on any data
                self.ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                                    edgecolor='#5BAEDE', linewidth=0.75,
                                    alpha=0.85, zorder=10)
                # Country borders: subtle dashes so political boundaries
                # can be referenced without cluttering the imagery
                self.ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                                    edgecolor='#2A5A8A', linewidth=0.35,
                                    linestyle='--', alpha=0.65, zorder=10)

                if use_native_projection:
                    self.ax.set_global()

                # Gridlines: barely-visible structure lines
                self.ax.gridlines(linestyle='-', alpha=0.18,
                                  color='#1E3050', linewidth=0.4)
                # ─────────────────────────────────────────────────────────

            except Exception as e:
                logger.exception(f"[Canvas] Cartopy drawing error: {e}")
                self.plot_pixel_mode(img_data)
        else:
            self.plot_pixel_mode(img_data)

        # === 3. 刷新画布 ===
        try:
            self.canvas.draw()
        except Exception as e:
            logger.exception(f"[Canvas] Draw failed: {e}")

    def plot_pixel_mode(self, img_data):
        """降级显示：不带地图投影，只显示像素矩阵"""
        logger.debug(f"[Canvas] plot_pixel_mode called with img shape={getattr(img_data, 'shape', 'unknown')}")
        self.fig.clear()
        self.ax = self.fig.add_subplot(111) # 普通 Axes，非 GeoAxes

        if img_data.ndim == 3:
            logger.debug("[Canvas] Displaying RGB image in pixel mode")
            self.ax.imshow(img_data)
        else:
            logger.debug("[Canvas] Displaying single-band image in pixel mode")
            self.ax.imshow(img_data, cmap='gray')

        self.ax.set_title("Preview (No Geo-Location)")
        self.ax.axis('off')
        logger.debug("[Canvas] plot_pixel_mode setup complete")

    def clear_view(self):
        """Reset canvas to an empty placeholder state."""
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#080E1C')
        self.ax.text(
            0.5, 0.5, "No image loaded\nLoad a folder and press  ▶ Generate",
            ha='center', va='center', color='#8BA5C5',
            fontsize=11, linespacing=1.8,
            transform=self.ax.transAxes
        )
        self.ax.axis('off')
        self.canvas.draw()

    def _fast_format_coord(self, x: float, y: float) -> str:
        """Use a lightweight formatter for smoother mouse-hover feedback."""
        try:
            lon, lat = ccrs.PlateCarree().transform_point(x, y, self.ax.projection)
            return f"Lon {lon:.4f}°, Lat {lat:.4f}°"
        except Exception:
            return f"x={x:.0f}, y={y:.0f}"
