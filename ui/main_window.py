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
from utils.workers import ImageLoaderWorker, VideoExportWorker # 导入新的 Worker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Himawari/FY Satellite Analyst (Pro Edition)")
        self.resize(1400, 900)
        
        self.driver = SatpyDriver() 
        self.current_gamma = 1.0
        
        self.cached_img = None
        self.cached_extent = None
        # [新增] 播放器状态
        self.file_groups = []       # 所有时间切片 [[t0_files], [t1_files], ...]
        self.current_frame_index = -1

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

        # [新增] --- 播放控制区 (添加到左侧面板底部) ---
        gb_player = QGroupBox("Time Series Player")
        vbox_player = QVBoxLayout()
        
        # 时间显示
        self.lbl_time = QLabel("Time: N/A")
        self.lbl_time.setStyleSheet("font-size: 14px; font-weight: bold; color: #00e5ff;")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox_player.addWidget(self.lbl_time)
        
        # 进度条
        self.slider_time = QSlider(Qt.Orientation.Horizontal)
        self.slider_time.setEnabled(False)
        self.slider_time.valueChanged.connect(self.on_slider_move)
        vbox_player.addWidget(self.slider_time)
        
        # 按钮组
        hbox_btns = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.btn_prev.clicked.connect(self.prev_frame)
        self.btn_next.clicked.connect(self.next_frame)
        
        self.btn_video = QPushButton("Export Video")
        self.btn_video.setStyleSheet("background-color: #d81b60;") # 醒目的颜色
        self.btn_video.clicked.connect(self.export_video_sequence)
        
        hbox_btns.addWidget(self.btn_prev)
        hbox_btns.addWidget(self.btn_video)
        hbox_btns.addWidget(self.btn_next)
        vbox_player.addLayout(hbox_btns)
        
        gb_player.setLayout(vbox_player)
        control_layout.addWidget(gb_player) # 添加到左侧面板

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
        
        self.statusBar().showMessage("Scanning folder...")
        
        # 1. 扫描并分组
        groups = self.driver.scan_and_group_files(folder)
        
        if not groups:
            QMessageBox.warning(self, "Error", "No supported satellite files found.")
            return
            
        self.file_groups = groups
        self.current_frame_index = 0
        
        # 2. 更新 UI 状态
        self.slider_time.setRange(0, len(groups) - 1)
        self.slider_time.setValue(0)
        self.slider_time.setEnabled(True)
        self.statusBar().showMessage(f"Found {len(groups)} time frames.")
        
        # 3. 加载第一帧 (仅加载 Scene 元数据，不渲染图像)
        self.load_frame(0)

    # [新增] 加载特定帧
    def load_frame(self, index):
        if not self.file_groups or index < 0 or index >= len(self.file_groups):
            return
            
        files = self.file_groups[index]
        self.current_frame_index = index
        
        # 暂时阻塞信号防止滑块循环调用
        self.slider_time.blockSignals(True)
        self.slider_time.setValue(index)
        self.slider_time.blockSignals(False)
        
        # 调用 Driver 加载 Scene 元数据
        if self.driver.load_scene(files):
            # 更新波段列表 (仅第一次或波段变化时)
            if self.band_list.count() == 0:
                bands = self.driver.get_available_datasets()
                self.band_list.clear()
                self.band_list.addItems(sorted(bands))
            
            # 更新时间标签
            meta = self.driver.get_metadata()
            time_str = meta.get('start_time', 'Unknown')
            self.lbl_time.setText(f"{time_str}\n[{index+1}/{len(self.file_groups)}]")
            
            # 自动刷新视图 (如果已经选了波段)
            # 检查是否有选中的波段，如果有，自动触发 run_process
            r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
            if r and g and b:
                self.run_process() # 重新生成当前视角的图像
            
        else:
            self.statusBar().showMessage(f"Failed to load frame {index}")

    # [新增] 导航槽函数
    def prev_frame(self):
        if self.current_frame_index > 0:
            self.load_frame(self.current_frame_index - 1)

    def next_frame(self):
        if self.current_frame_index < len(self.file_groups) - 1:
            self.load_frame(self.current_frame_index + 1)

    def on_slider_move(self, value):
        # 只有当松开鼠标或者点击时才加载，防止滑动过快卡死
        # 这里简单处理，直接加载
        if value != self.current_frame_index:
            self.load_frame(value)

    # [新增] 视频导出逻辑
    def export_video_sequence(self):
        if not self.file_groups: return
        
        # 获取当前波段设置
        r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
        bands = []
        if r and g and b: bands = [r, g, b]
        else: 
            QMessageBox.info(self, "Info", "Please setup RGB bands first.")
            return

        # 选择保存路径
        output_file, _ = QFileDialog.getSaveFileName(self, "Save Video", "", "MP4 Video (*.mp4)")
        if not output_file: return
        
        # 准备参数
        proj_id = self.combo_proj.currentData()
        params = {
            'gamma': self.current_gamma,
            'proj_name': proj_id
        }
        
        # 启动视频工作线程
        self.vid_worker = VideoExportWorker(self.driver, self.file_groups, output_file, bands, params)
        self.vid_worker.progress.connect(self.on_video_progress)
        self.vid_worker.finished.connect(self.on_video_finished)
        self.vid_worker.error.connect(self.on_video_error)
        
        # 禁用界面防止冲突
        self.setEnabled(False)
        self.statusBar().showMessage("Exporting video... This may take a while.")
        self.vid_worker.start()
    
    def on_video_progress(self, current, total):
        self.statusBar().showMessage(f"Exporting Video: Frame {current}/{total}...")

    def on_video_finished(self, path):
        self.setEnabled(True)
        self.statusBar().showMessage("Video Export Complete!")
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def on_video_error(self, message: str):
        self.setEnabled(True)
        self.statusBar().showMessage("Video export failed")
        QMessageBox.critical(self, "Video Export Error", f"Failed to export video:\n{message}")

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
            
            time_s = result.get('time_s')
            time_msg = f"{time_s:.2f}s" if isinstance(time_s, (int, float)) else "N/A"
            msg = f"Export successful: {output_path}\nProjection: {proj_name}\nTime: {time_msg}"
            self.statusBar().showMessage("Export complete!")
            QMessageBox.information(self, "Export Success", msg)
        
        except Exception as e:
            msg = f"Export failed:\n{str(e)}"
            self.statusBar().showMessage("Export failed!")
            QMessageBox.critical(self, "Export Error", msg)
