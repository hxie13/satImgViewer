import sys
import os
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QSplitter, 
                             QGroupBox, QSlider, QTabWidget, QMessageBox, QComboBox)
from PyQt6.QtCore import Qt, QTimer

# 确保导入所有自定义模块
from core.geo_utils import get_geographic_extent # 确保导入此函数
from core.satpy_driver import SatpyDriver
from core.projections import get_available_projections
from ui.canvas import GeoCanvas
from ui.globe_canvas import Globe3DCanvas  # 确保你有这个文件
from ui.widgets import DraggableList, BandDropZone
from utils.workers import ImageLoaderWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Himawari/FY Satellite Analyst (Pro Edition)")
        self.resize(1400, 900)
        
        self.driver = SatpyDriver() 
        self.current_gamma = 1.0
        
        self.cached_img = None
        self.cached_extent = None
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        # 主布局：左侧控制栏 + 右侧显示区
        layout = QHBoxLayout(main_widget)

        # === 1. 左侧控制面板 ===
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_panel.setFixedWidth(320)

        # A. 文件加载
        btn_load = QPushButton("Load Data Folder")
        btn_load.clicked.connect(self.load_data)
        control_layout.addWidget(btn_load)

        # B. 波段列表 (可拖拽)
        control_layout.addWidget(QLabel("Available Bands (Drag to Right):"))
        self.band_list = DraggableList()
        control_layout.addWidget(self.band_list)

        # C. RGB 合成区 (接收拖拽)
        gb_rgb = QGroupBox("RGB Compositor")
        vbox_rgb = QVBoxLayout()
        self.drop_r = BandDropZone("Red Channel (e.g. B13)")
        self.drop_g = BandDropZone("Green Channel (e.g. B12)")
        self.drop_b = BandDropZone("Blue Channel (e.g. B09)")
        
        vbox_rgb.addWidget(QLabel("R:")); vbox_rgb.addWidget(self.drop_r)
        vbox_rgb.addWidget(QLabel("G:")); vbox_rgb.addWidget(self.drop_g)
        vbox_rgb.addWidget(QLabel("B:")); vbox_rgb.addWidget(self.drop_b)
        
        btn_gen = QPushButton("Generate View")
        btn_gen.clicked.connect(self.run_process)
        vbox_rgb.addWidget(btn_gen)
        gb_rgb.setLayout(vbox_rgb)
        control_layout.addWidget(gb_rgb)

        # D. 投影选择 (Projection)
        gb_proj = QGroupBox("Projection & Export")
        vbox_proj = QVBoxLayout()
        
        vbox_proj.addWidget(QLabel("Output Projection:"))
        self.combo_proj = QComboBox()
        proj_options = get_available_projections()
        for proj_id, proj_name, proj_desc in proj_options:
            self.combo_proj.addItem(f"{proj_name} ({proj_desc})", proj_id)
        vbox_proj.addWidget(self.combo_proj)
        
        btn_export = QPushButton("Export to File")
        btn_export.clicked.connect(self.export_image)
        vbox_proj.addWidget(btn_export)
        
        gb_proj.setLayout(vbox_proj)
        control_layout.addWidget(gb_proj)

        # E. 图像增强 (Gamma)
        gb_enhance = QGroupBox("Enhancement")
        vbox_enh = QVBoxLayout()
        self.slider_gamma = QSlider(Qt.Orientation.Horizontal)
        self.slider_gamma.setRange(5, 30) # 0.5 - 3.0
        self.slider_gamma.setValue(10)
        self.slider_gamma.valueChanged.connect(self.on_gamma_change)
        self.lbl_gamma = QLabel("Gamma: 1.0")
        
        vbox_enh.addWidget(self.lbl_gamma)
        vbox_enh.addWidget(self.slider_gamma)
        gb_enhance.setLayout(vbox_enh)
        control_layout.addWidget(gb_enhance)

        # [新增] 透明度滑块
        self.lbl_opacity = QLabel("Overlay Opacity: 100%")
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100) # 0% - 100%
        self.slider_opacity.setValue(100)    # 默认不透明
        self.slider_opacity.valueChanged.connect(self.on_opacity_change)
        
        vbox_enh.addWidget(self.lbl_opacity)
        vbox_enh.addWidget(self.slider_opacity)

        # 将控制面板加入主布局
        layout.addWidget(control_panel)

        # === 2. 右侧显示区域 (Splitter + Tabs) ===
        # [修复点] 必须先创建 Splitter 对象，才能调用 addWidget
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 创建标签页容器
        self.tabs = QTabWidget()
        
        # Tab 1: 2D 地图视图
        self.canvas_2d = GeoCanvas()
        self.tabs.addTab(self.canvas_2d, "2D Map View")
        
        # Tab 2: 3D 地球视图
        self.canvas_3d = Globe3DCanvas()
        self.tabs.addTab(self.canvas_3d, "3D Globe View")
        
        # 将 Tabs 加入 Splitter
        self.splitter.addWidget(self.tabs)
        
        # 将 Splitter 加入主布局
        layout.addWidget(self.splitter)

    def load_data(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if not folder: return
        
        # 简单的文件扫描逻辑
        import os
        supported_exts = ('.nc', '.dat', '.h5', '.hdf', '.bz2')
        valid_files = []
        try:
            for f in os.listdir(folder):
                full_path = os.path.join(folder, f)
                if os.path.isfile(full_path) and f.lower().endswith(supported_exts):
                    valid_files.append(full_path)
        except OSError:
            return

        if not valid_files:
            QMessageBox.warning(self, "Error", "No valid satellite files found.")
            return

        self.statusBar().showMessage("Loading metadata... please wait.")
        QTimer.singleShot(100, lambda: self._execute_driver_load(valid_files))

    def _execute_driver_load(self, files):
        if self.driver.load_scene(files):
            bands = self.driver.get_available_datasets()
            self.band_list.clear()
            self.band_list.addItems(sorted(bands))
            
            meta = self.driver.get_metadata()
            self.statusBar().showMessage(f"Loaded: {meta.get('platform')} | {meta.get('start_time')}")
        else:
            self.statusBar().showMessage("Failed to load scene.")
            QMessageBox.critical(self, "Error", "Failed to load satellite data.\nCheck console for details.")

    def on_gamma_change(self, value):
        self.current_gamma = value / 10.0
        self.lbl_gamma.setText(f"Gamma: {self.current_gamma}")

    def run_process(self):
        # 获取波段
        r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
        bands = []
        
        if r and g and b:
            bands = [r, g, b]
        elif self.band_list.currentItem():
            bands = [self.band_list.currentItem().text()]
        else:
            QMessageBox.information(self, "Info", "Please select bands or drag to RGB boxes.")
            return

        # Get the selected projection from the combo box
        proj_id = self.combo_proj.currentData()
        
        params = {
            'gamma': self.current_gamma,
            'proj_name': proj_id  # Use the selected projection
        }
        
        # 启动后台线程
        self.worker = ImageLoaderWorker(self.driver, bands, params)
        self.worker.data_ready.connect(self.on_data_ready)
        # 连接错误信号，显示到状态栏并弹窗提示
        try:
            self.worker.error.connect(self.on_worker_error)
        except Exception:
            pass
        self.worker.start()

    def on_data_ready(self, img, area_def):
        """处理后台线程返回的图像数据"""
        print(f"[MainWindow] Image ready: shape={img.shape}")

        # [新增] 缓存当前数据，供滑块调整使用
        self.cached_img = img
        from core.geo_utils import get_geographic_extent
        self.cached_extent = get_geographic_extent(area_def)

        # 1. 更新 2D 地图
        try:
            self.canvas_2d.update_image(img, area_def)
        except Exception as e:
            print(f"2D update failed: {e}")

        # 2. 更新 3D 地球 (使用当前滑块的透明度)
        self.update_3d_view()
    
    def on_opacity_change(self, value):
        """滑块拖动回调"""
        self.lbl_opacity.setText(f"Overlay Opacity: {value}%")
        # 实时刷新 3D 视图
        self.update_3d_view()
    
    def update_3d_view(self):
        """刷新 3D 纹理的辅助函数"""
        if self.cached_img is not None and getattr(self.canvas_3d, 'available', True):
            try:
                # 获取当前透明度 (0.0 - 1.0)
                alpha = self.slider_opacity.value() / 100.0
                
                # 调用 3D 画布更新
                self.canvas_3d.update_texture(
                    self.cached_img, 
                    extent=self.cached_extent,
                    alpha=alpha  # 传递 alpha 参数
                )
            except Exception as e:
                print(f"3D update failed: {e}")

    def on_worker_error(self, message: str):
        """在后台线程发生错误时被调用，保证在主线程显示提示"""
        try:
            self.statusBar().showMessage(f"Processing error: {message}")
            QMessageBox.critical(self, "Processing Error", f"Failed to generate image:\n{message}")
        except Exception:
            print(f"Worker error (no UI): {message}")

    def export_image(self):
        """导出当前合成的图像到指定投影格式和文件"""
        # 获取当前选择的波段和投影
        r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
        bands = []
        
        if r and g and b:
            bands = [r, g, b]
        elif self.band_list.currentItem():
            bands = [self.band_list.currentItem().text()]
        else:
            QMessageBox.information(self, "Info", "Please select bands first.")
            return
        
        # 获取投影和文件路径
        proj_id = self.combo_proj.currentData()
        proj_name = self.combo_proj.currentText()
        
        output_file = QFileDialog.getSaveFileName(
            self,
            "Export Image As",
            "",
            "PNG Image (*.png);;GeoTIFF (*.tif);;All Files (*.*)"
        )
        
        if not output_file[0]:
            return
        
        output_path = output_file[0]
        
        # 确定格式
        if output_path.lower().endswith('.tif'):
            export_format = 'geotiff'
        else:
            export_format = 'png'
        
        # 后台线程导出
        self.statusBar().showMessage(f"Exporting to {proj_name}...")
        target_region = 'global'
        try:
            result = self.driver.export_image(
                bands=bands,
                output_path=output_path,
                proj_name=proj_id,
                export_format=export_format,
                gamma=self.current_gamma,
                calibration=True,  # Enable radiometric calibration
                region=target_region,  # Default to China region
                resample_method='nearest'  # Default resample method
            )
            
            msg = f"Export successful: {output_path}\nProjection: {proj_name}\nTime: {result['time_s']:.2f}s"
            self.statusBar().showMessage("Export complete!")
            QMessageBox.information(self, "Export Success", msg)
        
        except Exception as e:
            msg = f"Export failed:\n{str(e)}"
            self.statusBar().showMessage("Export failed!")
            QMessageBox.critical(self, "Export Error", msg)