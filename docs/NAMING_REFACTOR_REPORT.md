# Naming Convention Refactoring Report

**Date:** 2026-03-03  
**Scope:** UI components, controllers, and core modules  
**Standard:** NAMING_CONVENTIONS.md

---

## Summary

The naming convention refactoring has been successfully applied to the satImgViewer codebase. This report documents all changes made to ensure consistency with the established naming standards.

---

## Changes Made

### 1. ui/main_window.py

#### Manager Instance (Private)
```python
# Before
self.manager = SatelliteImageManager()

# After
self._manager = SatelliteImageManager()
```

#### Controllers (Full Names)
```python
# Before
self._img_ctrl  = ImageViewController(self.manager, self._state, parent=self)
self._ts_ctrl   = TimeSeriesController(self.manager, self._state, parent=self)
self._exp_ctrl  = ExportController(self.manager, self._state, parent=self)

# After
self._image_controller = ImageViewController(self._manager, self._state, parent=self)
self._timeseries_controller = TimeSeriesController(self._manager, self._state, parent=self)
self._export_controller = ExportController(self._manager, self._state, parent=self)
```

#### UI Widgets (Descriptive Names with Suffixes)

**Buttons:**
```python
# Before
self.btn_load = QPushButton("⊞  Load Folder")
self.btn_clear = QPushButton("↺  Reset")
self.btn_generate = QPushButton("▶  Generate")
self.btn_export = QPushButton("↗  Export")
self.btn_video = QPushButton("▤  Video")
self.btn_cancel_video = QPushButton("⊗  Cancel")
self.btn_prev = QPushButton("◀  Prev")
self.btn_next = QPushButton("Next  ▶")
self.btn_jump_frame = QPushButton("Go")
self.btn_clear_r, self.btn_clear_g, self.btn_clear_b

# After
self.load_button = QPushButton("⊞  Load Folder")
self.clear_button = QPushButton("↺  Reset")
self.generate_button = QPushButton("▶  Generate")
self.export_button = QPushButton("↗  Export")
self.video_button = QPushButton("▤  Video")
self.cancel_video_button = QPushButton("⊗  Cancel")
self.previous_button = QPushButton("◀  Prev")
self.next_button = QPushButton("Next  ▶")
self.jump_frame_button = QPushButton("Go")
self.clear_red_button, self.clear_green_button, self.clear_blue_button
```

**Labels:**
```python
# Before
self.lbl_header_title = QLabel("Satellite Image Analyst Console")
self.lbl_header_meta = QLabel("No dataset loaded")
self.lbl_gamma = QLabel("Gamma: 1.0")
self.lbl_opacity = QLabel("Overlay Opacity: 100%")
self.lbl_view_status = QLabel("View: No image yet")
self.lbl_render_info = QLabel("Render: --")
self.lbl_time = QLabel("Time: N/A")
self.lbl_frame_info = QLabel("Frame: --/--")
self.lbl_preview_info = QLabel("Preview: Idle")
self.lbl_export_info = QLabel("Export: idle")

# After
self.header_title_label = QLabel("Satellite Image Analyst Console")
self.header_meta_label = QLabel("No dataset loaded")
self.gamma_label = QLabel("Gamma: 1.0")
self.opacity_label = QLabel("Overlay Opacity: 100%")
self.view_status_label = QLabel("View: No image yet")
self.render_info_label = QLabel("Render: --")
self.time_label = QLabel("Time: N/A")
self.frame_info_label = QLabel("Frame: --/--")
self.preview_info_label = QLabel("Preview: Idle")
self.export_info_label = QLabel("Export: idle")
```

**ComboBoxes:**
```python
# Before
self.combo_proj = QComboBox()

# After
self.projection_combobox = QComboBox()
```

**Sliders:**
```python
# Before
self.slider_gamma = QSlider(Qt.Orientation.Horizontal)
self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
self.slider_time = QSlider(Qt.Orientation.Horizontal)

# After
self.gamma_slider = QSlider(Qt.Orientation.Horizontal)
self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
self.time_slider = QSlider(Qt.Orientation.Horizontal)
```

**SpinBoxes:**
```python
# Before
self.spin_frame_index = QSpinBox()

# After
self.frame_index_spinbox = QSpinBox()
```

**Canvases:**
```python
# Before
self.canvas_2d = GeoCanvas()
self.canvas_3d = Globe3DCanvas()

# After
self.map_2d_canvas = GeoCanvas()
self.globe_3d_canvas = Globe3DCanvas()
```

**Drop Zones:**
```python
# Before
self.drop_r, self.drop_g, self.drop_b

# After
self.red_drop_zone, self.green_drop_zone, self.blue_drop_zone
```

**Other Widgets:**
```python
# Before
self.band_list = DraggableList(density="comfortable")
self.tabs = QTabWidget()
self.splitter = QSplitter(Qt.Orientation.Horizontal)

# After
self.band_list_widget = DraggableList(density="comfortable")
self.view_tabs = QTabWidget()
self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
```

---

## Naming Standards Applied

### UI Widget Suffixes

| Widget Type | Suffix | Example |
|-------------|--------|---------|
| QPushButton | `_button` | `load_button`, `export_button` |
| QLabel | `_label` | `status_label`, `header_label` |
| QSlider | `_slider` | `gamma_slider`, `opacity_slider` |
| QComboBox | `_combobox` | `projection_combobox` |
| QSpinBox | `_spinbox` | `frame_index_spinbox` |
| QListWidget | `_list_widget` | `band_list_widget` |
| QTabWidget | `_tabs` | `view_tabs` |
| QSplitter | `_splitter` | `main_splitter` |
| Custom Canvas | `_canvas` | `map_2d_canvas`, `globe_3d_canvas` |
| DropZone | `_drop_zone` | `red_drop_zone` |

### Private vs Public Attributes

- **Private attributes** (internal use only): `_` prefix
  - `self._manager`
  - `self._state`
  - `self._image_controller`

- **Public attributes** (part of API surface): no prefix
  - `self.load_button`
  - `self.gamma_label`

---

## Files Reviewed (No Changes Needed)

The following files were reviewed and found to already comply with naming conventions:

1. **core/drivers/base.py** - Consistent use of PascalCase for classes, snake_case for methods
2. **core/drivers/fengyun3d.py** - Proper private attribute naming (`_satpy`, `_dataset_names`)
3. **core/manager.py** - Clean separation of public/private API
4. **core/config.py** - Constants use UPPER_SNAKE_CASE
5. **ui/widgets.py** - Class names follow PascalCase
6. **utils/workers.py** - Worker class names are descriptive

---

## Benefits of This Refactoring

1. **Improved Readability**: Descriptive names make code self-documenting
2. **Consistency**: Same pattern used throughout the codebase
3. **Maintainability**: Easier to understand and modify code
4. **IDE Support**: Better autocomplete due to consistent suffixes
5. **Reduced Cognitive Load**: No need to remember abbreviations

---

## Verification

All changes have been verified to:
- Maintain functionality (no logic changes)
- Follow the NAMING_CONVENTIONS.md standard
- Preserve backward compatibility where applicable
- Pass existing type checks

---

## Migration for Downstream Code

If you have code that references the old names, update as follows:

```python
# Old names (deprecated)
main_window.btn_load
main_window.lbl_time
main_window.canvas_2d

# New names
main_window.load_button
main_window.time_label
main_window.map_2d_canvas
```

---

**Refactoring Completed:** 2026-03-03  
**Next Review:** On major UI changes
