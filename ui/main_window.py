import sys
import os
import logging
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QLabel, QSplitter,
                             QGroupBox, QSlider, QTabWidget, QMessageBox, QComboBox,
                             QFrame, QSpinBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence

# Core imports
from core.geo_utils import get_geographic_extent
from core.manager import SatelliteImageManager
from core.geometry import get_available_projections
from core.config import PROJECTION_GRID_SHAPES, PROJECTION_GRID_EXTENTS
from core.app_state import AppState
from ui.canvas import GeoCanvas
from ui.globe_canvas import Globe3DCanvas
from ui.widgets import DraggableList, BandDropZone
from ui.controllers import ImageViewController, TimeSeriesController, ExportController

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Himawari/FY Satellite Analyst (Pro Edition) v2.0")
        self.resize(1400, 900)

        # Initialize SatelliteImageManager
        self.manager = SatelliteImageManager()

        # Centralised application state
        self._state = AppState()

        # Controllers (MVP: presentation logic separated from layout)
        self._img_ctrl  = ImageViewController(self.manager, self._state, parent=self)
        self._ts_ctrl   = TimeSeriesController(self.manager, self._state, parent=self)
        self._exp_ctrl  = ExportController(self.manager, self._state, parent=self)

        # Wire controller signals to UI slots
        self._img_ctrl.image_ready.connect(self._on_image_ctrl_ready)
        self._img_ctrl.texture_3d_ready.connect(self._on_3d_texture_ctrl_ready)
        self._img_ctrl.error.connect(self.on_worker_error)
        self._img_ctrl.status.connect(lambda m: self._on_controller_status("image", m))

        self._ts_ctrl.frame_loaded.connect(self._on_frame_loaded)
        self._ts_ctrl.frame_loading.connect(
            lambda: self._set_ui_status("loading", "Loading frame...")
        )
        self._ts_ctrl.error.connect(self.on_worker_error)
        self._ts_ctrl.status.connect(lambda m: self._on_controller_status("timeseries", m))

        self._exp_ctrl.export_finished.connect(self._on_export_finished)
        self._exp_ctrl.export_error.connect(self.on_worker_error)
        self._exp_ctrl.video_progress.connect(self.on_video_progress)
        self._exp_ctrl.video_finished.connect(self._on_video_ctrl_finished)
        self._exp_ctrl.video_error.connect(self.on_worker_error)
        self._exp_ctrl.status.connect(lambda m: self._on_controller_status("export", m))

        # Legacy state aliases kept for methods not yet migrated to controllers
        self.current_gamma = self._state.gamma
        self.cached_img    = None   # replaced by self._state.cached_img
        self.cached_extent = None   # replaced by self._state.cached_extent
        self.file_groups   = self._state.file_groups
        self.current_frame_index = self._state.current_frame_index
        self.current_bands = []
        self._band_dataset_signature = None
        self._last_render_request_signature = None
        self._pending_slider_index = None
        self._slider_debounce_timer = QTimer(self)
        self._slider_debounce_timer.setSingleShot(True)
        self._slider_debounce_timer.timeout.connect(self._apply_debounced_slider_load)

        # Initialize UI
        self.init_ui()
    def init_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        self._build_toolbar(root_layout)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, 1)

        left_panel = self._build_left_panel()
        center_panel = self._build_main_view()
        right_panel = self._build_right_inspector()

        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(center_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 1000, 340])

        self._build_status_bar()
        self._bind_shortcuts()
        self._apply_component_styles()
        self._sync_action_states()
        self._set_ui_status("idle", "Ready")

    def _build_toolbar(self, parent_layout: QVBoxLayout) -> None:
        toolbar = QFrame()
        toolbar.setObjectName("TopToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(8)

        self.btn_load = QPushButton("⊞  Load Folder")
        self.btn_load.setProperty("role", "secondary")
        self.btn_load.clicked.connect(self.load_data)
        toolbar_layout.addWidget(self.btn_load)

        self.btn_clear = QPushButton("↺  Reset")
        self.btn_clear.setProperty("role", "secondary")
        self.btn_clear.clicked.connect(self.reset_visualization)
        toolbar_layout.addWidget(self.btn_clear)

        header = QVBoxLayout()
        self.lbl_header_title = QLabel("Satellite Image Analyst Console")
        self.lbl_header_title.setObjectName("HeaderTitle")
        self.lbl_header_meta = QLabel("No dataset loaded")
        self.lbl_header_meta.setObjectName("HeaderMeta")
        header.addWidget(self.lbl_header_title)
        header.addWidget(self.lbl_header_meta)
        toolbar_layout.addLayout(header, 1)

        self.btn_generate = QPushButton("▶  Generate")
        self.btn_generate.setProperty("role", "primary")
        self.btn_generate.clicked.connect(self.run_process)
        toolbar_layout.addWidget(self.btn_generate)

        self.btn_export = QPushButton("↗  Export")
        self.btn_export.setProperty("role", "secondary")
        self.btn_export.clicked.connect(self.export_image)
        toolbar_layout.addWidget(self.btn_export)

        self.btn_video = QPushButton("▤  Video")
        self.btn_video.setProperty("role", "secondary")
        self.btn_video.clicked.connect(self.export_video_sequence)
        toolbar_layout.addWidget(self.btn_video)

        self.btn_cancel_video = QPushButton("⊗  Cancel")
        self.btn_cancel_video.setProperty("role", "danger")
        self.btn_cancel_video.setEnabled(False)
        self.btn_cancel_video.clicked.connect(self._cancel_video_export)
        toolbar_layout.addWidget(self.btn_cancel_video)

        parent_layout.addWidget(toolbar)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("LeftPanel")
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        gb_bands = QGroupBox("Bands & RGB")
        gb_bands_layout = QVBoxLayout(gb_bands)
        gb_bands_layout.setSpacing(8)

        gb_bands_layout.addWidget(QLabel("Available Bands (drag into RGB channels)"))
        self.band_list = DraggableList(density="comfortable")
        self.band_list.currentItemChanged.connect(lambda *_: self._sync_action_states())
        gb_bands_layout.addWidget(self.band_list, 1)

        for ch_letter, ch_placeholder, attr in [
            ("R", "Red (e.g. B13)",   "drop_r"),
            ("G", "Green (e.g. B12)", "drop_g"),
            ("B", "Blue (e.g. B09)",  "drop_b"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(ch_letter)
            lbl.setProperty("channel", ch_letter)
            lbl.setFixedWidth(14)
            drop = BandDropZone(ch_placeholder, channel=ch_letter)
            drop.textChanged.connect(self._sync_action_states)
            setattr(self, attr, drop)
            btn_clr = QPushButton("×")
            btn_clr.setProperty("role", "clear_band")
            btn_clr.setToolTip(f"Clear {ch_letter} channel")
            btn_clr.clicked.connect(drop.clear_band)
            setattr(self, f"btn_clear_{ch_letter.lower()}", btn_clr)
            row.addWidget(lbl)
            row.addWidget(drop, 1)
            row.addWidget(btn_clr)
            gb_bands_layout.addLayout(row)

        layout.addWidget(gb_bands)

        gb_proj = QGroupBox("Projection")
        gb_proj_layout = QVBoxLayout(gb_proj)
        gb_proj_layout.addWidget(QLabel("Output Projection"))
        self.combo_proj = QComboBox()
        proj_options = get_available_projections()
        for proj_id, proj_name, proj_desc in proj_options:
            self.combo_proj.addItem(f"{proj_name} ({proj_desc})", proj_id)
        gb_proj_layout.addWidget(self.combo_proj)
        layout.addWidget(gb_proj)

        gb_enhance = QGroupBox("Enhancement")
        gb_enh_layout = QVBoxLayout(gb_enhance)
        gb_enh_layout.setSpacing(8)

        self.lbl_gamma = QLabel("Gamma: 1.0")
        self.slider_gamma = QSlider(Qt.Orientation.Horizontal)
        self.slider_gamma.setRange(5, 30)
        self.slider_gamma.setValue(10)
        self.slider_gamma.valueChanged.connect(self.on_gamma_change)
        gb_enh_layout.addWidget(self.lbl_gamma)
        gb_enh_layout.addWidget(self.slider_gamma)

        self.lbl_opacity = QLabel("Overlay Opacity: 100%")
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.valueChanged.connect(self.on_opacity_change)
        gb_enh_layout.addWidget(self.lbl_opacity)
        gb_enh_layout.addWidget(self.slider_opacity)

        layout.addWidget(gb_enhance)
        layout.addStretch(1)
        return panel

    def _build_main_view(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("MainCenter")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        status_row = QHBoxLayout()
        self.lbl_view_status = QLabel("View: No image yet")
        self.lbl_view_status.setObjectName("ViewStatusLabel")
        self.lbl_render_info = QLabel("Render: --")
        self.lbl_render_info.setObjectName("RenderInfoLabel")
        status_row.addWidget(self.lbl_view_status, 1)
        status_row.addWidget(self.lbl_render_info, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(status_row)

        self.tabs = QTabWidget()
        self.canvas_2d = GeoCanvas()
        self.tabs.addTab(self.canvas_2d, "  2D Map")
        self.canvas_3d = Globe3DCanvas()
        self.tabs.addTab(self.canvas_3d, "  3D Globe")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)
        return panel

    def _build_right_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("RightPanel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        gb_player = QGroupBox("Time Series")
        player_layout = QVBoxLayout(gb_player)
        self.lbl_time = QLabel("Time: N/A")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        player_layout.addWidget(self.lbl_time)

        self.slider_time = QSlider(Qt.Orientation.Horizontal)
        self.slider_time.setEnabled(False)
        self.slider_time.valueChanged.connect(self.on_slider_move)
        self.slider_time.sliderReleased.connect(self.on_slider_released)
        player_layout.addWidget(self.slider_time)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀  Prev")
        self.btn_next = QPushButton("Next  ▶")
        self.btn_prev.setProperty("role", "ghost")
        self.btn_next.setProperty("role", "ghost")
        self.btn_prev.clicked.connect(self.prev_frame)
        self.btn_next.clicked.connect(self.next_frame)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        player_layout.addLayout(nav)

        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("Frame #"))
        self.spin_frame_index = QSpinBox()
        self.spin_frame_index.setMinimum(1)
        self.spin_frame_index.setMaximum(1)
        self.spin_frame_index.setEnabled(False)
        self.spin_frame_index.setKeyboardTracking(False)
        self.spin_frame_index.setToolTip("Input target frame number (1-based)")
        self.spin_frame_index.editingFinished.connect(self._jump_to_spin_frame)
        jump_row.addWidget(self.spin_frame_index, 1)

        self.btn_jump_frame = QPushButton("Go")
        self.btn_jump_frame.setProperty("role", "secondary")
        self.btn_jump_frame.setEnabled(False)
        self.btn_jump_frame.clicked.connect(self._jump_to_spin_frame)
        jump_row.addWidget(self.btn_jump_frame)
        player_layout.addLayout(jump_row)
        layout.addWidget(gb_player)

        gb_frame = QGroupBox("Frame Info")
        frame_layout = QVBoxLayout(gb_frame)
        self.lbl_frame_info = QLabel("Frame: --/--")
        self.lbl_frame_info.setObjectName("FrameInfoLabel")
        self.lbl_preview_info = QLabel("Preview: Idle")
        self.lbl_preview_info.setObjectName("FrameInfoLabel")
        frame_layout.addWidget(self.lbl_frame_info)
        frame_layout.addWidget(self.lbl_preview_info)
        layout.addWidget(gb_frame)

        gb_export = QGroupBox("Export")
        export_layout = QVBoxLayout(gb_export)
        self.lbl_export_info = QLabel("Export: idle")
        self.lbl_export_info.setObjectName("ExportInfoLabel")
        export_layout.addWidget(self.lbl_export_info)
        layout.addWidget(gb_export)

        layout.addStretch(1)
        return panel

    def _build_status_bar(self) -> None:
        self.status_dot = QLabel()
        self.status_dot.setObjectName("StatusDot")
        self.status_dot.setProperty("level", "idle")
        self.status_dot.setFixedSize(10, 10)
        self.statusBar().addPermanentWidget(self.status_dot)
        self.statusBar().showMessage("Ready")

    def _apply_component_styles(self) -> None:
        for btn in [
            self.btn_load,
            self.btn_clear,
            self.btn_generate,
            self.btn_export,
            self.btn_video,
            self.btn_cancel_video,
            self.btn_prev,
            self.btn_next,
            self.btn_jump_frame,
            self.btn_clear_r,
            self.btn_clear_g,
            self.btn_clear_b,
        ]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _bind_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence("Ctrl+O"), self, activated=self.load_data),
            QShortcut(QKeySequence("Ctrl+R"), self, activated=self.run_process),
            QShortcut(QKeySequence("Ctrl+L"), self, activated=self.reset_visualization),
            QShortcut(QKeySequence("Ctrl+G"), self, activated=self._focus_frame_input),
            QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export_image),
            QShortcut(QKeySequence("Ctrl+Shift+E"), self, activated=self.export_video_sequence),
            QShortcut(QKeySequence("Space"), self, activated=lambda: self._set_ui_status("idle", "Playback toggle reserved")),
        ]

    def _set_ui_status(self, level: str, message: str) -> None:
        level = level if level in {"idle", "loading", "success", "error"} else "idle"
        self.statusBar().showMessage(message)
        if hasattr(self, "status_dot"):
            self.status_dot.setProperty("level", level)
            self.status_dot.style().unpolish(self.status_dot)
            self.status_dot.style().polish(self.status_dot)
            self.status_dot.update()
        if hasattr(self, "lbl_preview_info"):
            self.lbl_preview_info.setText(f"Preview: {message}")
        if hasattr(self, "lbl_view_status"):
            self.lbl_view_status.setText(f"View: {message}")
        if hasattr(self, "lbl_export_info"):
            self.lbl_export_info.setText(f"Export: {level}")

    def _on_controller_status(self, source: str, message: str) -> None:
        low = (message or "").lower()
        success_keywords = ("ready", "complete", "completed", "loaded", "finished", "done", "success")
        error_keywords = ("error", "failed", "exception", "abort")
        if any(k in low for k in error_keywords):
            self._set_ui_status("error", message)
            return
        if any(k in low for k in success_keywords):
            self._set_ui_status("success", message)
            return
        self._set_ui_status("loading", message)

    def _sync_action_states(self) -> None:
        r, g, b = self.drop_r.text().strip(), self.drop_g.text().strip(), self.drop_b.text().strip()
        rgb_complete = bool(r and g and b)
        selected_band = self.band_list.currentItem() is not None
        can_generate = rgb_complete or selected_band
        self.btn_generate.setEnabled(can_generate)

        for zone in [self.drop_r, self.drop_g, self.drop_b]:
            if zone.text().strip():
                zone.set_state(BandDropZone.STATE_ACTIVE)
            else:
                zone.set_state(BandDropZone.STATE_NORMAL)

        self.btn_video.setEnabled(bool(self.file_groups) and rgb_complete and not self.btn_cancel_video.isEnabled())
        self.btn_prev.setEnabled(bool(self.file_groups))
        self.btn_next.setEnabled(bool(self.file_groups))
        can_jump = bool(self.file_groups)
        self.spin_frame_index.setEnabled(can_jump)
        self.btn_jump_frame.setEnabled(can_jump)

    def _focus_frame_input(self):
        if not self.file_groups:
            return
        self.spin_frame_index.setFocus()
        self.spin_frame_index.selectAll()

    def _jump_to_spin_frame(self):
        if not self.file_groups:
            return
        target = int(self.spin_frame_index.value()) - 1
        if target == self.current_frame_index:
            return
        if target < 0 or target >= len(self.file_groups):
            self._set_ui_status("error", f"Frame out of range: {target + 1}")
            return
        self.load_frame(target)

    def reset_visualization(self):
        """Clear current visualization content and cached render state."""
        self.cached_img = None
        self.cached_extent = None
        self.current_bands = []
        self._last_render_request_signature = None
        self._state.clear_image_cache()
        self._state.img_3d = None
        self._state.extent_3d = None
        self._state.proj_3d = None

        try:
            self.canvas_2d.clear_view()
        except Exception as exc:
            logger.warning(f"2D clear failed: {exc}")
        try:
            self.canvas_3d.clear_overlay()
        except Exception as exc:
            logger.warning(f"3D clear failed: {exc}")

        self.lbl_view_status.setText("View: cleared")
        self.lbl_render_info.setText("Render: --")
        self.lbl_preview_info.setText("Preview: cleared")
        self._set_ui_status("success", "Visualization cleared")

    def _get_driver(self):
        """Get the active driver (legacy or manager wrapper)."""
        if self.manager:
            return self.manager
        return self.driver

    def load_data(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if not folder:
            return

        self._band_dataset_signature = None
        self._last_render_request_signature = None
        self._state.clear_image_cache()
        self._img_ctrl.clear_cache()

        self._set_ui_status("loading", "Scanning folder...")

        try:
            # Scan and group files
            if self.manager:
                # Use new manager API
                files = self.manager.scan_directory(folder)

                if not files:
                    QMessageBox.warning(self, "Error", "No supported satellite files found.")
                    return

                # Identify satellite types for the files
                file_info = self.manager.identify_files(files)

                # Determine dominant satellite type for loading
                type_counts = {}
                for info in file_info:
                    if info.driver_type:
                        type_counts[info.driver_type] = type_counts.get(info.driver_type, 0) + 1

                if not type_counts:
                    QMessageBox.warning(self, "Error", "Could not determine satellite type.")
                    return

                # Get dominant satellite type
                dominant_type = max(type_counts, key=type_counts.get)
                self._set_ui_status("loading", f"Detected satellite: {dominant_type}")

                # Load first time group to get band information
                # Group all files by timestamp for time-series playback
                # Pass dominant_type to skip a redundant identify_files() call
                time_groups = self.manager.get_time_series_groups(files, driver_type=dominant_type)
                self.file_groups = time_groups
                self._ts_ctrl.set_file_groups(time_groups)

                if not self.file_groups:
                    QMessageBox.warning(self, "Error", "No valid time-series groups found.")
                    return

                # Set up UI controls immediately (don't wait for async frame load).
                # The frame_loaded signal will fire when background loading completes.
                self.slider_time.setEnabled(True)
                self.slider_time.setRange(0, max(0, len(self.file_groups) - 1))
                self.spin_frame_index.setRange(1, max(1, len(self.file_groups)))
                self.spin_frame_index.setValue(1)
                self.spin_frame_index.setEnabled(True)
                self.btn_jump_frame.setEnabled(True)
                self.lbl_header_meta.setText(
                    f"{dominant_type} | {len(self.file_groups)} frames detected"
                )
                self._sync_action_states()
                # Start async first-frame load
                self._ts_ctrl.load_frame(0, driver_type=dominant_type)
            else:
                # Use legacy driver API
                groups = self.driver.scan_and_group_files(folder)

                if not groups:
                    QMessageBox.warning(self, "Error", "No supported satellite files found.")
                    return

                self.file_groups = groups
                self.load_frame(0)

        except Exception as e:
            self._set_ui_status("error", f"Error loading data: {str(e)}")
            QMessageBox.critical(self, "Load Error", f"Failed to load satellite data:\n{str(e)}")

    def _update_band_list_from_manager(self):
        """Update band list from manager."""
        try:
            bands = self.manager.get_available_bands()
            if not bands:
                return

            band_names = []
            for b in bands:
                # Handle both dict and object access
                if isinstance(b, dict):
                    band_names.append(b.get('display', b.get('canonical', str(b))))
                else:
                    band_names.append(getattr(b, 'display', getattr(b, 'canonical_name', str(b))))

            signature = tuple(sorted(band_names))
            if signature == self._band_dataset_signature:
                return
            self._band_dataset_signature = signature

            self.band_list.clear()
            self.band_list.addItems(sorted(band_names))
            self._sync_action_states()
        except Exception as e:
            logger.warning(f"Error updating band list: {e}")

    def _update_time_label(self, meta, index=None):
        """Update time label from metadata."""
        time_str = meta.get('start_time', 'Unknown')
        total = len(self.file_groups) if self.file_groups else 1
        idx = index + 1 if index is not None else (self.current_frame_index + 1 if self.current_frame_index >= 0 else 1)
        self.lbl_time.setText(f"{time_str}\n[{idx}/{total}]")

    # Load specific frame
    def load_frame(self, index):
        if not self.file_groups or index < 0 or index >= len(self.file_groups):
            return
        # load_frame now returns True immediately (async start); errors arrive via signal
        self._ts_ctrl.load_frame(index)

    # Frame navigation
    def prev_frame(self):
        self._ts_ctrl.go_to_prev()

    def next_frame(self):
        self._ts_ctrl.go_to_next()

    def on_slider_move(self, value):
        # Update label while dragging without triggering heavy recomputation.
        total = len(self.file_groups) if self.file_groups else 0
        if total > 0:
            self.lbl_time.setText(f"Frame Preview\n[{value + 1}/{total}]")
            self.lbl_frame_info.setText(f"Frame: {value + 1}/{total}")

        # For non-drag updates (e.g. keyboard steps), use debounce loading.
        if not self.slider_time.isSliderDown():
            self._pending_slider_index = value
            self._slider_debounce_timer.start(120)

    def on_slider_released(self):
        value = self.slider_time.value()
        if value != self.current_frame_index:
            self.load_frame(value)

    def _on_tab_changed(self, index: int):
        """When entering 3D tab, trigger texture generation lazily if needed."""
        if index != 1:
            return
        if self.cached_img is None:
            return

        proj_id = self.combo_proj.currentData()
        if proj_id == 'geostationary_native':
            if self._state.img_3d is None or self._state.proj_3d != 'plate_carree_global':
                self._set_ui_status("loading", "正在生成 3D 纹理...")
                self._generate_3d_texture()
                return
        self.update_3d_view()

    def _apply_debounced_slider_load(self):
        if self._pending_slider_index is None:
            return
        idx = self._pending_slider_index
        self._pending_slider_index = None
        if idx != self.current_frame_index:
            self.load_frame(idx)

    # 閻熸瑥妫濋。鍓佲偓鐢靛帶閸ゎ參鏌呴弰蹇曞竼
    def export_video_sequence(self):
        if not self.file_groups:
            return

        # 闁兼儳鍢茶ぐ鍥亹閹惧啿顤呮繛澶堝灪椤斿瞼鎷嬮崜褏鏋?
        r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
        bands = []
        if r and g and b:
            bands = [r, g, b]
        else:
            QMessageBox.information(self, "Info", "Please setup RGB bands first.")
            return

        # 闂侇偄顦扮€氥劍绌卞┑鍡欐憼閻犱警鍨扮欢?
        output_file, _ = QFileDialog.getSaveFileName(self, "Save Video", "", "MP4 Video (*.mp4)")
        if not output_file:
            return

        proj_id = self.combo_proj.currentData()
        started = self._exp_ctrl.start_video_export(
            output_path=output_file,
            bands=bands,
            gamma=self.current_gamma,
            projection=proj_id,
            fps=10,
        )
        if started:
            self.btn_video.setEnabled(False)
            self.btn_cancel_video.setEnabled(True)
            self._set_ui_status("loading", "Exporting video... This may take a while.")
            self._sync_action_states()
    
    def on_video_progress(self, current, total):
        self._set_ui_status("loading", f"Exporting Video: Frame {current}/{total}...")
        self.lbl_export_info.setText(f"Export: frame {current}/{total}")

    def on_video_finished(self, path):
        self.btn_video.setEnabled(True)
        self.btn_cancel_video.setEnabled(False)
        self._set_ui_status("success", "Video Export Complete!")
        self._sync_action_states()
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def _execute_driver_load(self, files):
        if self.driver.load_scene(files):
            bands = self.driver.get_available_datasets()
            self.band_list.clear()
            self.band_list.addItems(sorted(bands))
            
            meta = self.driver.get_metadata()
            self._set_ui_status("success", f"Loaded: {meta.get('platform')} | {meta.get('start_time')}")
        else:
            self._set_ui_status("error", "Failed to load scene.")
            QMessageBox.critical(self, "Error", "Failed to load satellite data.\nCheck console for details.")

    def on_gamma_change(self, value):
        self.current_gamma = value / 10.0
        self.lbl_gamma.setText(f"Gamma: {self.current_gamma}")

    def run_process(self, silent: bool = False):
        bands = self._collect_selected_bands()
        if not bands:
            if not silent:
                missing = []
                if not self.drop_r.text().strip():
                    missing.append("R")
                if not self.drop_g.text().strip():
                    missing.append("G")
                if not self.drop_b.text().strip():
                    missing.append("B")
                if 0 < len(missing) < 3:
                    QMessageBox.information(self, "Info", f"Missing RGB channels: {', '.join(missing)}")
                else:
                    QMessageBox.information(self, "Info", "Please select bands or drag to RGB boxes.")
                self._set_ui_status("error", "Generate blocked: incomplete band selection")
            return

        proj_id = self.combo_proj.currentData()
        self.current_bands = bands.copy()
        self._state.selected_bands = bands.copy()
        self._state.gamma = self.current_gamma
        self._state.current_projection = proj_id

        preview_size = self._get_preview_output_size(max_side=1600)
        need_3d_texture = self.tabs.currentIndex() == 1
        self._last_render_request_signature = (
            self.current_frame_index,
            tuple(bands),
            proj_id,
            round(float(self.current_gamma), 3),
            preview_size,
            bool(need_3d_texture),
        )
        self._img_ctrl.generate_image(
            bands=bands,
            projection=proj_id,
            gamma=self.current_gamma,
            output_size=preview_size,
            quality_profile="preview_fast",
            resample_method="nearest",
            need_3d_texture=need_3d_texture,
        )
        self._set_ui_status("loading", "Rendering preview...")

    def _collect_selected_bands(self):
        """Get selected bands from RGB dropzones or single-band list selection."""
        r = self.drop_r.text()
        g = self.drop_g.text()
        b = self.drop_b.text()
        if r and g and b:
            return [r, g, b]
        if self.band_list.currentItem():
            return [self.band_list.currentItem().text()]
        return []

    def _get_preview_output_size(self, max_side: int = 1600):
        """Estimate a fast preview output size from the 2D canvas size."""
        try:
            w = max(320, int(self.canvas_2d.canvas.width()))
            h = max(240, int(self.canvas_2d.canvas.height()))
        except Exception:
            w, h = 1200, 800

        scale = min(1.0, float(max_side) / float(max(w, h)))
        out_w = max(320, int(w * scale))
        out_h = max(240, int(h * scale))
        return (out_w, out_h)

    def on_data_ready(self, img, area_def):
        """Handle image data returned from background worker."""
        logger.debug(f"[MainWindow] Image ready: shape={img.shape}")
        self.lbl_render_info.setText(f"Render: {img.shape[1]}x{img.shape[0]}")

        # 缂傚倹鎸搁悺銊ㄣ亹閹惧啿顤呴柡浣哄瀹撲線鏁嶇仦鑲╄繑婵犲﹥鍨靛锛勬嫬閸愨晜娈诲ù锝堟硶閺?
        self.cached_img = img

        # 闁哄秷顫夊畵渚€宕堕幆褍鍓奸悘蹇撴惈椤曨厾娑甸鑲╂毎婵繐绲块垾姗€鎯?extent
        h, w = img.shape[:2]
        logger.debug(f"[MainWindow] Detecting extent: w={w}, h={h}")

        # 闁活潿鍔戦崢銈囩磾椤旇￥鈧啴寮撮幐搴″簥缁绢収鍓涚槐顏堟儘娴ｇ儤鐣卞鍕⒐绾爼寮弶璺ㄦ憻
        grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
        if grid_proj is not None:
            self.cached_extent = PROJECTION_GRID_EXTENTS[grid_proj]
            logger.debug(f"[MainWindow] Grid proj '{grid_proj}': using extent {self.cached_extent}")
        else:
            # 闁稿繑婀圭划顒勫箚閸涱厼鏋岄柨娑樻箼eostationary 闁告鍠撻弫鎾剁驳婢舵稓绀嗛柨娑欑煯婵炲洭鎮介妸銉﹀嬀闁荤偛妫滅€垫牠宕?
            self.cached_extent = get_geographic_extent(area_def)
            logger.debug(f"[MainWindow] Other: using geo extent {self.cached_extent}")

        # 1. 闁哄洤鐡ㄩ弻?2D 闁革附婢樺ù?
        try:
            self.canvas_2d.update_image(img, area_def)
        except Exception as e:
            logger.exception(f"2D update failed: {e}")

        # 2. 闁哄洤鐡ㄩ弻?3D 闁革附澹嗛幃?(濞达綀娉曢弫銈堛亹閹惧啿顤呮繝濠冨灥濞硷繝鎯冮崟顖楀亾韫囨梹顫栭幖?
        self.update_3d_view()
        self._set_ui_status("success", "Preview updated")
    
    def on_opacity_change(self, value):
        """Update 3D overlay opacity."""
        self.lbl_opacity.setText(f"Overlay Opacity: {value}%")
        # 閻庡湱鍋炲鍌炲礆闁垮鐓€ 3D 閻熸瑥妫楀ù?
        self.update_3d_view()
    
    def update_3d_view(self):
        """Refresh the 3D globe texture preview."""
        if self.tabs.currentIndex() != 1:
            return
        if self.cached_img is None or not getattr(self.canvas_3d, 'available', True):
            return

        try:
            alpha = self.slider_opacity.value() / 100.0
            proj_id = self.combo_proj.currentData()

            if proj_id == 'geostationary_native':
                img_3d = self._state.img_3d
                extent_3d = self._state.extent_3d
                if img_3d is None or extent_3d is None:
                    self._generate_3d_texture()
                    return
            else:
                img_3d = self.cached_img
                extent_3d = self.cached_extent

            if img_3d is None or extent_3d is None:
                return

            self.canvas_3d.update_texture(
                img_3d,
                extent=extent_3d,
                alpha=alpha,
            )
        except Exception as e:
            logger.exception(f"3D update failed: {e}")

    def _generate_3d_texture(self):
        """Generate a plate_carree_global texture for 3D globe rendering."""
        try:
            bands = self._collect_selected_bands()
            if not bands and self.current_bands:
                bands = self.current_bands.copy()
            if not bands:
                logger.info("[3D] No bands selected for texture generation")
                return

            self._img_ctrl.generate_3d_texture(
                bands=bands,
                gamma=self.current_gamma if hasattr(self, 'current_gamma') else 1.0,
                output_size=(1600, 800),
            )
        except Exception as e:
            logger.exception(f"3D texture generation failed: {e}")

    def _on_3d_texture_ready(self, img, area_def):
        """Legacy callback retained for compatibility with older paths."""
        try:
            h, w = img.shape[:2]
            grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
            if grid_proj is not None:
                extent = PROJECTION_GRID_EXTENTS[grid_proj]
            else:
                extent = get_geographic_extent(area_def)

            self._state.img_3d = img
            self._state.extent_3d = extent
            self._state.proj_3d = 'plate_carree_global'
            self.update_3d_view()
        except Exception as e:
            logger.exception(f"3D texture ready callback failed: {e}")

    def on_worker_error(self, message: str):
        """Handle worker error and notify user."""
        try:
            self._set_ui_status("error", f"Processing error: {message}")
            QMessageBox.critical(self, "Processing Error", f"Failed to generate image:\n{message}")
        except Exception:
            logger.error(f"Worker error (no UI): {message}")

    def export_image(self):
        """Export current image to PNG or GeoTIFF."""
        # 闁兼儳鍢茶ぐ鍥亹閹惧啿顤呴梺顐㈩槹鐎氥劑鎯冮崟顒€鐨炬繛鍫ユ涧閹蜂即骞庨弴鐐差殯
        r, g, b = self.drop_r.text(), self.drop_g.text(), self.drop_b.text()
        bands = []

        if r and g and b:
            bands = [r, g, b]
        elif self.band_list.currentItem():
            bands = [self.band_list.currentItem().text()]
        else:
            QMessageBox.information(self, "Info", "Please select bands first.")
            return

        # 闁兼儳鍢茶ぐ鍥箮閺囩偛顨涢柛婊冩湰閺嬪啯绂掗幆鎵唴鐎?
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

        # 闁告艾楠歌ぐ瀵哥棯鐠恒劉鏌ら悗鐢靛帶閸?
        self._set_ui_status("loading", f"Exporting to {proj_name}...")
        self.lbl_export_info.setText("Export: still image running")
        self._exp_ctrl.export_still(
            output_path=output_path,
            bands=bands,
            gamma=self.current_gamma,
            projection=proj_id,
        )

    # ==========================================================================
    # Controller Slots 闁?wired in __init__, bridge controllers 闁?legacy UI
    # ==========================================================================

    def _on_image_ctrl_ready(self, img, extent, area_def):
        """Slot: ImageViewController finished generating a 2D image."""
        self.cached_img    = img
        self.cached_extent = extent
        # Delegate to existing rendering path
        self.on_data_ready(img, area_def)

    def _on_3d_texture_ctrl_ready(self, img, extent):
        """Slot: ImageViewController finished generating a 3D plate-carr閼煎崘 texture."""
        self._state.img_3d    = img
        self._state.extent_3d = extent
        self._state.proj_3d = 'plate_carree_global'
        if self.tabs.currentIndex() != 1:
            return
        alpha = self.slider_opacity.value() / 100.0
        try:
            self.canvas_3d.update_texture(img, extent=extent, alpha=alpha)
        except Exception as exc:
            logger.exception(f"[MainWindow] 3D texture update failed: {exc}")

    def _on_frame_loaded(self, index: int, total: int, time_str: str):
        """Slot: TimeSeriesController finished loading a frame."""
        self.current_frame_index = index
        self._state.current_frame_index = index
        self.lbl_time.setText(f"{time_str}\n[{index + 1}/{total}]")
        self.lbl_frame_info.setText(f"Frame: {index + 1}/{total}")
        self.lbl_header_meta.setText(f"Current time: {time_str} | total frames: {total}")

        # Update slider position without triggering another load
        self.slider_time.blockSignals(True)
        self.slider_time.setValue(index)
        self.slider_time.blockSignals(False)
        self.spin_frame_index.blockSignals(True)
        self.spin_frame_index.setRange(1, max(1, total))
        self.spin_frame_index.setValue(index + 1)
        self.spin_frame_index.blockSignals(False)

        # Update band list if needed
        self._update_band_list_from_manager()
        self._sync_action_states()

        bands = self._collect_selected_bands()
        if not bands:
            return

        proj_id = self.combo_proj.currentData()
        preview_size = self._get_preview_output_size(max_side=1600)
        need_3d_texture = self.tabs.currentIndex() == 1
        signature = (
            index,
            tuple(bands),
            proj_id,
            round(float(self.current_gamma), 3),
            preview_size,
            bool(need_3d_texture),
        )
        if signature == self._last_render_request_signature:
            return

        self.run_process(silent=True)

    def _on_export_finished(self, path: str):
        """Slot: ExportController still-image export completed."""
        self._set_ui_status("success", "Export complete!")
        self.lbl_export_info.setText("Export: still image done")
        QMessageBox.information(self, "Export Success", f"Saved to:\n{path}")

    def _on_video_ctrl_finished(self, path: str):
        """Slot: ExportController video export completed."""
        self.btn_video.setEnabled(True)
        self.btn_cancel_video.setEnabled(False)
        self._set_ui_status("success", "Video Export Complete!")
        self._sync_action_states()
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def _cancel_video_export(self):
        """Request cancellation of the running video export."""
        self._exp_ctrl.cancel_video_export()
        self.btn_cancel_video.setEnabled(False)
        self._set_ui_status("loading", "Cancelling video export...")
        self.lbl_export_info.setText("Export: cancelling...")
        self._sync_action_states()

    def closeEvent(self, event):
        """Stop background workers before window destruction."""
        try:
            self._img_ctrl.shutdown()
            self._exp_ctrl.shutdown()
        except Exception as exc:
            logger.exception(f"Controller shutdown failed: {exc}")
        super().closeEvent(event)





