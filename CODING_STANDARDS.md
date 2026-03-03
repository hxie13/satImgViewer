# Coding Standards for satImgViewer

## 1. Language Convention

- **All code comments and docstrings must be in English** for consistency and international collaboration
- UI labels and user-facing text can be in Chinese as needed

## 2. Docstring Style

Use **Google Style** docstrings:

```python
def process_image(self, bands: List[str], gamma: float = 1.0) -> Tuple[np.ndarray, Any]:
    """Generate image from specified bands.
    
    Args:
        bands: List of band canonical names (e.g., ['B01', 'B02', 'B03'])
        gamma: Gamma correction value (default: 1.0)
        
    Returns:
        Tuple of (image_array, area_definition)
        
    Raises:
        ValueError: If no data is loaded
        ProcessingError: If image generation fails
    """
```

## 3. Type Hints

- All public methods must have type hints
- Use `from __future__ import annotations` for forward references
- Use `Optional[X]` instead of `Union[X, None]`
- Use `|` operator for unions (Python 3.10+)

## 4. Import Ordering

```python
# 1. Standard library
import os
import logging
from typing import Dict, List

# 2. Third-party
import numpy as np
from PyQt6.QtWidgets import QWidget

# 3. Local modules
from core.config import get_satellite_config
from ui.canvas import GeoCanvas
```

## 5. Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Classes | PascalCase | `SatelliteImageManager` |
| Functions/Methods | snake_case | `process_image()` |
| Constants | UPPER_SNAKE_CASE | `PROJECTION_GRID_SHAPES` |
| Private attributes | _leading_underscore | `_driver`, `_is_loaded` |
| Module names | lowercase | `manager.py`, `geo_utils.py` |

## 6. Error Handling

- Catch specific exceptions, avoid bare `except:`
- Use custom exception hierarchy (`SatImgError` subclasses)
- Log exceptions with context before re-raising

```python
try:
    result = process_data()
except FileNotFoundError as e:
    logger.error(f"Data file not found: {file_path}")
    raise SatDataLoadError(f"Cannot load {file_path}") from e
except ValueError as e:
    logger.error(f"Invalid data format: {e}")
    raise ProcessingError("Data format validation failed") from e
```
