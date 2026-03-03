# Performance Optimization Guide

## 1. Image Data Processing

### Current Issue: NaN Pixel Detection
Location: `ui/canvas.py` lines 147-171

The current implementation checks every pixel individually:
```python
# Current (inefficient for large images)
nan_pixels = np.sum(np.isnan(img_data))
black_pixels = np.sum((img_data < 0.01).all(axis=-1))
```

### Recommended Optimization
```python
# Optimized version using vectorized operations
def _validate_image_data(img_data: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Validate and clean image data efficiently.
    
    Uses sampling for large images to avoid performance degradation.
    """
    if img_data.size > 50_000_000:  # > 50M pixels (e.g., 8K x 6K)
        # Sample every Nth pixel for validation
        sample_step = max(1, int(np.sqrt(img_data.size / 10_000_000)))
        sampled = img_data[::sample_step, ::sample_step]
        invalid_ratio = np.mean(np.isnan(sampled) | (sampled < threshold))
    else:
        # Full validation for smaller images
        if img_data.ndim == 3:
            valid_mask = (img_data > threshold).any(axis=-1)
        else:
            valid_mask = img_data > threshold
        invalid_ratio = 1.0 - (np.sum(valid_mask) / valid_mask.size)
    
    if invalid_ratio > 0.1:
        img_data = img_data.copy()
        if img_data.ndim == 3:
            valid_mask = (img_data > threshold).any(axis=-1)
        else:
            valid_mask = img_data > threshold
        img_data[~valid_mask] = np.nan
    
    return img_data
```

## 2. Geolocation File Loading

### Current Issue: Synchronous HDF5 Loading
Location: `core/drivers/fengyun3d.py` lines 782-839

Loading GEO files synchronously blocks the UI thread.

### Recommended Optimization
```python
from concurrent.futures import ThreadPoolExecutor
import functools

class FengYun3DDriver(BasePolarDriver):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self._geo_executor = ThreadPoolExecutor(max_workers=1)
        self._geo_future = None
    
    def _load_geo_file_async(self, geo_file: str) -> None:
        """Start async loading of geolocation data."""
        self._geo_future = self._geo_executor.submit(
            self._load_geo_file_sync, geo_file
        )
    
    def _get_geolocation_from_geo_file(self) -> Tuple[Optional[np.ndarray], ...]:
        """Get geolocation, waiting for async load if needed."""
        if self._geo_future and not self._geo_future.done():
            try:
                self._geo_future.result(timeout=5.0)  # Wait max 5s
            except TimeoutError:
                logger.warning("GEO file loading timeout")
                return None, None
        return self._swath_lons, self._swath_lats
```

## 3. Caching Strategy Improvements

### Band Mapping Cache
Location: `core/drivers/fengyun3d.py` lines 368-402

Current implementation rebuilds dataset map on every load:
```python
# Current: Conditional rebuild
if used_reader != self._loaded_reader:
    self._build_dataset_map()
    self._loaded_reader = used_reader
```

Recommended: Add persistent disk cache for band mappings:
```python
import json
import hashlib
from pathlib import Path

class BandMappingCache:
    """Persistent cache for satellite band mappings."""
    
    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
    
    def _get_cache_key(self, reader: str, file_sample: str) -> str:
        """Generate cache key from reader and file."""
        content = f"{reader}:{file_sample}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, reader: str, file_sample: str) -> Optional[Dict]:
        cache_file = self.cache_dir / f"{self._get_cache_key(reader, file_sample)}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return None
    
    def put(self, reader: str, file_sample: str, mapping: Dict) -> None:
        cache_file = self.cache_dir / f"{self._get_cache_key(reader, file_sample)}.json"
        with open(cache_file, 'w') as f:
            json.dump(mapping, f)
```

## 4. Memory Management

### Large Array Handling
For large satellite images (e.g., 250m resolution FY3D data):

```python
import gc
import weakref

class MemoryEfficientLoader:
    """Context manager for memory-efficient image loading."""
    
    def __enter__(self):
        gc.collect()  # Force cleanup before loading
        return self
    
    def __exit__(self, *args):
        gc.collect()
    
    @staticmethod
    def chunk_process(data: np.ndarray, chunk_size: int = 1024):
        """Process large arrays in chunks to reduce memory pressure."""
        h, w = data.shape[:2]
        for y in range(0, h, chunk_size):
            y_end = min(y + chunk_size, h)
            for x in range(0, w, chunk_size):
                x_end = min(x + chunk_size, w)
                yield data[y:y_end, x:x_end]
```

## 5. Profiling Guidelines

### Enable Performance Logging
```python
# In your main.py or configuration
import logging

# Set up performance logging
perf_logger = logging.getLogger('satimg.perf')
perf_logger.setLevel(logging.DEBUG)

# Usage in code
import time
from functools import wraps

def perf_timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        perf_logger.debug(f"{func.__name__}: {elapsed:.1f}ms")
        return result
    return wrapper
```
