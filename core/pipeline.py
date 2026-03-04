"""
Image Processing Pipeline

Memory-efficient pipeline with Dask-based lazy computation and chunked processing.
Provides on-demand area resampling to avoid generating full-resolution intermediates.
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import dask.array as da

logger = logging.getLogger(__name__)


class ProcessingStage(Enum):
    """Pipeline processing stages."""
    LOAD = "load"
    RESAMPLE = "resample"
    CROP = "crop"
    CALIBRATE = "calibrate"
    ENHANCE = "enhance"
    COMPOSITE = "composite"
    OUTPUT = "output"


@dataclass
class PipelineConfig:
    """Configuration for the processing pipeline."""
    # Target output settings
    target_area: Optional[Any] = None  # Pyresample AreaDefinition
    output_shape: Optional[Tuple[int, int]] = None  # (height, width)

    # Processing options
    resample_method: str = "nearest"
    radius_of_influence: int = 50000  # meters
    calibration: bool = False
    calibration_params: Dict = field(default_factory=dict)

    # Enhancement options
    gamma: float = 1.0
    contrast_stretch: Optional[Tuple[float, float]] = None  # (low, high) percentiles

    # Memory management
    chunk_size: int = 1024  # Chunk size for Dask arrays
    dtype: np.dtype = np.float32

    # Output format
    output_range: Tuple[float, float] = (0.0, 1.0)


class BasePipelineNode(ABC):
    """Abstract base class for pipeline processing nodes."""

    @abstractmethod
    def process(self, data: Any, config: PipelineConfig) -> Any:
        """Process data and return result."""
        pass

    @abstractmethod
    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Estimate memory usage in bytes."""
        pass


class DaskChunkedNode(BasePipelineNode):
    """
    Wrapper for Dask-based chunked processing.

    Ensures data remains as Dask arrays until final compute() call.
    """

    def __init__(self, processor: Callable):
        """
        Initialize node with processing function.

        Args:
            processor: Function that takes (dask_array, config) and returns dask_array
        """
        self.processor = processor

    def process(self, data: Any, config: PipelineConfig) -> Any:
        """Apply processing via Dask."""
        if isinstance(data, np.ndarray):
            # Convert numpy to dask
            chunks = self._compute_chunks(data.shape, config.chunk_size)
            data = da.from_array(data, chunks=chunks)

        return self.processor(data, config)

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Estimate memory as data_size * 2 (input + output)."""
        size = np.prod(data_shape) * config.dtype().itemsize
        return int(size * 2)

    def _compute_chunks(self, shape: Tuple, chunk_size: int) -> Tuple:
        """Compute Dask chunk tuple from shape."""
        chunks = []
        for dim in shape:
            n_chunks = (dim + chunk_size - 1) // chunk_size
            chunk_list = [chunk_size] * (n_chunks - 1)
            chunk_list.append(dim - chunk_size * (n_chunks - 1))
            chunks.append(tuple(chunk_list) if chunk_list else (dim,))
        return tuple(chunks)


class LoadNode(BasePipelineNode):
    """Node for lazy loading satellite data."""

    def __init__(self, scene_loader):
        """
        Initialize with scene loader function.

        Args:
            scene_loader: Function that loads dataset and returns Dask array
        """
        self.scene_loader = scene_loader

    def process(self, band_names: List[str], config: PipelineConfig) -> Dict[str, Any]:
        """
        Load bands lazily.

        Returns:
            Dict mapping band_name -> Dask array
        """
        result = {}
        for band in band_names:
            try:
                arr = self.scene_loader(band)
                if isinstance(arr, np.ndarray):
                    chunks = self._compute_chunks(arr.shape, config.chunk_size)
                    arr = da.from_array(arr, chunks=chunks)
                result[band] = arr
            except Exception as e:
                logger.error(f"Failed to load band {band}: {e}")
                raise
        return result

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Estimate based on full array size."""
        return int(np.prod(data_shape) * config.dtype.itemsize * len(data_shape))

    def _compute_chunks(self, shape: Tuple, chunk_size: int) -> Tuple:
        """Compute Dask chunk tuple."""
        chunks = []
        for dim in shape:
            n_chunks = max(1, (dim + chunk_size - 1) // chunk_size)
            base_chunk = dim // n_chunks
            remainder = dim % n_chunks
            chunk_list = [base_chunk + 1] * remainder + [base_chunk] * (n_chunks - remainder)
            if not chunk_list:
                chunk_list = [dim]
            chunks.append(tuple(chunk_list))
        return tuple(chunks)


class ResampleNode(BasePipelineNode):
    """
    Node for area-aware resampling.

    Critical: Resamples directly to target_area without intermediate global products.
    """

    def __init__(self, resampler_func: Callable):
        """
        Initialize with resampler function.

        Args:
            resampler_func: Function(dsa_array, target_area, method) -> Dask array
        """
        self.resampler_func = resampler_func

    def process(self, data: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
        """
        Resample all bands to target area.

        Args:
            data: Dict of band_name -> Dask array
            config: PipelineConfig with target_area

        Returns:
            Dict of resampled Dask arrays
        """
        if config.target_area is None:
            logger.warning("No target_area specified, skipping resampling")
            return data

        result = {}
        for band, arr in data.items():
            try:
                # Resample directly to target area
                resampled = self.resampler_func(arr, config.target_area, config.resample_method)
                result[band] = resampled
            except Exception as e:
                logger.error(f"Resampling failed for {band}: {e}")
                # Fallback: return original
                result[band] = arr
        return result

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Estimate based on target area size."""
        if config.output_shape:
            target_size = config.output_shape[0] * config.output_shape[1]
        else:
            # Estimate from target_area
            target_size = 2000 * 2000  # Default estimate
        return int(target_size * config.dtype.itemsize)


class CropNode(BasePipelineNode):
    """Node for geographic cropping."""

    def __init__(self, crop_func: Callable):
        """
        Initialize with crop function.

        Args:
            crop_func: Function(arr, lat_array, lon_array, bounds) -> cropped array
        """
        self.crop_func = crop_func

    def process(self, data: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
        """
        Crop data to geographic bounds.

        Args:
            data: Dict of band_name -> Dask array
            config: PipelineConfig with crop_bounds

        Returns:
            Dict of cropped Dask arrays
        """
        crop_bounds = getattr(config, 'crop_bounds', None)
        if crop_bounds is None:
            return data

        result = {}
        for band, arr in data.items():
            try:
                cropped = self.crop_func(arr, crop_bounds)
                result[band] = cropped
            except Exception as e:
                logger.warning(f"Crop failed for {band}: {e}")
                result[band] = arr
        return result

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Estimate based on crop region size."""
        crop_factor = getattr(config, 'crop_factor', 0.25)  # Default 25% of original
        original_size = np.prod(data_shape) * config.dtype.itemsize
        return int(original_size * crop_factor)


class CalibrateNode(BasePipelineNode):
    """Node for radiometric calibration."""

    def __init__(self, calibrate_func: Callable):
        """Initialize with calibration function."""
        self.calibrate_func = calibrate_func

    def process(self, data: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
        """Apply calibration to each band."""
        if not config.calibration:
            return data

        result = {}
        for band, arr in data.items():
            try:
                params = config.calibration_params.get(band, {})
                calibrated = self.calibrate_func(arr, **params)
                result[band] = calibrated
            except Exception as e:
                logger.warning(f"Calibration failed for {band}: {e}")
                result[band] = arr
        return result

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Calibration doesn't significantly change memory."""
        return np.prod(data_shape) * config.dtype.itemsize


class NormalizeNode(BasePipelineNode):
    """Node for contrast normalization."""

    def __init__(self, low_percent: float = 2.0, high_percent: float = 98.0):
        """
        Initialize normalization.

        Args:
            low_percent: Lower percentile for stretch
            high_percent: Upper percentile for stretch
        """
        self.low_percent = low_percent
        self.high_percent = high_percent

    def _normalize_dask(self, arr: da.Array, low: float, high: float) -> da.Array:
        """Apply percentile normalization to Dask array.

        NOTE [P1-3]: The .compute() call below materialises the entire Dask
        graph at this node, breaking lazy evaluation.  A proper fix is to use
        dask.array.percentile() (available in recent Dask versions) so the
        percentile computation stays in the graph and is fused with downstream
        operations.  Tracked as: TODO — replace arr.compute() with
        da.percentile(arr, [low, high]) once minimum Dask version is confirmed.
        """
        try:
            # Compute percentiles using numpy (triggers computation for this chunk)
            arr_np = arr.compute()

            # Debug: print statistics
            arr_min = np.nanmin(arr_np)
            arr_max = np.nanmax(arr_np)
            nan_count = np.sum(np.isnan(arr_np))
            logger.debug(f"[Normalize] arr stats: min={arr_min:.4f}, max={arr_max:.4f}, NaN count={nan_count}")

            # Check if data is all NaN
            if nan_count == arr_np.size:
                logger.warning(f"[Normalize] All pixels are NaN! Returning zeros")
                return da.zeros_like(arr, dtype=arr.dtype)

            # Replace NaN with 0 for percentile calculation
            arr_clean = np.where(np.isnan(arr_np), 0, arr_np)

            p_low, p_high = np.percentile(arr_clean, [low, high])
            logger.debug(f"Percentiles: p{low}={p_low:.4f}, p{high}={p_high:.4f}")

            # Handle edge case where p_low == p_high
            if p_high <= p_low:
                logger.warning(f"Normalization: p_high ({p_high}) <= p_low ({p_low}), skipping stretch")
                return da.from_array(np.clip(arr_clean, 0, 1))

            # Apply stretch
            arr_normalized = (arr_clean - p_low) / (p_high - p_low)
            arr_normalized = np.clip(arr_normalized, 0, 1)

            # Preserve NaN where original was NaN
            arr_normalized = np.where(np.isnan(arr_np), np.nan, arr_normalized)

            return da.from_array(arr_normalized, chunks=arr.chunks)
        except Exception as e:
            logger.warning(f"Normalization failed: {e}")
            import traceback
            traceback.print_exc()
            return arr

    def process(self, data: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
        """Apply normalization to each band."""
        if config.contrast_stretch:
            low, high = config.contrast_stretch
        else:
            low, high = self.low_percent, self.high_percent

        result = {}
        for band, arr in data.items():
            try:
                normalized = self._normalize_dask(arr, low, high)
                result[band] = normalized
            except Exception as e:
                logger.warning(f"Normalization failed for {band}: {e}")
                result[band] = arr
        return result

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """Normalization needs extra buffer."""
        return int(np.prod(data_shape) * config.dtype.itemsize * 2)


class CompositeNode(BasePipelineNode):
    """Node for RGB composition."""

    def __init__(self, band_order: List[str] = None):
        """
        Initialize compositor.

        Args:
            band_order: Order of bands [R, G, B]
        """
        self.band_order = band_order or ['R', 'G', 'B']

    def process(self, data: Dict[str, Any], config: PipelineConfig) -> da.Array:
        """
        Stack bands into RGB image.

        Args:
            data: Dict of band_name -> Dask array
            config: PipelineConfig

        Returns:
            Dask RGB array (H, W, 3)
        """
        bands = []
        for band_name in self.band_order:
            if band_name in data:
                arr = data[band_name]
                # Ensure 2D
                if arr.ndim > 2:
                    arr = arr.squeeze()
                bands.append(arr)
            else:
                logger.warning(f"Band {band_name} not found, using zeros")
                # Get shape from first available band
                first_arr = next(iter(data.values())) if data else (1000, 1000)
                shape = first_arr.shape[:2] if first_arr.ndim >= 2 else (1000, 1000)
                bands.append(da.zeros(shape, dtype=config.dtype))

        # Stack along channel dimension
        rgb = da.stack(bands, axis=-1)

        # Apply gamma correction
        if config.gamma != 1.0:
            rgb = da.pow(rgb, 1.0 / config.gamma)

        # Clip to output range
        rgb = da.clip(rgb, config.output_range[0], config.output_range[1])

        return rgb

    def estimate_memory(self, data_shape: Tuple, config: PipelineConfig) -> int:
        """RGB image is 3x single band."""
        single_band = np.prod(data_shape[:2]) * config.dtype.itemsize
        return int(single_band * 3)


class ImageProcessingPipeline:
    """
    Memory-efficient image processing pipeline with Dask support.

    Key features:
    - Lazy evaluation: Data remains as Dask arrays until compute()
    - Chunked processing: Configurable chunk sizes for memory control
    - Area-aware resampling: Direct resample to target area
    - Pipeline nodes: Modular processing stages

    Usage:
        pipeline = ImageProcessingPipeline()
        pipeline.load(scene_loader_func)
        pipeline.resample(target_area)
        pipeline.composite(['R', 'G', 'B'])
        pipeline.compute()  # Only now is actual computation triggered
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        Initialize pipeline.

        Args:
            config: Optional PipelineConfig
        """
        self.config = config or PipelineConfig()
        self._nodes: List[Tuple[str, BasePipelineNode]] = []
        self._data: Optional[Any] = None
        self._computed: bool = False
        self._result: Optional[Any] = None
        self._is_dask: bool = False

        # Statistics
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._memory_stats: Dict[str, int] = {}

    def add_node(self, name: str, node: BasePipelineNode) -> 'ImageProcessingPipeline':
        """
        Add processing node to pipeline.

        Args:
            name: Node name for debugging
            node: BasePipelineNode instance

        Returns:
            Self for chaining
        """
        self._nodes.append((name, node))
        return self

    def load(self, scene_loader: Callable[[str], np.ndarray],
             band_names: List[str]) -> 'ImageProcessingPipeline':
        """
        Add loading node.

        Args:
            scene_loader: Function that loads a band and returns numpy/Dask array
            band_names: List of band names to load

        Returns:
            Self for chaining
        """
        def loader_func(bands: List[str], config: PipelineConfig) -> Dict[str, Any]:
            result = {}
            for band in bands:
                try:
                    arr = scene_loader(band)
                    if isinstance(arr, np.ndarray):
                        chunks = self._compute_chunks(arr.shape, config.chunk_size)
                        arr = da.from_array(arr, chunks=chunks)
                    result[band] = arr
                except Exception as e:
                    logger.error(f"Loading failed for {band}: {e}")
                    raise
            return result

        node = DaskChunkedNode(loader_func)
        self.add_node("load", node)

        # Store band names for loading
        self._band_names = band_names

        return self

    def resample(self, target_area: Any,
                 resample_method: str = "nearest") -> 'ImageProcessingPipeline':
        """
        Add resampling node.

        Args:
            target_area: Pyresample AreaDefinition
            resample_method: Resampling method

        Returns:
            Self for chaining
        """
        def resampler_func(arr: da.Array, area: Any, method: str) -> da.Array:
            """Resample Dask array to target area."""
            try:
                from pyresample import geometry

                # Create AreaDefinition from source if needed
                if hasattr(arr, 'attrs') and hasattr(arr.attrs, 'area'):
                    source_area = arr.attrs.area
                else:
                    # Use shape to estimate
                    h, w = arr.shape[:2]
                    source_area = geometry.AreaDefinition(
                        'source', 'Source', 'geos',
                        {'proj': 'geos', 'lon_0': 105, 'lat_0': 0, 'h': 35785831},
                        w, h, (-5500000, -5500000, 5500000, 5500000)
                    )

                # Try different resampling approaches based on available classes
                arr_np = arr.compute()

                # Check for NaN in source data
                has_nan = np.any(np.isnan(arr_np))
                logger.debug(f"Resampling: source has NaN: {has_nan}")

                # Method 1: Try BilinearResampler (newer pyresample)
                try:
                    from pyresample import BilinearResampler
                    resampler = BilinearResampler(source_area, area, radius_of_influence=50000)
                    resampled = resampler.resample(arr_np)
                except ImportError:
                    # Method 2: Try KDTree for nearest neighbor
                    try:
                        from pyresample import KDTree
                        lons, lats = source_area.get_lonlats()
                        valid_mask = np.isfinite(lons) & np.isfinite(lats)

                        # Also check source data validity
                        if has_nan:
                            data_valid_mask = np.isfinite(arr_np)
                            combined_mask = valid_mask & data_valid_mask
                        else:
                            combined_mask = valid_mask

                        src_coords = np.column_stack([lons[combined_mask], lats[combined_mask]])
                        src_data = arr_np[combined_mask]

                        t_lons, t_lats = area.get_lonlats()

                        # Create full output array with NaN
                        resampled = np.full(t_lons.shape, np.nan, dtype=arr_np.dtype)

                        if len(src_data) > 0:
                            tgt_coords = np.column_stack([t_lons.ravel(), t_lats.ravel()])

                            from scipy.spatial import cKDTree
                            tree = cKDTree(src_coords)
                            _, indices = tree.query(tgt_coords, k=1, workers=-1)
                            valid_tgt = np.arange(t_lons.size)
                            resampled.flat[valid_tgt] = src_data[indices]

                    except ImportError:
                        # Method 3: Simple nearest neighbor with scipy
                        from scipy.spatial import cKDTree
                        lons, lats = source_area.get_lonlats()
                        valid_mask = np.isfinite(lons) & np.isfinite(lats)

                        if has_nan:
                            data_valid_mask = np.isfinite(arr_np)
                            combined_mask = valid_mask & data_valid_mask
                        else:
                            combined_mask = valid_mask

                        src_coords = np.column_stack([lons[combined_mask], lats[combined_mask]])
                        src_data = arr_np[combined_mask]

                        t_lons, t_lats = area.get_lonlats()
                        resampled = np.full(t_lons.shape, np.nan, dtype=arr_np.dtype)

                        if len(src_data) > 0:
                            tgt_coords = np.column_stack([t_lons.ravel(), t_lats.ravel()])

                            tree = cKDTree(src_coords)
                            _, indices = tree.query(tgt_coords, k=1, workers=-1)
                            valid_tgt = np.arange(t_lons.size)
                            resampled.flat[valid_tgt] = src_data[indices]

                logger.debug(f"Resampled shape: {resampled.shape}, has NaN: {np.any(np.isnan(resampled))}")

                # Convert back to Dask
                chunks = self._compute_chunks(resampled.shape, self.config.chunk_size)
                return da.from_array(resampled, chunks=chunks)

            except Exception as e:
                logger.warning(f"Resampling failed: {e}, returning original")
                import traceback
                traceback.print_exc()
                return arr

        self.config.target_area = target_area
        self.config.resample_method = resample_method

        node = ResampleNode(resampler_func)
        self.add_node("resample", node)

        return self

    def crop(self, bounds: Tuple[float, float, float, float],
             lats: np.ndarray, lons: np.ndarray) -> 'ImageProcessingPipeline':
        """
        Add cropping node.

        Args:
            bounds: (min_lon, max_lon, min_lat, max_lat)
            lats: Latitude array
            lons: Longitude array

        Returns:
            Self for chaining
        """
        def cropper(arr: np.ndarray, crop_bounds: Tuple) -> np.ndarray:
            """Crop array to geographic bounds."""
            min_lon, max_lon, min_lat, max_lat = crop_bounds

            # Find row/col indices
            row_mask = (lats >= min_lat) & (lats <= max_lat)
            col_mask = (lons >= min_lon) & (lons <= max_lon)

            rows = np.where(row_mask)[0]
            cols = np.where(col_mask)[0]

            if len(rows) == 0 or len(cols) == 0:
                return arr  # No overlap

            r_min, r_max = rows.min(), rows.max()
            c_min, c_max = cols.min(), cols.max()

            return arr[r_min:r_max+1, c_min:c_max+1]

        self.config.crop_bounds = bounds
        self.config.lats = lats
        self.config.lons = lons

        node = CropNode(cropper)
        self.add_node("crop", node)

        return self

    def calibrate(self, params: Dict[str, Dict]) -> 'ImageProcessingPipeline':
        """
        Add calibration node.

        Args:
            params: Dict mapping band_name -> calibration parameters

        Returns:
            Self for chaining
        """
        def calibrator(arr: np.ndarray, **kwargs) -> np.ndarray:
            """Apply calibration."""
            # Simple calibration: scale to 0-1
            arr_min, arr_max = arr.min(), arr.max()
            if arr_max > arr_min:
                arr = (arr - arr_min) / (arr_max - arr_min)
            return arr.astype(self.config.dtype)

        self.config.calibration = True
        self.config.calibration_params = params

        node = CalibrateNode(calibrator)
        self.add_node("calibrate", node)

        return self

    def normalize(self, low_percent: float = 2.0,
                  high_percent: float = 98.0) -> 'ImageProcessingPipeline':
        """
        Add normalization node.

        Args:
            low_percent: Lower percentile for stretch
            high_percent: Upper percentile for stretch

        Returns:
            Self for chaining
        """
        self.config.contrast_stretch = (low_percent, high_percent)

        node = NormalizeNode(low_percent, high_percent)
        self.add_node("normalize", node)

        return self

    def composite(self, band_order: List[str]) -> 'ImageProcessingPipeline':
        """
        Add RGB compositing node.

        Args:
            band_order: Order of bands [R, G, B]

        Returns:
            Self for chaining
        """
        self._composite_order = band_order

        node = CompositeNode(band_order)
        self.add_node("composite", node)

        return self

    def _compute_chunks(self, shape: Tuple, chunk_size: int) -> Tuple:
        """Compute Dask chunk tuple from array shape."""
        chunks = []
        for dim in shape:
            if dim == 0:
                chunks.append((0,))
                continue
            n_chunks = max(1, (dim + chunk_size - 1) // chunk_size)
            base_chunk = dim // n_chunks
            remainder = dim % n_chunks
            chunk_list = [base_chunk + 1] * remainder + [base_chunk] * (n_chunks - remainder)
            chunks.append(tuple(chunk_list))
        return tuple(chunks)

    def _run_pipeline(self, input_data: Any) -> Any:
        """Execute pipeline stages."""
        current_data = input_data

        for name, node in self._nodes:
            try:
                current_data = node.process(current_data, self.config)
            except Exception as e:
                logger.error(f"Pipeline stage '{name}' failed: {e}")
                raise

        return current_data

    def execute(self, **kwargs) -> 'ImageProcessingPipeline':
        """
        Execute pipeline without computing (lazy).

        Returns:
            Self for chaining
        """
        self._start_time = time.time()

        # Initialize data if needed
        if self._data is None and hasattr(self, '_band_names'):
            # Load data through first node
            load_node = None
            for name, node in self._nodes:
                if name == "load":
                    load_node = node
                    break

            if load_node:
                self._data = load_node.process(self._band_names, self.config)

        # Run remaining pipeline
        if self._data is not None:
            # Find and run from second node
            current = self._data
            for name, node in self._nodes[1:]:
                current = node.process(current, self.config)
            self._result = current

        return self

    def compute(self, **kwargs) -> np.ndarray:
        """
        Trigger actual computation and return result.

        This is where Dask arrays are converted to numpy arrays.

        Args:
            **kwargs: Passed to da.compute() (e.g., scheduler, memory_limit)

        Returns:
            numpy array result
        """
        if self._result is None:
            self.execute(**kwargs)

        self._start_time = time.time()

        try:
            if isinstance(self._result, da.Array):
                # Compute Dask array
                logger.info("Computing Dask array...")
                result = self._result.compute(**kwargs)
                self._is_dask = False
            elif isinstance(self._result, dict):
                # Compute all arrays in dict
                logger.info("Computing dictionary of Dask arrays...")
                results_dict, = da.compute(self._result, **kwargs)
                # If composite node exists, return single array
                if len(results_dict) == 1:
                    result = list(results_dict.values())[0]
                else:
                    result = results_dict
                self._is_dask = False
            else:
                # Already numpy
                result = self._result
                self._is_dask = False

            self._result = result
            return result

        except Exception as e:
            logger.error(f"Computation failed: {e}")
            raise

        finally:
            self._end_time = time.time()
            logger.info(f"Pipeline compute time: {self._end_time - self._start_time:.2f}s")

    def compute_to_file(self, output_path: str,
                         format: str = 'png',
                         **kwargs) -> Dict:
        """
        Compute and save to file directly.

        Memory-efficient: Saves without holding full result in memory.

        Args:
            output_path: Output file path
            format: Output format ('png', 'geotiff')
            **kwargs: Passed to compute()

        Returns:
            Dict with status and path
        """
        import os
        from PIL import Image

        # Compute directly to file for memory efficiency
        if isinstance(self._result, da.Array):
            # For PNG: compute and save chunk by chunk
            if format == 'png':
                arr = self._result.compute(**kwargs)
                arr = np.clip(arr * 255, 0, 255).astype('uint8')

                os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
                Image.fromarray(arr).save(output_path)

                return {'status': 'success', 'path': output_path}

            # For GeoTIFF: need additional handling
            elif format == 'geotiff':
                arr = self._result.compute(**kwargs)
                return self._save_geotiff(arr, output_path)

        elif isinstance(self._result, dict):
            # Multiple bands
            results, = da.compute(self._result, **kwargs)
            if format == 'png':
                # Stack for RGB
                bands = [results.get(b, np.zeros((1000, 1000))) for b in self._composite_order]
                arr = np.stack(bands, axis=-1)
                arr = np.clip(arr * 255, 0, 255).astype('uint8')

                os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
                Image.fromarray(arr).save(output_path)

                return {'status': 'success', 'path': output_path}

        return {'status': 'error', 'message': 'Unknown result type'}

    def _save_geotiff(self, arr: np.ndarray, output_path: str) -> Dict:
        """Save as GeoTIFF."""
        try:
            from osgeo import gdal, osr
            import os

            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            # Get dimensions
            if arr.ndim == 3:
                bands, height, width = arr.shape
            else:
                height, width = arr.shape
                bands = 1

            # Create driver
            driver = gdal.GetDriverByName('GTiff')
            out_ds = driver.Create(
                output_path, width, height, bands,
                gdal.GDT_Float32 if arr.dtype == np.float32 else gdal.GDT_Byte
            )

            # Set geotransform from target area
            if self.config.target_area:
                extent = self.config.target_area.area_extent
                x_res = (extent[2] - extent[0]) / width
                y_res = (extent[3] - extent[1]) / height
                geotransform = (extent[0], x_res, 0, extent[3], 0, -y_res)
                out_ds.SetGeoTransform(geotransform)

                # Set projection
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(4326)
                out_ds.SetProjection(srs.ExportToWkt())

            # Write data
            if arr.ndim == 3:
                for i in range(bands):
                    out_ds.GetRasterBand(i + 1).WriteArray(arr[i])
            else:
                out_ds.GetRasterBand(1).WriteArray(arr)

            out_ds = None

            return {'status': 'success', 'path': output_path}

        except ImportError:
            logger.error("GDAL not available for GeoTIFF export")
            return {'status': 'error', 'message': 'GDAL not available'}
        except Exception as e:
            logger.error(f"GeoTIFF export failed: {e}")
            return {'status': 'error', 'message': str(e)}

    def get_stats(self) -> Dict:
        """
        Get pipeline execution statistics.

        Returns:
            Dict with timing and memory info
        """
        stats = {
            'compute_time': self._end_time - self._start_time if self._end_time else None,
            'is_dask': self._is_dask,
            'stages': len(self._nodes),
        }

        if self._result is not None:
            if isinstance(self._result, da.Array):
                stats['shape'] = self._result.shape
                stats['dtype'] = str(self._result.dtype)
                stats['num_chunks'] = self._result.npartitions
            elif isinstance(self._result, dict):
                stats['bands'] = list(self._result.keys())

        return stats

    def __repr__(self) -> str:
        return (f"ImageProcessingPipeline("
                f"stages={len(self._nodes)}, "
                f"dask={self._is_dask})")


def create_pipeline_from_driver(driver: Any,
                                bands: List[str],
                                target_area: Any = None,
                                output_shape: Tuple[int, int] = None,
                                gamma: float = 1.0) -> ImageProcessingPipeline:
    """
    Create pipeline from existing driver.

    Args:
        driver: Driver-like object exposing `scn` or `_scene` with band arrays
        bands: Band names to process
        target_area: Optional target AreaDefinition
        output_shape: Optional (width, height) for resize
        gamma: Gamma correction value

    Returns:
        Configured ImageProcessingPipeline
    """
    pipeline = ImageProcessingPipeline()

    # Configure
    pipeline.config.target_area = target_area
    pipeline.config.output_shape = output_shape
    pipeline.config.gamma = gamma

    # Create scene loader function
    def load_band(band_name: str) -> np.ndarray:
        """Load band from scene."""
        try:
            if hasattr(driver, 'scn') and driver.scn:
                return driver.scn[band_name].values.astype(np.float32)
            elif hasattr(driver, '_scene') and driver._scene:
                return driver._scene[band_name].values.astype(np.float32)
            else:
                raise ValueError("No scene loaded")
        except Exception as e:
            logger.error(f"Failed to load {band_name}: {e}")
            raise

    # Build pipeline
    pipeline.load(load_band, bands)

    if target_area:
        pipeline.resample(target_area, resample_method='nearest')

    pipeline.normalize()
    pipeline.composite(bands[:3] if len(bands) >= 3 else bands)

    return pipeline
