# satImgViewer Naming Conventions

This document defines the naming standards for the satImgViewer project to ensure consistency and readability across the codebase.

## 1. General Principles

- **Be descriptive**: Names should clearly indicate purpose
- **Be consistent**: Use the same pattern for similar concepts
- **Avoid abbreviations**: Except for well-known acronyms (e.g., `HTTP`, `URL`, `RGB`, `FY4A`)
- **Follow Python conventions**: PEP 8 compliance with project-specific extensions

## 2. Naming Patterns

### 2.1 Classes - PascalCase

```python
# ✅ Correct
class SatelliteImageManager:
class ImageViewController:
class BaseSatelliteDriver:
class FengYun3DDriver:
class ProcessingResult:

# ❌ Incorrect
class satellite_image_manager:  # snake_case
class imageViewController:      # camelCase
class Base_Driver:              # Mixed with underscore
```

**Special Cases:**
- Abstract base classes should start with `Base`: `BaseSatelliteDriver`, `BaseCompositor`
- Factory classes should end with `Factory`: `DriverFactory`, `RGBCompositorFactory`
- Exception classes should end with `Error`: `SatDataLoadError`, `ProjectionError`
- UI widget classes should describe their function: `GeoCanvas`, `BandDropZone`

### 2.2 Functions and Methods - snake_case

```python
# ✅ Correct
def process_image():
def get_satellite_coverage():
def scan_directory():
def _setup_logging():  # Private method

# ❌ Incorrect
def processImage():     # camelCase
def ProcessImage():     # PascalCase
```

**Naming Patterns by Purpose:**

| Pattern | Use For | Examples |
|---------|---------|----------|
| `get_*` | Retrieval without side effects | `get_metadata()`, `get_band_mapping()` |
| `set_*` | Setters with validation | `set_gamma()`, `set_projection()` |
| `is_*` / `has_*` | Boolean checks | `is_loaded`, `has_data()` |
| `can_*` | Capability checks | `can_load()`, `can_export()` |
| `create_*` / `build_*` | Factory methods | `create_driver()`, `build_dataset_map()` |
| `load_*` / `save_*` | I/O operations | `load_files()`, `save_image()` |
| `update_*` | Refresh/modify state | `update_image()`, `update_cache()` |
| `handle_*` / `on_*` | Event handlers | `on_slider_change()`, `handle_error()` |
| `validate_*` | Validation logic | `validate_file()`, `validate_extent()` |
| `_parse_*` / `_extract_*` | Internal parsing | `_parse_timestamp()`, `_extract_bands()` |

### 2.3 Variables and Attributes

#### Instance Variables

```python
# ✅ Correct - Private attributes (internal use)
self._driver: Optional[BaseSatelliteDriver] = None
self._time_groups: List[List[str]] = []
self._lock = threading.RLock()

# ✅ Correct - Public attributes (API surface)
self.config: Dict[str, Any] = {}
self.logger = logging.getLogger(__name__)

# ❌ Incorrect
self.driverType = None      # camelCase
self._Driver = None         # Leading underscore + PascalCase
```

#### Local Variables

```python
# ✅ Correct
file_paths: List[str] = []
band_count = len(bands)
is_valid = True

# ❌ Incorrect
filePaths = []      # camelCase
BandCount = 0       # PascalCase (looks like class)
```

#### Boolean Variables

```python
# ✅ Correct - Prefix with is_, has_, can_, should_, use_
is_loaded: bool = False
has_geolocation: bool = True
can_process: bool = True
use_caching: bool = True

# ❌ Incorrect
loaded = False      # Ambiguous (could be timestamp)
geolocation = True  # Ambiguous (could be the data itself)
```

#### Collections

```python
# ✅ Correct - Use plural names or *_list, *_dict, *_set suffixes
file_paths: List[str] = []
band_configs: Dict[str, BandConfig] = {}
unique_bands: Set[str] = set()

# ❌ Incorrect
file_path = []      # Singular for a list
band = {}           # Singular for a dict
```

### 2.4 Constants - UPPER_SNAKE_CASE

```python
# ✅ Correct
MAX_CACHE_SIZE = 100
DEFAULT_GAMMA = 1.0
SUPPORTED_FORMATS = ['.nc', '.hdf', '.h5']
PROJECTION_GRID_SHAPES = {
    (3600, 1800): 'plate_carree_global',
}

# ❌ Incorrect
MaxCacheSize = 100      # PascalCase
default_gamma = 1.0     # snake_case
```

### 2.5 Type Variables and Aliases

```python
# ✅ Correct
from typing import TypeVar

T = TypeVar('T')  # Single letter for generic
DriverType = TypeVar('DriverType', bound=BaseSatelliteDriver)

# Type aliases
BandMapping = Dict[str, str]
FileGroups = List[List[str]]
ExtentTuple = Tuple[float, float, float, float]

# ❌ Incorrect
typevar = TypeVar('typevar')  # lowercase
Band_Mapping = ...            # snake_case with uppercase
```

### 2.6 Enum Members - UPPER_SNAKE_CASE

```python
# ✅ Correct
class SatelliteType(Enum):
    FENGYUN_3D = "FY3D"
    FENGYUN_4A = "FY4A"
    HIMAWARI_8 = "H08"
    UNKNOWN = "UNKNOWN"

class ProcessingStage(Enum):
    INITIALIZED = "initialized"
    LOADING = "loading"
    PROCESSING = "processing"
    COMPLETED = "completed"
```

### 2.7 UI Widget Names (MainWindow attributes)

```python
# ✅ Correct - Descriptive, consistent suffixes
self.load_button: QPushButton
self.export_button: QPushButton
self.header_title_label: QLabel
self.gamma_slider: QSlider
self.band_list_widget: DraggableList
self.drop_red_channel: BandDropZone
self.frame_index_spinbox: QSpinBox
self.main_splitter: QSplitter
self.canvas_2d: GeoCanvas
self.canvas_3d: Globe3DCanvas

# ❌ Incorrect
self.btn_load        # Abbreviated
self.lbl_title       # Abbreviated
self.slider          # Not descriptive
self.drop_r          # Too abbreviated
```

**UI Naming Suffixes:**

| Widget Type | Suffix | Example |
|-------------|--------|---------|
| QPushButton | `_button` | `load_button`, `export_button` |
| QLabel | `_label` | `status_label`, `header_label` |
| QSlider | `_slider` | `gamma_slider`, `opacity_slider` |
| QComboBox | `_combobox` | `projection_combobox` |
| QListWidget | `_list` / `_list_widget` | `band_list`, `file_list_widget` |
| QLineEdit | `_input` / `_field` | `search_input`, `path_field` |
| QSpinBox | `_spinbox` | `frame_spinbox`, `width_spinbox` |
| QTimer | `_timer` | `debounce_timer`, `refresh_timer` |
| Custom Widgets | Descriptive name | `geo_canvas`, `band_drop_zone` |

### 2.8 Signal Names (Qt)

```python
# ✅ Correct - Past tense for completed actions, present for ongoing
image_ready = pyqtSignal(object, object, object)      # Completed
texture_3d_ready = pyqtSignal(object, object)
frame_loaded = pyqtSignal(str)
frame_loading = pyqtSignal()                         # Ongoing
export_finished = pyqtSignal(str)
export_progress = pyqtSignal(int, int)
error_occurred = pyqtSignal(str)                     # More descriptive than just 'error'

# ❌ Incorrect
image = pyqtSignal(...)         # Not descriptive
do_load = pyqtSignal(...)       # Imperative (command-like)
```

### 2.9 Private vs Public Naming

```python
class SatelliteImageManager:
    # Public API (no underscore prefix)
    def process_image(self, ...): ...
    def export_image(self, ...): ...
    
    # Internal implementation (single underscore prefix)
    def _setup_logging(self): ...
    def _infer_driver_type(self): ...
    
    # Name mangling for inheritance protection (double underscore)
    __internal_cache = {}
```

## 3. Special Conventions

### 3.1 Satellite-Specific Terms

```python
# Standard abbreviations (allowed)
FY4A, FY4B          # Fengyun-4A/B
FY3D                # Fengyun-3D
H08, H09            # Himawari-8/9
MERSI, AGRI, AHI    # Sensor names
L1, L2              # Product levels (Level-1, Level-2)
GEO                 # Geolocation files

# Use these consistently
band_mapping        # Not band_map (unless dict context is clear)
file_paths          # Not filenames (use paths to indicate they include directories)
file_groups         # Groups of files by timestamp
time_series         # Not timeseries or timeSeries
```

### 3.2 Geospatial Terms

```python
# Standard terms
area_def            # AreaDefinition (pyresample convention)
area_extent         # (west, south, east, north) or (xmin, ymin, xmax, ymax)
geo_extent          # Geographic extent in degrees
proj_dict           # Projection dictionary
crs                 # Coordinate Reference System
lon, lat            # Longitude, latitude (not lng, long)
lons, lats          # Arrays of coordinates
```

### 3.3 Image Processing Terms

```python
# Standard terms
img_data            # Image data array
img_array           # Alternative
raw_data            # Unprocessed data
calibrated_data     # After calibration
normalized_data     # After normalization
composite           # RGB composite
channels            # Color channels (R, G, B)
bands               # Spectral bands (B01, B02, etc.)
gamma               # Gamma correction value
```

## 4. Migration Guide

### Deprecating Old Names

When renaming public API elements, maintain backward compatibility:

```python
class SatelliteImageManager:
    @property
    def time_groups(self) -> List[List[str]]:
        """Get time-sorted file groups."""
        return self._time_groups.copy()
    
    # Backward compatibility alias (deprecated)
    @property
    def file_groups(self) -> List[List[str]]:
        """Deprecated: Use time_groups instead."""
        import warnings
        warnings.warn(
            "file_groups is deprecated, use time_groups",
            DeprecationWarning,
            stacklevel=2
        )
        return self.time_groups
```

## 5. Checklist for Code Review

Before submitting code, verify:

- [ ] Classes use PascalCase
- [ ] Functions/methods use snake_case
- [ ] Constants use UPPER_SNAKE_CASE
- [ ] Private attributes use `_` prefix
- [ ] Boolean variables use `is_`, `has_`, `can_` prefixes
- [ ] Collections use plural names
- [ ] UI widgets use descriptive names with appropriate suffixes
- [ ] No single-letter variable names (except in short loops)
- [ ] No abbreviations except standard ones (FY4A, GEO, etc.)
