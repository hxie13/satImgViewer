import sys
import os
import logging
from typing import Optional, Tuple
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QLabel, QSplitter,
                             QGroupBox, QSlider, QTabWidget, QMessageBox, QComboBox,
                             QFrame, QSpinBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence, QIcon

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
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        # Keep title/version out of the UI for software copyright screenshots/materials.
        self.setWindowTitle("多源卫星影像处理与可视化软件")
        self.resize(1400, 900)

        # Initialize SatelliteImageManager
        self._manager = SatelliteImageManager()

        # Centralised application state
        self._state = AppState()

        # Controllers (MVP: presentation logic separated from layout)
        self._image_controller  = ImageViewController(self._manager, self._state, parent=self)
        self._timeseries_controller   = TimeSeriesController(self._manager, self._state, parent=self)
        self._export_controller  = ExportController(self._manager, self._state, parent=self)

        # Wire controller signals to UI slots
        self._image_controller.image_ready.connect(self._on_image_ctrl_ready)
        self._image_controller.texture_3d_ready.connect(self._on_3d_texture_ctrl_ready)
        self._image_controller.error.connect(self.on_worker_error)
        self._image_controller.status.connect(lambda m: self._on_controller_status("image", m))

        self._timeseries_controller.frame_loaded.connect(self._on_frame_loaded)
        self._timeseries_controller.frame_loading.connect(
            lambda: self._set_ui_status("loading", "Loading frame...")
        )
        self._timeseries_controller.error.connect(self.on_worker_error)
        self._timeseries_controller.status.connect(lambda m: self._on_controller_status("timeseries", m))

        self._export_controller.export_finished.connect(self._on_export_finished)
        self._export_controller.export_error.connect(self.on_worker_error)
        self._export_controller.video_progress.connect(self.on_video_progress)
        self._export_controller.video_finished.connect(self._on_video_ctrl_finished)
        self._export_controller.video_error.connect(self._on_video_ctrl_error)
        self._export_controller.status.connect(lambda m: self._on_controller_status("export", m))

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
        self._fy3d_china_projection_warn_key = None
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

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.main_splitter, 1)

        left_panel = self._build_left_panel()
        center_panel = self._build_main_view()
        right_panel = self._build_right_inspector()

        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(center_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([300, 1000, 340])

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

        self.load_button = QPushButton("⊞  Load Folder")
        self.load_button.setProperty("role", "secondary")
        self.load_button.clicked.connect(self.load_data)
        toolbar_layout.addWidget(self.load_button)

        self.clear_button = QPushButton("↺  Reset")
        self.clear_button.setProperty("role", "secondary")
        self.clear_button.clicked.connect(self.reset_visualization)
        toolbar_layout.addWidget(self.clear_button)

        header = QVBoxLayout()
        self.header_title_label = QLabel("Satellite Image Analyst Console")
        self.header_title_label.setObjectName("HeaderTitle")
        self.header_meta_label = QLabel("No dataset loaded")
        self.header_meta_label.setObjectName("HeaderMeta")
        header.addWidget(self.header_title_label)
        header.addWidget(self.header_meta_label)
        toolbar_layout.addLayout(header, 1)

        self.generate_button = QPushButton("▶  Generate")
        self.generate_button.setProperty("role", "primary")
        self.generate_button.clicked.connect(self.run_process)
        toolbar_layout.addWidget(self.generate_button)

        self.export_button = QPushButton("↗  Export")
        self.export_button.setProperty("role", "secondary")
        self.export_button.clicked.connect(self.export_image)
        toolbar_layout.addWidget(self.export_button)

        self.video_button = QPushButton("▤  Video")
        self.video_button.setProperty("role", "secondary")
        self.video_button.clicked.connect(self.export_video_sequence)
        toolbar_layout.addWidget(self.video_button)

        self.cancel_video_button = QPushButton("⊗  Cancel")
        self.cancel_video_button.setProperty("role", "danger")
        self.cancel_video_button.setEnabled(False)
        self.cancel_video_button.clicked.connect(self._cancel_video_export)
        toolbar_layout.addWidget(self.cancel_video_button)

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
        self.band_list_widget = DraggableList(density="comfortable")
        self.band_list_widget.currentItemChanged.connect(lambda *_: self._sync_action_states())
        gb_bands_layout.addWidget(self.band_list_widget, 1)

        for ch_letter, ch_placeholder, drop_attr, btn_attr in [
            ("R", "Red (e.g. B13)",   "red_drop_zone", "clear_red_button"),
            ("G", "Green (e.g. B12)", "green_drop_zone", "clear_green_button"),
            ("B", "Blue (e.g. B09)",  "blue_drop_zone", "clear_blue_button"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(ch_letter)
            lbl.setProperty("channel", ch_letter)
            lbl.setFixedWidth(14)
            drop = BandDropZone(ch_placeholder, channel=ch_letter)
            drop.textChanged.connect(self._sync_action_states)
            setattr(self, drop_attr, drop)
            btn_clr = QPushButton("×")
            btn_clr.setProperty("role", "clear_band")
            btn_clr.setToolTip(f"Clear {ch_letter} channel")
            btn_clr.clicked.connect(drop.clear_band)
            setattr(self, btn_attr, btn_clr)
            row.addWidget(lbl)
            row.addWidget(drop, 1)
            row.addWidget(btn_clr)
            gb_bands_layout.addLayout(row)

        layout.addWidget(gb_bands)

        gb_proj = QGroupBox("Projection")
        gb_proj_layout = QVBoxLayout(gb_proj)
        gb_proj_layout.addWidget(QLabel("Output Projection"))
        self.projection_combobox = QComboBox()
        proj_options = get_available_projections()
        for proj_id, proj_name, proj_desc in proj_options:
            self.projection_combobox.addItem(f"{proj_name} ({proj_desc})", proj_id)
        self.projection_combobox.currentIndexChanged.connect(self._on_projection_changed)
        gb_proj_layout.addWidget(self.projection_combobox)
        layout.addWidget(gb_proj)

        gb_enhance = QGroupBox("Enhancement")
        gb_enh_layout = QVBoxLayout(gb_enhance)
        gb_enh_layout.setSpacing(8)

        self.gamma_label = QLabel("Gamma: 1.0")
        self.gamma_slider = QSlider(Qt.Orientation.Horizontal)
        self.gamma_slider.setRange(5, 30)
        self.gamma_slider.setValue(10)
        self.gamma_slider.valueChanged.connect(self.on_gamma_change)
        gb_enh_layout.addWidget(self.gamma_label)
        gb_enh_layout.addWidget(self.gamma_slider)

        self.opacity_label = QLabel("Overlay Opacity: 100%")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_change)
        gb_enh_layout.addWidget(self.opacity_label)
        gb_enh_layout.addWidget(self.opacity_slider)

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
        self.view_status_label = QLabel("View: No image yet")
        self.view_status_label.setObjectName("ViewStatusLabel")
        self.render_info_label = QLabel("Render: --")
        self.render_info_label.setObjectName("RenderInfoLabel")
        status_row.addWidget(self.view_status_label, 1)
        status_row.addWidget(self.render_info_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(status_row)

        self.view_tabs = QTabWidget()
        self.map_2d_canvas = GeoCanvas()
        self.view_tabs.addTab(self.map_2d_canvas, "  2D Map")
        self.globe_3d_canvas = Globe3DCanvas()
        self.view_tabs.addTab(self.globe_3d_canvas, "  3D Globe")
        self.view_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.view_tabs, 1)
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
        self.time_label = QLabel("Time: N/A")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        player_layout.addWidget(self.time_label)

        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_move)
        self.time_slider.sliderReleased.connect(self.on_slider_released)
        player_layout.addWidget(self.time_slider)

        nav = QHBoxLayout()
        self.previous_button = QPushButton("◀  Prev")
        self.next_button = QPushButton("Next  ▶")
        self.previous_button.setProperty("role", "ghost")
        self.next_button.setProperty("role", "ghost")
        self.previous_button.clicked.connect(self.prev_frame)
        self.next_button.clicked.connect(self.next_frame)
        nav.addWidget(self.previous_button)
        nav.addWidget(self.next_button)
        player_layout.addLayout(nav)

        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("Frame #"))
        self.frame_index_spinbox = QSpinBox()
        self.frame_index_spinbox.setMinimum(1)
        self.frame_index_spinbox.setMaximum(1)
        self.frame_index_spinbox.setEnabled(False)
        self.frame_index_spinbox.setKeyboardTracking(False)
        self.frame_index_spinbox.setToolTip("Input target frame number (1-based)")
        self.frame_index_spinbox.editingFinished.connect(self._jump_to_spin_frame)
        jump_row.addWidget(self.frame_index_spinbox, 1)

        self.jump_frame_button = QPushButton("Go")
        self.jump_frame_button.setProperty("role", "secondary")
        self.jump_frame_button.setEnabled(False)
        self.jump_frame_button.clicked.connect(self._jump_to_spin_frame)
        jump_row.addWidget(self.jump_frame_button)
        player_layout.addLayout(jump_row)
        layout.addWidget(gb_player)

        gb_frame = QGroupBox("Frame Info")
        frame_layout = QVBoxLayout(gb_frame)
        self.frame_info_label = QLabel("Frame: --/--")
        self.frame_info_label.setObjectName("FrameInfoLabel")
        self.preview_info_label = QLabel("Preview: Idle")
        self.preview_info_label.setObjectName("FrameInfoLabel")
        frame_layout.addWidget(self.frame_info_label)
        frame_layout.addWidget(self.preview_info_label)
        layout.addWidget(gb_frame)

        gb_export = QGroupBox("Export")
        export_layout = QVBoxLayout(gb_export)
        self.export_info_label = QLabel("Export: idle")
        self.export_info_label.setObjectName("ExportInfoLabel")
        export_layout.addWidget(self.export_info_label)
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
            self.load_button,
            self.clear_button,
            self.generate_button,
            self.export_button,
            self.video_button,
            self.cancel_video_button,
            self.previous_button,
            self.next_button,
            self.jump_frame_button,
            self.clear_red_button,
            self.clear_green_button,
            self.clear_blue_button,
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

    def _on_projection_changed(self, _index: int) -> None:
        """React to projection selection changes."""
        proj_id = self.projection_combobox.currentData()
        if isinstance(proj_id, str):
            self._state.current_projection = proj_id
        self._maybe_warn_fy3d_china_projection_risk(proj_id=proj_id)

    @staticmethod
    def _bbox_intersects(
        bbox_a: Tuple[float, float, float, float],
        bbox_b: Tuple[float, float, float, float],
    ) -> bool:
        """Check overlap for bboxes in (west, east, south, north)."""
        west_a, east_a, south_a, north_a = bbox_a
        west_b, east_b, south_b, north_b = bbox_b
        lon_overlap = max(west_a, west_b) <= min(east_a, east_b)
        lat_overlap = max(south_a, south_b) <= min(north_a, north_b)
        return bool(lon_overlap and lat_overlap)

    def _get_fy3d_swath_overlap_with_china(self) -> Optional[bool]:
        """
        Estimate whether current FY3D swath intersects China region.
        Returns True / False when known, or None when unavailable.
        """
        if self._manager.current_driver_type != "fengyun3d":
            return None

        try:
            metadata = self._manager.get_metadata()
        except Exception as exc:
            logger.debug("FY3D metadata unavailable for overlap check: %s", exc)
            return None

        overlap = metadata.get("swath_overlaps_china")
        if isinstance(overlap, bool):
            return overlap

        swath_extent = metadata.get("swath_extent")
        if (
            isinstance(swath_extent, (tuple, list))
            and len(swath_extent) == 4
            and all(isinstance(v, (int, float)) for v in swath_extent)
        ):
            swath_bbox = (
                float(swath_extent[0]),
                float(swath_extent[1]),
                float(swath_extent[2]),
                float(swath_extent[3]),
            )
            china_bbox = (70.0, 142.0, 15.0, 55.0)
            return self._bbox_intersects(swath_bbox, china_bbox)

        return None

    def _maybe_warn_fy3d_china_projection_risk(self, proj_id: Optional[str] = None) -> None:
        """Warn early for FY3D + China projection when China coverage is missing/unknown."""
        target_proj = proj_id if isinstance(proj_id, str) else self.projection_combobox.currentData()
        if target_proj != "plate_carree_china":
            return
        if self._manager.current_driver_type != "fengyun3d":
            return

        overlap = self._get_fy3d_swath_overlap_with_china()
        if overlap is True:
            return

        try:
            metadata = self._manager.get_metadata()
        except Exception:
            metadata = {}

        frame_key = (
            self.current_frame_index,
            metadata.get("start_time"),
            overlap,
        )
        if frame_key == self._fy3d_china_projection_warn_key:
            return
        self._fy3d_china_projection_warn_key = frame_key

        if overlap is False:
            message = (
                "Current FY3D swath likely does not cover China (70E-142E, 15N-55N).\n\n"
                "Using Plate Carree China may produce mostly NaN pixels and trigger "
                "\"All-NaN slice encountered\" warnings."
            )
        else:
            message = (
                "FY3D is polar-swath data. The current frame may not cover China "
                "(70E-142E, 15N-55N).\n\n"
                "Using Plate Carree China may produce many NaN pixels and trigger "
                "\"All-NaN slice encountered\" warnings."
            )

        QMessageBox.information(self, "FY3D Projection Risk", message)

    def _set_ui_status(self, level: str, message: str) -> None:
        level = level if level in {"idle", "loading", "success", "error"} else "idle"
        self.statusBar().showMessage(message)
        if hasattr(self, "status_dot"):
            self.status_dot.setProperty("level", level)
            self.status_dot.style().unpolish(self.status_dot)
            self.status_dot.style().polish(self.status_dot)
            self.status_dot.update()
        if hasattr(self, "lbl_preview_info"):
            self.preview_info_label.setText(f"Preview: {message}")
        if hasattr(self, "lbl_view_status"):
            self.view_status_label.setText(f"View: {message}")
        if hasattr(self, "lbl_export_info"):
            self.export_info_label.setText(f"Export: {level}")

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
        r, g, b = self.red_drop_zone.text().strip(), self.green_drop_zone.text().strip(), self.blue_drop_zone.text().strip()
        rgb_complete = bool(r and g and b)
        selected_band = self.band_list_widget.currentItem() is not None
        can_generate = rgb_complete or selected_band
        self.generate_button.setEnabled(can_generate)

        for zone in [self.red_drop_zone, self.green_drop_zone, self.blue_drop_zone]:
            if zone.text().strip():
                zone.set_state(BandDropZone.STATE_ACTIVE)
            else:
                zone.set_state(BandDropZone.STATE_NORMAL)

        # Keep Video button clickable once data exists; detailed RGB checks are
        # handled in export_video_sequence() with explicit user feedback.
        has_groups = bool(self.file_groups) or bool(self._state.file_groups)
        self.video_button.setEnabled(has_groups and not self.cancel_video_button.isEnabled())
        self.previous_button.setEnabled(bool(self.file_groups))
        self.next_button.setEnabled(bool(self.file_groups))
        can_jump = bool(self.file_groups)
        self.frame_index_spinbox.setEnabled(can_jump)
        self.jump_frame_button.setEnabled(can_jump)

    def _focus_frame_input(self):
        if not self.file_groups:
            return
        self.frame_index_spinbox.setFocus()
        self.frame_index_spinbox.selectAll()

    def _jump_to_spin_frame(self):
        if not self.file_groups:
            return
        target = int(self.frame_index_spinbox.value()) - 1
        if target == self.current_frame_index:
            return
        if target < 0 or target >= len(self.file_groups):
            self._set_ui_status("error", f"Frame out of range: {target + 1}")
            return
        self.load_frame(target)

    def reset_visualization(self, update_status: bool = True):
        """Clear current visualization content and cached render state."""
        self.cached_img = None
        self.cached_extent = None
        self.current_bands = []
        self._last_render_request_signature = None
        self._fy3d_china_projection_warn_key = None
        self._state.clear_image_cache()
        self._state.selected_bands = []
        self._state.img_3d = None
        self._state.extent_3d = None
        self._state.proj_3d = None

        try:
            self.map_2d_canvas.clear_view()
        except Exception as exc:
            logger.warning(f"2D clear failed: {exc}")
        try:
            self.globe_3d_canvas.clear_overlay()
        except Exception as exc:
            logger.warning(f"3D clear failed: {exc}")

        self.view_status_label.setText("View: cleared")
        self.render_info_label.setText("Render: --")
        self.preview_info_label.setText("Preview: cleared")
        if update_status:
            self._set_ui_status("success", "Visualization cleared")

    def _available_band_names(self) -> set:
        """Get currently listed band names from the GUI band list."""
        names = set()
        for i in range(self.band_list_widget.count()):
            item = self.band_list_widget.item(i)
            if item:
                txt = item.text().strip()
                if txt:
                    names.add(txt)
        return names

    def _sanitize_band_selection(self, valid_band_names: set) -> None:
        """
        Remove stale band selections that don't belong to the active dataset.
        """
        changed = False
        for zone in [self.red_drop_zone, self.green_drop_zone, self.blue_drop_zone]:
            txt = zone.text().strip()
            if txt and txt not in valid_band_names:
                zone.clear_band()
                changed = True

        selected = self.band_list_widget.currentItem()
        if selected and selected.text().strip() not in valid_band_names:
            self.band_list_widget.clearSelection()
            changed = True

        if changed:
            self.current_bands = []
            self._state.selected_bands = []
            self._last_render_request_signature = None

    def _reset_for_dataset_switch(self) -> None:
        """
        Reset GUI and backend state to startup-like baseline before loading a new folder.
        """
        self._slider_debounce_timer.stop()
        self._pending_slider_index = None

        self._export_controller.shutdown()
        self._timeseries_controller.shutdown(wait_ms=1000)
        self._image_controller.cancel()
        self._image_controller.clear_cache()

        self._manager.unload()

        self.file_groups = []
        self.current_frame_index = -1
        self.current_bands = []
        self._band_dataset_signature = None
        self._last_render_request_signature = None
        self._fy3d_china_projection_warn_key = None
        self._state.file_groups = []
        self._state.current_frame_index = -1
        self._state.selected_bands = []
        self._state.clear_image_cache()

        self.band_list_widget.clear()
        self.band_list_widget.clearSelection()
        self.red_drop_zone.clear_band()
        self.green_drop_zone.clear_band()
        self.blue_drop_zone.clear_band()

        self.time_slider.blockSignals(True)
        self.time_slider.setEnabled(False)
        self.time_slider.setRange(0, 0)
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)
        self.time_label.setText("Time: N/A")

        self.frame_index_spinbox.blockSignals(True)
        self.frame_index_spinbox.setRange(1, 1)
        self.frame_index_spinbox.setValue(1)
        self.frame_index_spinbox.setEnabled(False)
        self.frame_index_spinbox.blockSignals(False)
        self.jump_frame_button.setEnabled(False)
        self.frame_info_label.setText("Frame: --/--")

        self.video_button.setEnabled(False)
        self.cancel_video_button.setEnabled(False)
        self.export_info_label.setText("Export: idle")
        self.header_meta_label.setText("No dataset loaded")

        self.reset_visualization(update_status=False)
        self._sync_action_states()

    def load_data(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder")
        if not folder:
            return

        self._reset_for_dataset_switch()

        self._set_ui_status("loading", "Scanning folder...")

        try:
            files = self._manager.scan_directory(folder)

            if not files:
                QMessageBox.warning(self, "Error", "No supported satellite files found.")
                return

            # Identify satellite types for the files
            file_info = self._manager.identify_files(files)

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

            # Group all files by timestamp for time-series playback.
            # Pass dominant_type to skip a redundant identify_files() call.
            time_groups = self._manager.get_time_series_groups(files, driver_type=dominant_type)
            self.file_groups = time_groups
            self._timeseries_controller.set_file_groups(time_groups)

            if not self.file_groups:
                QMessageBox.warning(self, "Error", "No valid time-series groups found.")
                return

            # Set up UI controls immediately (don't wait for async frame load).
            # The frame_loaded signal will fire when background loading completes.
            self.time_slider.setEnabled(True)
            self.time_slider.setRange(0, max(0, len(self.file_groups) - 1))
            self.frame_index_spinbox.setRange(1, max(1, len(self.file_groups)))
            self.frame_index_spinbox.setValue(1)
            self.frame_index_spinbox.setEnabled(True)
            self.jump_frame_button.setEnabled(True)
            self.header_meta_label.setText(
                f"{dominant_type} | {len(self.file_groups)} frames detected"
            )
            self._sync_action_states()
            # Start async first-frame load
            self._timeseries_controller.load_frame(0, driver_type=dominant_type)

        except Exception as e:
            self._set_ui_status("error", f"Error loading data: {str(e)}")
            QMessageBox.critical(self, "Load Error", f"Failed to load satellite data:\n{str(e)}")

    def _update_band_list_from_manager(self):
        """Update band list from manager."""
        try:
            bands = self._manager.get_available_bands()
            if not bands:
                self._band_dataset_signature = None
                self.band_list_widget.clear()
                self.band_list_widget.clearSelection()
                self._sanitize_band_selection(set())
                self._sync_action_states()
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

            self.band_list_widget.clear()
            self.band_list_widget.addItems(sorted(band_names))
            self._sanitize_band_selection(set(band_names))
            self._sync_action_states()
        except Exception as e:
            logger.warning(f"Error updating band list: {e}")

    def _update_time_label(self, meta, index=None):
        """Update time label from metadata."""
        time_str = meta.get('start_time', 'Unknown')
        total = len(self.file_groups) if self.file_groups else 1
        idx = index + 1 if index is not None else (self.current_frame_index + 1 if self.current_frame_index >= 0 else 1)
        self.time_label.setText(f"{time_str}\n[{idx}/{total}]")

    # Load specific frame
    def load_frame(self, index):
        if not self.file_groups or index < 0 or index >= len(self.file_groups):
            return
        # load_frame now returns True immediately (async start); errors arrive via signal
        self._timeseries_controller.load_frame(index)

    # Frame navigation
    def prev_frame(self):
        self._timeseries_controller.go_to_prev()

    def next_frame(self):
        self._timeseries_controller.go_to_next()

    def on_slider_move(self, value):
        # Update label while dragging without triggering heavy recomputation.
        total = len(self.file_groups) if self.file_groups else 0
        if total > 0:
            self.time_label.setText(f"Frame Preview\n[{value + 1}/{total}]")
            self.frame_info_label.setText(f"Frame: {value + 1}/{total}")

        # For non-drag updates (e.g. keyboard steps), use debounce loading.
        if not self.time_slider.isSliderDown():
            self._pending_slider_index = value
            self._slider_debounce_timer.start(120)

    def on_slider_released(self):
        value = self.time_slider.value()
        if value != self.current_frame_index:
            self.load_frame(value)

    def _on_tab_changed(self, index: int):
        """When entering 3D tab, trigger texture generation lazily if needed."""
        if index != 1:
            return
        if self.cached_img is None:
            return

        proj_id = self.projection_combobox.currentData()
        if proj_id == 'geostationary_native':
            if self._state.img_3d is None or self._state.proj_3d != 'plate_carree_global':
                self._set_ui_status("loading", "Generating 3D texture...")
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

    # Video export button callback
    def export_video_sequence(self):
        groups = self._state.file_groups if self._state.file_groups else self.file_groups
        if not groups:
            self._set_ui_status("error", "Video export blocked: no time-series data loaded")
            QMessageBox.information(self, "Info", "No time-series data loaded yet. Please load a folder first.")
            return

        # Check RGB band selection
        r, g, b = self.red_drop_zone.text(), self.green_drop_zone.text(), self.blue_drop_zone.text()
        bands = []
        if r and g and b:
            bands = [r, g, b]
        else:
            QMessageBox.information(self, "Info", "Please setup RGB bands first.")
            return

        # Get output file path
        output_file, _ = QFileDialog.getSaveFileName(self, "Save Video", "", "MP4 Video (*.mp4)")
        if not output_file:
            return

        proj_id = self.projection_combobox.currentData()
        started = self._export_controller.start_video_export(
            output_path=output_file,
            bands=bands,
            gamma=self.current_gamma,
            projection=proj_id,
            fps=10,
        )
        if started:
            self.video_button.setEnabled(False)
            self.cancel_video_button.setEnabled(True)
            self._set_ui_status("loading", "Exporting video... This may take a while.")
            self._sync_action_states()
        else:
            self.video_button.setEnabled(True)
            self.cancel_video_button.setEnabled(False)
            self._set_ui_status("error", "Video export failed to start")
            self._sync_action_states()
    
    def on_video_progress(self, current, total):
        self._set_ui_status("loading", f"Exporting Video: Frame {current}/{total}...")
        self.export_info_label.setText(f"Export: frame {current}/{total}")

    def on_video_finished(self, path):
        self.video_button.setEnabled(True)
        self.cancel_video_button.setEnabled(False)
        self._set_ui_status("success", "Video Export Complete!")
        self._sync_action_states()
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def on_gamma_change(self, value):
        self.current_gamma = value / 10.0
        self.gamma_label.setText(f"Gamma: {self.current_gamma}")

    def run_process(self, silent: bool = False):
        bands = self._collect_selected_bands()
        if not bands:
            if not silent:
                missing = []
                if not self.red_drop_zone.text().strip():
                    missing.append("R")
                if not self.green_drop_zone.text().strip():
                    missing.append("G")
                if not self.blue_drop_zone.text().strip():
                    missing.append("B")
                if 0 < len(missing) < 3:
                    QMessageBox.information(self, "Info", f"Missing RGB channels: {', '.join(missing)}")
                else:
                    QMessageBox.information(self, "Info", "Please select bands or drag to RGB boxes.")
                self._set_ui_status("error", "Generate blocked: incomplete band selection")
            return

        proj_id = self.projection_combobox.currentData()
        if not silent:
            self._maybe_warn_fy3d_china_projection_risk(proj_id=proj_id)
        self.current_bands = bands.copy()
        self._state.selected_bands = bands.copy()
        self._state.gamma = self.current_gamma
        self._state.current_projection = proj_id

        preview_size = self._get_preview_output_size(max_side=1600)
        need_3d_texture = self.view_tabs.currentIndex() == 1
        self._last_render_request_signature = (
            self.current_frame_index,
            tuple(bands),
            proj_id,
            round(float(self.current_gamma), 3),
            preview_size,
            bool(need_3d_texture),
        )
        self._image_controller.generate_image(
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
        valid_band_names = self._available_band_names()
        r = self.red_drop_zone.text()
        g = self.green_drop_zone.text()
        b = self.blue_drop_zone.text()
        if (
            r and g and b and
            r in valid_band_names and
            g in valid_band_names and
            b in valid_band_names
        ):
            return [r, g, b]
        selected = self.band_list_widget.currentItem()
        if selected and selected.text() in valid_band_names:
            return [selected.text()]
        return []

    def _get_preview_output_size(self, max_side: int = 1600):
        """Estimate a fast preview output size from the 2D canvas size."""
        try:
            w = max(320, int(self.map_2d_canvas.canvas.width()))
            h = max(240, int(self.map_2d_canvas.canvas.height()))
        except Exception:
            w, h = 1200, 800

        scale = min(1.0, float(max_side) / float(max(w, h)))
        out_w = max(320, int(w * scale))
        out_h = max(240, int(h * scale))
        return (out_w, out_h)

    def on_data_ready(self, img, area_def):
        """Handle image data returned from background worker."""
        logger.debug(f"[MainWindow] Image ready: shape={img.shape}")
        self.render_info_label.setText(f"Render: {img.shape[1]}x{img.shape[0]}")

        # Cache image data for subsequent 3D updates
        self.cached_img = img

        # Try to get geographic extent
        h, w = img.shape[:2]
        logger.debug(f"[MainWindow] Detecting extent: w={w}, h={h}")

        # First try to determine extent based on predefined grid sizes
        grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
        if grid_proj is not None:
            self.cached_extent = PROJECTION_GRID_EXTENTS[grid_proj]
            logger.debug(f"[MainWindow] Grid proj '{grid_proj}': using extent {self.cached_extent}")
        else:
            # If not standard grid size, try to extract extent from area_def (for geostationary or other projections)
            self.cached_extent = get_geographic_extent(area_def)
            logger.debug(f"[MainWindow] Other: using geo extent {self.cached_extent}")

        # 1. Update 2D canvas first
        try:
            self.map_2d_canvas.update_image(img, area_def)
        except Exception as e:
            logger.exception(f"2D update failed: {e}")

        # 2. Then update 3D preview (if current tab is 3D and data is ready)
        self.update_3d_view()
        self._set_ui_status("success", "Preview updated")
    
    def on_opacity_change(self, value):
        """Update 3D overlay opacity."""
        self.opacity_label.setText(f"Overlay Opacity: {value}%")
        # If 3D tab is active, update 3D view
        self.update_3d_view()
    
    def update_3d_view(self):
        """Refresh the 3D globe texture preview."""
        if self.view_tabs.currentIndex() != 1:
            return
        if self.cached_img is None or not getattr(self.globe_3d_canvas, 'available', True):
            return

        try:
            alpha = self.opacity_slider.value() / 100.0
            proj_id = self.projection_combobox.currentData()

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

            self.globe_3d_canvas.update_texture(
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

            self._image_controller.generate_3d_texture(
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
        # Check if bands are selected
        r, g, b = self.red_drop_zone.text(), self.green_drop_zone.text(), self.blue_drop_zone.text()
        bands = []

        if r and g and b:
            bands = [r, g, b]
        elif self.band_list_widget.currentItem():
            bands = [self.band_list_widget.currentItem().text()]
        else:
            QMessageBox.information(self, "Info", "Please select bands first.")
            return

        # Get projection settings
        proj_id = self.projection_combobox.currentData()
        proj_name = self.projection_combobox.currentText()

        output_file = QFileDialog.getSaveFileName(
            self,
            "Export Image As",
            "",
            "PNG Image (*.png);;GeoTIFF (*.tif);;All Files (*.*)"
        )

        if not output_file[0]:
            return

        output_path = output_file[0]

        # Trigger export task
        self._set_ui_status("loading", f"Exporting to {proj_name}...")
        self.export_info_label.setText("Export: still image running")
        self._export_controller.export_still(
            output_path=output_path,
            bands=bands,
            gamma=self.current_gamma,
            projection=proj_id,
        )

    # ==========================================================================
    # Controller Slots - wired in __init__, bridge controllers to legacy UI
    # ==========================================================================

    def _on_image_ctrl_ready(self, img, extent, area_def):
        """Slot: ImageViewController finished generating a 2D image."""
        self.cached_img    = img
        self.cached_extent = extent
        # Delegate to existing rendering path
        self.on_data_ready(img, area_def)

    def _on_3d_texture_ctrl_ready(self, img, extent):
        """Slot: ImageViewController finished generating a 3D plate-carree texture."""
        self._state.img_3d    = img
        self._state.extent_3d = extent
        self._state.proj_3d = 'plate_carree_global'
        if self.view_tabs.currentIndex() != 1:
            return
        alpha = self.opacity_slider.value() / 100.0
        try:
            self.globe_3d_canvas.update_texture(img, extent=extent, alpha=alpha)
        except Exception as exc:
            logger.exception(f"[MainWindow] 3D texture update failed: {exc}")

    def _on_frame_loaded(self, index: int, total: int, time_str: str):
        """Slot: TimeSeriesController finished loading a frame."""
        self.current_frame_index = index
        self._state.current_frame_index = index
        self.time_label.setText(f"{time_str}\n[{index + 1}/{total}]")
        self.frame_info_label.setText(f"Frame: {index + 1}/{total}")
        self.header_meta_label.setText(f"Current time: {time_str} | total frames: {total}")

        # Update slider position without triggering another load
        self.time_slider.blockSignals(True)
        self.time_slider.setValue(index)
        self.time_slider.blockSignals(False)
        self.frame_index_spinbox.blockSignals(True)
        self.frame_index_spinbox.setRange(1, max(1, total))
        self.frame_index_spinbox.setValue(index + 1)
        self.frame_index_spinbox.blockSignals(False)

        # Update band list if needed
        self._update_band_list_from_manager()
        self._sync_action_states()

        bands = self._collect_selected_bands()
        if not bands:
            return

        proj_id = self.projection_combobox.currentData()
        preview_size = self._get_preview_output_size(max_side=1600)
        need_3d_texture = self.view_tabs.currentIndex() == 1
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
        self.export_info_label.setText("Export: still image done")
        QMessageBox.information(self, "Export Success", f"Saved to:\n{path}")

    def _on_video_ctrl_finished(self, path: str):
        """Slot: ExportController video export completed."""
        self.video_button.setEnabled(True)
        self.cancel_video_button.setEnabled(False)
        self._set_ui_status("success", "Video Export Complete!")
        self._sync_action_states()
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def _on_video_ctrl_error(self, message: str):
        """Slot: ExportController video export failed."""
        self.video_button.setEnabled(True)
        self.cancel_video_button.setEnabled(False)
        self._set_ui_status("error", f"Video export error: {message}")
        self.export_info_label.setText("Export: video failed")
        self._sync_action_states()
        QMessageBox.critical(self, "Video Export Error", f"Failed to export video:\n{message}")

    def _cancel_video_export(self):
        """Request cancellation of the running video export."""
        self._export_controller.cancel_video_export()
        self.cancel_video_button.setEnabled(False)
        self._set_ui_status("loading", "Cancelling video export...")
        self.export_info_label.setText("Export: cancelling...")
        self._sync_action_states()

    def closeEvent(self, event):
        """Stop background workers before window destruction."""
        try:
            self._image_controller.shutdown()
            self._timeseries_controller.shutdown()
            self._export_controller.shutdown()
        except Exception as exc:
            logger.exception(f"Controller shutdown failed: {exc}")
        super().closeEvent(event)





