from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import cartopy.crs as ccrs
import numpy as np
import warnings
from core.geo_utils import create_extent_array_for_imshow

# 忽略 Cartopy 的一些转换警告
warnings.filterwarnings("ignore", category=UserWarning)

class GeoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0) # 去掉边缘留白
        
        # === 样式适配关键点 ===
        # facecolor='#2b2b2b' 必须与 QSS 中的 QWidget 背景色一致
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor='#2b2b2b') 
        
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        
        # 隐藏 Matplotlib 工具栏的默认边框，使其融入
        self.toolbar.setStyleSheet("background-color: #2b2b2b; border: none;")
        
        self.layout.addWidget(self.toolbar)
        self.layout.addWidget(self.canvas)
        
        self.ax = None
        self.init_map()

    def init_map(self):
        self.fig.clear()
        self.geo_proj = ccrs.PlateCarree()
        
        # 设置坐标轴背景也是深色
        self.ax = self.fig.add_subplot(111, projection=self.geo_proj)
        
        # 移除坐标轴白边
        self.ax.spines['geo'].set_visible(False) 
        
        # 海岸线改为亮色 (Cyan 或 Light Grey) 以便在深色背景显示
        self.ax.coastlines(color='#00e5ff', linewidth=0.8) 
        self.ax.gridlines(draw_labels=True, linestyle='--', alpha=0.3, color='#cccccc')
        
        self.canvas.draw()
    
    def plot_pixel_mode(self, img_data):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        
        # 隐藏坐标轴刻度
        self.ax.axis('off')
        
        # 设置图像背景色 (防止缩放时露出白色)
        self.ax.set_facecolor('#2b2b2b')
        
        if img_data.ndim == 3:
            self.ax.imshow(img_data)
        else:
            self.ax.imshow(img_data, cmap='gray')
            
        self.ax.set_title("Preview (No Geo-Location)", color='white') # 标题改为白色

    def update_image(self, img_data, area_def):
        """
        核心绘图函数（带投影自适应逻辑）
        """
        # print(f"[Canvas] update_image called...") # 调试输出可适当减少
        self.ax.clear()
        self.fig.clear()

        if img_data.ndim < 2:
            self.ax = self.fig.add_subplot(111)
            self.ax.text(0.5, 0.5, "Data is 1D/Invalid", ha='center')
            self.canvas.draw()
            return

        # === 1. 智能解析投影 ===
        target_crs = None
        target_extent = None
        use_native_projection = False

        try:
            # A. 优先尝试从数据中获取原生投影 (如 Geostationary)
            if hasattr(area_def, 'to_cartopy_crs'):
                target_crs = area_def.to_cartopy_crs()
            
            # B. 获取范围 (Extent)
            if target_crs is not None:
                # 检查是否为原生卫星视角 (Geostationary / NearsidePerspective)
                # 这种投影的单位是 "米"，必须使用 area_def.area_extent
                if isinstance(target_crs, (ccrs.Geostationary, ccrs.NearsidePerspective)):
                    print("[Canvas] Mode: Native Geostationary (Meters)")
                    use_native_projection = True
                    
                    # Pyresample area_extent 是 (xmin, ymin, xmax, ymax)
                    # Matplotlib imshow extent 也是 (xmin, xmax, ymin, ymax)
                    # 注意顺序差异！
                    ae = area_def.area_extent
                    if ae:
                        # 转换顺序: (xmin, ymin, xmax, ymax) -> (xmin, xmax, ymin, ymax)
                        target_extent = (ae[0], ae[2], ae[1], ae[3])
                else:
                    # 其他投影 (如 PlateCarree, Mercator)，通常 Satpy 会重采样好
                    # 这里依然尝试获取 area_extent，如果单位也是米，逻辑通用
                    print(f"[Canvas] Mode: {type(target_crs).__name__}")
                    ae = getattr(area_def, 'area_extent', None)
                    if ae:
                         target_extent = (ae[0], ae[2], ae[1], ae[3])
            
            # C. 如果没能解析出 CRS，回退到经纬度模式 (PlateCarree)
            if target_crs is None:
                print("[Canvas] Mode: Fallback to PlateCarree (Degrees)")
                target_crs = ccrs.PlateCarree()
                # 尝试计算经纬度范围
                geo_ext = create_extent_array_for_imshow(area_def)
                if geo_ext:
                    target_extent = geo_ext # (W, E, S, N) 符合 imshow 顺序

        except Exception as e:
            print(f"[Canvas] Projection setup failed: {e}")
            target_crs = None

        # === 2. 执行绘图 ===
        if target_crs:
            try:
                # 创建带投影的坐标轴
                self.ax = self.fig.add_subplot(111, projection=target_crs)
                
                # 绘制图像
                # 关键：transform=target_crs 表示图像数据本身就是在这个坐标系下的
                kwargs = {
                    'origin': 'upper', 
                    'transform': target_crs
                }
                
                # 只有当 extent 有效时才添加，否则让 matplotlib 自动推断
                if target_extent:
                    kwargs['extent'] = target_extent
                    print(f"[Canvas] Plotting with extent: {target_extent}")

                if img_data.ndim == 3:
                    self.ax.imshow(img_data, **kwargs)
                else:
                    self.ax.imshow(img_data, cmap='gray', **kwargs)

                # 添加地图元素
                # 注意：海岸线需要指定分辨率，全圆盘建议用 110m，局部用 50m
                self.ax.coastlines(resolution='110m', color='#00ffff', linewidth=0.8, alpha=0.8)
                
                # 只有在原生模式下才设置 global，这样能看到完整的地球圆盘背景
                if use_native_projection:
                    self.ax.set_global()
                
                # 添加网格
                try:
                    self.ax.gridlines(linestyle='--', alpha=0.4, color='white')
                except Exception:
                    pass

            except Exception as e:
                print(f"[Canvas] Cartopy drawing error: {e}. Fallback to Pixel.")
                self.plot_pixel_mode(img_data)
        else:
            self.plot_pixel_mode(img_data)

        # === 3. 刷新画布 ===
        try:
            self.canvas.draw()
        except Exception as e:
            print(f"[Canvas] Draw failed: {e}")

    def plot_pixel_mode(self, img_data):
        """降级显示：不带地图投影，只显示像素矩阵"""
        print(f"[Canvas] plot_pixel_mode called with img shape={getattr(img_data, 'shape', 'unknown')}")
        self.fig.clear()
        self.ax = self.fig.add_subplot(111) # 普通 Axes，非 GeoAxes
        
        if img_data.ndim == 3:
            print(f"[Canvas] Displaying RGB image in pixel mode")
            self.ax.imshow(img_data)
        else:
            print(f"[Canvas] Displaying single-band image in pixel mode")
            self.ax.imshow(img_data, cmap='gray')
            
        self.ax.set_title("Preview (No Geo-Location)")
        self.ax.axis('off')
        print(f"[Canvas] plot_pixel_mode setup complete")