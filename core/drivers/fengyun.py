"""
Fengyun Satellite Driver

Implementation for Fengyun-4A and Fengyun-4B satellite data.
Supports AGRI L1 data and various L2 products.
"""
import os
import re
import glob
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import numpy as np

from .base import (
    BaseSatelliteDriver,
    SatelliteType,
    ProductLevel,
    SatelliteFileInfo,
    BandInfo,
    ProcessingParams,
)

logger = logging.getLogger(__name__)


from core.config import get_satellite_band_map, get_thermal_bands  # noqa: E402

# =============================================================================
# Band Mapping Configuration  (sourced from core.config — single source of truth)
# =============================================================================

AGRI_L1_BANDS: Dict[str, Dict[str, str]] = get_satellite_band_map('AGRI_L1')
THERMAL_BANDS: set = get_thermal_bands('AGRI_L1')

# FY-4B L2 product mappings (kept local — not generic enough for config.py)
FY4B_L2_BANDS: Dict[str, Dict[str, str]] = {
    'CLM':    {'name': 'CLM', 'wavelength': None, 'resolution': '4000M'},
    'FOG':    {'name': 'FOG', 'wavelength': None, 'resolution': '4000M'},
    'CWP':    {'name': 'CWP', 'wavelength': None, 'resolution': '4000M'},
    'CTP':    {'name': 'CTP', 'wavelength': None, 'resolution': '4000M'},
    'CTT':    {'name': 'CTT', 'wavelength': None, 'resolution': '4000M'},
    'ACHA':   {'name': 'ACHA', 'wavelength': None, 'resolution': '1000M'},
    'ACSF':   {'name': 'ACSF', 'wavelength': None, 'resolution': '1000M'},
    'SST':    {'name': 'SST', 'wavelength': None, 'resolution': '2000M'},
    'LST':    {'name': 'LST', 'wavelength': None, 'resolution': '2000M'},
}

# Satellite coverage configurations
SATELLITE_COVERAGE = {
    SatelliteType.FENGYUN_4A: (70, 140, -50, 50),    # West, East, South, North
    SatelliteType.FENGYUN_4B: (75, 135, -55, 55),
}


class FengYunDriver(BaseSatelliteDriver):
    """
    Driver for Fengyun-4 series satellites.

    Supports:
    - FY-4A AGRI L1 data
    - FY-4B AGRI L1 data
    - FY-4B L2 products (Cloud mask, Fog, etc.)
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.UNKNOWN
    SUPPORTED_FORMATS = ['.nc', '.h5', '.hdf', '. HDF5']

    def __init__(self, satellite: str = "FY4A", config: Optional[Dict] = None):
        """
        Initialize Fengyun driver.

        Args:
            satellite: Specific satellite variant ('FY4A' or 'FY4B')
            config: Optional configuration dictionary
        """
        self._satellite_variant = satellite.upper()
        if self._satellite_variant not in ('FY4A', 'FY4B'):
            self._satellite_variant = 'FY4A'

        # Set satellite type
        self.SATELLITE_TYPE = SatelliteType.FENGYUN_4A if 'FY4A' in self._satellite_variant else SatelliteType.FENGYUN_4B

        super().__init__(config)

        # Lazy import flag
        self._satpy = None
        self._scenes: List = []
        self._loaded_reader: Optional[str] = None   # cache for dataset-map reuse
        self._preferred_reader: Optional[str] = None  # Direct reader recommendation

    def _set_preferred_reader(self, reader: str) -> None:
        """
        Set preferred reader from FileTypeRecognizer.
        
        This bypasses the trial-and-error reader detection.
        """
        self._preferred_reader = reader
        logger.info(f"[FengYunDriver] Preferred reader set: {reader}")

    def _init_driver(self) -> None:
        """Initialize driver-specific resources."""
        self._l1_band_map = self._build_l1_band_mapping()
        self._l2_band_map = self._build_l2_band_mapping()
        self._current_level = ProductLevel.UNKNOWN

    def _build_l1_band_mapping(self) -> Dict[str, str]:
        """Build canonical to AGRI L1 band name mapping."""
        return {canonical: info['name'] for canonical, info in AGRI_L1_BANDS.items()}

    def _build_l2_band_mapping(self) -> Dict[str, str]:
        """Build canonical to FY-4B L2 band name mapping."""
        return {canonical: info['name'] for canonical, info in FY4B_L2_BANDS.items()}

    def identify(self, file_path: str) -> bool:
        """Check if file is compatible with Fengyun driver."""
        filename = os.path.basename(file_path).upper()

        # Check for FY-4 satellite markers (FY4B first since FY4A is subset of FY4)
        if 'FY4B' in filename or 'FY-4B' in filename:
            self._satellite_variant = 'FY4B'
            return True
        if 'FY4A' in filename or 'FY-4A' in filename:
            self._satellite_variant = 'FY4A'
            return True

        # Check for AGRI sensor marker
        if 'AGRI' in filename:
            return True

        return False

    def get_band_mapping(self) -> Dict[str, str]:
        """Get band mapping based on current product level."""
        if self._current_level == ProductLevel.L2:
            return self._l2_band_map
        return self._l1_band_map

    def get_available_bands(self) -> List[BandInfo]:
        """Get list of available bands with standardized information."""
        band_dict = AGRI_L1_BANDS if self._current_level != ProductLevel.L2 else FY4B_L2_BANDS

        bands = []
        for canonical, info in band_dict.items():
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=f"{canonical} ({info['wavelength'] or info['name']})",
                wavelength=info.get('wavelength'),
                resolution=info.get('resolution', 'UNKNOWN'),
                is_thermal=canonical in THERMAL_BANDS
            )
            bands.append(band_info)

        return bands

    def _detect_product_level(self, file_paths: List[str]) -> ProductLevel:
        """
        Detect product level from file paths.

        Args:
            file_paths: List of file paths

        Returns:
            Detected ProductLevel
        """
        for path in file_paths:
            filename = os.path.basename(path).upper()

            # Check for L2 markers (handle patterns like _L1-, _L2-, L1-_FDI, etc.)
            if '_L2' in filename or ('L2' in filename and 'AGRI' in filename):
                if any(marker in filename for marker in ['CLM', 'FOG', 'CWP', 'CTT', 'SST', 'L2_']):
                    return ProductLevel.L2

            # Check for AGRI L1 data (handle patterns like _L1-_FDI)
            if 'AGRI' in filename:
                if '_L1' in filename or '_L1-' in filename:
                    return ProductLevel.L1
                # Default AGRI is L1 if no L2 marker found
                return ProductLevel.L1

        return ProductLevel.L1  # Default to L1 for AGRI data

    def _detect_reader(self, file_paths: List[str]) -> str:
        """
        Detect appropriate Satpy reader for files.
        Supports multiple reader fallbacks for compatibility.

        Args:
            file_paths: List of file paths

        Returns:
            Reader name string
        """
        for path in file_paths:
            filename = os.path.basename(path).upper()

            # FY-4B L2 products often use CF-compliant NetCDF
            if 'L2' in filename:
                if 'CLM' in filename or 'FOG' in filename:
                    return 'satpy_cf_nc'
                return 'generic_image'

            # AGRI L1 data - check for FY4B first, then FY4A
            if 'FY4B' in filename or 'FY-4B' in filename or 'AGRI' in filename:
                # Try reader in order of preference
                if self._check_reader_available('agri_fy4b'):
                    return 'agri_fy4b'
                elif self._check_reader_available('agri_fy4a'):
                    return 'agri_fy4a'
                elif self._check_reader_available('generic_image'):
                    return 'generic_image'
                else:
                    return 'agri_fy4a'  # Default fallback

            if 'FY4A' in filename or 'FY-4A' in filename:
                if self._check_reader_available('agri_fy4a'):
                    return 'agri_fy4a'
                elif self._check_reader_available('generic_image'):
                    return 'generic_image'
                else:
                    return 'agri_fy4a'

        # Default reader
        if self._satellite_variant == 'FY4B':
            if self._check_reader_available('agri_fy4b'):
                return 'agri_fy4b'
            elif self._check_reader_available('generic_image'):
                return 'generic_image'
        return 'agri_fy4a'

    def _check_reader_available(self, reader_name: str) -> bool:
        """
        Check if a satpy reader is available.

        Args:
            reader_name: Name of the reader to check

        Returns:
            True if reader is available
        """
        try:
            if self._satpy is None:
                self._configure_satpy_logging()
                import satpy as _satpy_module
                self._satpy = _satpy_module

            # Check if reader is in available readers
            available_readers = self._satpy.available_readers()
            return reader_name in available_readers
        except Exception:
            return False

    def _group_files_by_time(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """
        Group files by timestamp.

        Args:
            file_paths: List of file paths

        Returns:
            Dict mapping timestamp to file list
        """
        groups: Dict[str, List[str]] = {}

        for path in sorted(file_paths):
            filename = os.path.basename(path)

            # Try to extract timestamp
            # Pattern: YYYYMMDD_HHMM
            match = re.search(r'(\d{8}[_-]?\d{4})', filename)
            if match:
                ts = match.group(1)
            else:
                ts = filename

            if ts not in groups:
                groups[ts] = []
            groups[ts].append(path)

        return groups

    def load(self, file_paths: List[str]) -> bool:
        """
        Load Fengyun satellite data from file paths.

        Args:
            file_paths: List of paths to satellite data files

        Returns:
            True if loading successful
        """
        if not file_paths:
            logger.error("No file paths provided")
            return False

        try:
            # Configure logging BEFORE importing satpy
            if self._satpy is None:
                self._configure_satpy_logging()
                import satpy as _satpy_module
                self._satpy = _satpy_module

            # Detect product level
            self._current_level = self._detect_product_level(file_paths)
            logger.info(f"Detected product level: {self._current_level.value}")

            # Group files by time
            time_groups = self._group_files_by_time(file_paths)
            logger.info(f"Found {len(time_groups)} time groups")

            # Load first time group as primary scene
            if not time_groups:
                logger.error("No valid time groups found")
                return False

            primary_time = next(iter(time_groups.keys()))
            primary_files = time_groups[primary_time]

            # Determine reader to use - prioritize preferred reader from FileTypeRecognizer
            scene = None
            used_reader = None
            
            if self._preferred_reader:
                # Use FileTypeRecognizer recommendation directly (fast path)
                logger.info(f"[FastPath] Using FileTypeRecognizer recommendation: {self._preferred_reader}")
                try:
                    scene = self._satpy.Scene(
                        reader=self._preferred_reader,
                        filenames=primary_files
                    )
                    if scene.available_dataset_names():
                        used_reader = self._preferred_reader
                        logger.info(f"[FastPath] Success with preferred reader: {used_reader}")
                except Exception as e:
                    logger.warning(f"[FastPath] Preferred reader {self._preferred_reader} failed: {e}")
                    # Clear preferred reader and fall back to detection
                    self._preferred_reader = None
            
            if scene is None:
                # Fall back to traditional reader detection with fallback chain
                reader_name = self._detect_reader(file_paths)
                logger.info(f"Using detected reader: {reader_name}")

                # Build fallback chain
                reader_fallbacks = [reader_name]
                if reader_name == 'agri_fy4b':
                    reader_fallbacks = ['agri_fy4a', 'generic_image', 'satpy_cf_nc']
                elif reader_name == 'agri_fy4a':
                    reader_fallbacks = ['generic_image']

                for reader in reader_fallbacks:
                    try:
                        logger.info(f"Trying reader: {reader}")
                        scene = self._satpy.Scene(
                            reader=reader,
                            filenames=primary_files
                        )
                        if scene.available_dataset_names():
                            used_reader = reader
                            logger.info(f"Success with reader: {reader}")
                            break
                    except Exception as e:
                        logger.warning(f"Reader {reader} failed: {e}")
                        continue

            if scene is None or not scene.available_dataset_names():
                # Last resort: try auto-detection
                logger.info("Trying auto-detection...")
                try:
                    scene = self._satpy.Scene(filenames=primary_files)
                    used_reader = 'auto'
                except Exception as e:
                    logger.error(f"Auto-detection failed: {e}")
                    return False

            self._scene = scene

            # Build dataset map only when reader changes — band structure is
            # identical across all frames of the same satellite/reader, so skip
            # the rebuild on subsequent frame loads (saves ~5-20ms per frame).
            if used_reader != self._loaded_reader:
                self._build_dataset_map()
                self._loaded_reader = used_reader

            self._is_loaded = True
            logger.info(f"Successfully loaded {len(primary_files)} files with reader: {used_reader}")

            # Store time groups for time-series processing
            self._time_groups = time_groups

            return True

        except Exception as e:
            logger.error(f"Failed to load files: {e}")
            self._is_loaded = False
            return False

    def _build_dataset_map(self) -> None:
        """Build mapping from canonical names to dataset names."""
        if self._scene is None:
            return

        self._dataset_map = {}
        self._band_catalog = {}

        available = self._scene.available_dataset_names()

        for dataset in available:
            canonical = self._canonical_from_dataset(dataset)
            self._dataset_map[canonical] = dataset

            # Build band catalog entry
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=dataset,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

    def _canonical_from_dataset(self, dataset_name: str) -> str:
        """
        Convert dataset name to canonical name.

        Args:
            dataset_name: Satpy dataset name

        Returns:
            Canonical band name
        """
        import re

        # Try Channel pattern (e.g., Channel01 -> VIS006) for FY4A
        match = re.search(r'Channel(\d{2})', dataset_name, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return self._channel_to_canonical(num)

        # Try C## pattern (e.g., C01 -> VIS006) for FY4B
        match = re.search(r'^C(\d{2})$', dataset_name, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return self._channel_to_canonical(num)

        # Return as-is if no match
        return dataset_name

    def _channel_to_canonical(self, channel_num: int) -> str:
        """Map channel number to canonical name."""
        channel_map = {
            1: 'VIS006', 2: 'VIS008', 3: 'RED', 4: 'NIR016',
            5: 'SWIR16', 6: 'SWIR22', 7: 'IR039', 8: 'IR062',
            9: 'IR072', 10: 'IR086', 11: 'IR096', 12: 'IR105',
            13: 'IR112', 14: 'IR133', 15: 'BT136', 16: 'CO2',
        }
        return channel_map.get(channel_num, f'C{channel_num:02d}')

    def _extract_canonical_from_display(self, display_name: str) -> str:
        """
        Extract canonical band name from display name.

        Args:
            display_name: Display name (e.g., 'IR133 (13.5 μm)' or 'IR133')

        Returns:
            Canonical band name (e.g., 'IR133')
        """
        # Remove wavelength info in parentheses
        import re
        match = re.match(r'^([A-Z0-9]+)', display_name.strip())
        if match:
            return match.group(1)

        # Try to extract from patterns like 'IR133 (13.5 μm)'
        # Just return the first word
        return display_name.split()[0]

    def unload(self) -> None:
        """Release loaded resources."""
        if self._scene is not None:
            try:
                self._scene = None
            except Exception:
                pass
        self._scenes.clear()
        self._dataset_map.clear()
        self._band_catalog.clear()
        self._is_loaded = False
        logger.info("Driver resources released")

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded scene.

        Uses the new ImageProcessingPipeline for memory-efficient processing.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array, area_definition)
        """
        if not self._is_loaded or self._scene is None:
            raise ValueError("No scene loaded")

        try:
            # Map canonical band names to dataset names
            # Handle both canonical names (IR133) and display names (IR133 (13.5 μm))
            datasets = []
            for band in params.bands:
                # Extract canonical name from display name if needed
                clean_band = self._extract_canonical_from_display(band)
                ds_name = self._resolve_dataset_name(clean_band)
                datasets.append(ds_name)

            logger.info(f"[BandResolve] Requested bands: {params.bands}")
            logger.info(f"[BandResolve] Cleaned bands: {[self._extract_canonical_from_display(b) for b in params.bands]}")
            logger.info(f"[BandResolve] Dataset names: {datasets}")
            logger.info(f"[BandResolve] _dataset_map: {self._dataset_map}")
            logger.info(f"[BandResolve] Available datasets: {self._scene.available_dataset_names()}")

            # Use pipeline for memory-efficient processing
            return self._request_image_pipeline(datasets, params)

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _resolve_dataset_name(self, band_name: str) -> str:
        """
        Resolve a band name to an actual dataset name in the scene.

        Handles multiple name formats:
        - Canonical names (IR133)
        - Short names (C14)
        - Display names (IR133 (13.5 μm))
        - Actual dataset names (Channel14)

        Args:
            band_name: The band name to resolve

        Returns:
            The actual dataset name in the scene
        """
        # First check if it's already a valid dataset name
        available = self._scene.available_dataset_names()

        if band_name in available:
            return band_name

        # Try canonical name mapping
        if band_name in self._dataset_map:
            ds_name = self._dataset_map[band_name]
            if ds_name in available:
                return ds_name

        # Try reverse lookup: canonical -> dataset
        for canonical, ds_name in self._dataset_map.items():
            if ds_name == band_name:
                return ds_name

        # Try to find dataset by pattern matching
        # Handle patterns like C## -> Channel##
        import re
        match = re.match(r'^C(\d{2})$', band_name, re.IGNORECASE)
        if match:
            num = match.group(1)
            alternatives = [f'Channel{num}', f'C{num}']
            for alt in alternatives:
                if alt in available:
                    return alt

        # Try pattern Channel## -> C##
        match = re.match(r'^Channel(\d{2})$', band_name, re.IGNORECASE)
        if match:
            num = match.group(1)
            alternatives = [f'C{num}', f'Channel{num}']
            for alt in alternatives:
                if alt in available:
                    return alt

        # Last resort: try to find any dataset containing the band number
        match = re.search(r'(\d{2})', band_name)
        if match:
            num = match.group(1)
            for ds in available:
                if num in ds:
                    logger.debug(f"Found dataset {ds} for band {band_name}")
                    return ds

        # Fallback: return original and let SatPy raise the error
        logger.warning(f"Could not resolve band name '{band_name}', using as-is")
        return band_name

    def _request_image_pipeline(self, datasets: List[str],
                               params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Internal pipeline-based image generation.

        Memory-efficient: Uses Dask for lazy evaluation and chunked processing.
        Resamples directly to target area without intermediate global products.

        Args:
            datasets: List of dataset names
            params: Processing parameters

        Returns:
            Tuple of (image_array, area_definition)
        """
        from ..geometry import create_target_area

        # Load datasets in the scene first
        try:
            self._scene.load(datasets)
        except Exception as e:
            logger.warning(f"Scene load failed: {e}")

        # Get area from first dataset (needed for adaptive projection)
        source_area = None
        try:
            source_area = self._scene[datasets[0]].attrs.get('area')
            logger.info(f"Source area: {source_area}")
        except Exception as e:
            logger.warning(f"Could not get area from {datasets[0]}: {e}")

        # Create pipeline configuration
        from ..pipeline import PipelineConfig

        config = PipelineConfig(
            target_area=None,  # Will be set if resampling
            resample_method=params.resample_method,
            gamma=params.gamma,
            chunk_size=1024,
            dtype=np.float32,
        )

        # Determine target area (pass source_area for adaptive extent)
        target_area = None
        if params.output_proj != 'geostationary_native':
            custom_width = None
            custom_height = None
            if params.output_size:
                custom_width = int(params.output_size[0])
                custom_height = int(params.output_size[1])
            target_area = create_target_area(
                params.output_proj,
                source_area=source_area,
                custom_width=custom_width,
                custom_height=custom_height,
            )
            config.target_area = target_area
            if target_area:
                logger.info(f"Target area created: {params.output_proj}")

        # Create loader function
        def load_band(band_name: str) -> np.ndarray:
            """Load band data as numpy array (will be converted to Dask)."""
            try:
                logger.info(f"[LoadBand] Loading band: {band_name}")
                data = self._scene[band_name]
                logger.info(f"  Data type: {type(data)}")
                logger.info(f"  Data shape: {data.sizes if hasattr(data, 'sizes') else 'N/A'}")
                arr = data.values.astype(np.float32)
                nan_count = np.sum(np.isnan(arr))
                logger.info(f"  Array shape: {arr.shape}, min={np.nanmin(arr):.4f}, max={np.nanmax(arr):.4f}, NaN count={nan_count}")
                return arr
            except Exception as e:
                logger.error(f"Failed to load band {band_name}: {e}")
                import traceback
                traceback.print_exc()
                # Return zeros as fallback
                return np.zeros((2748, 2748), dtype=np.float32)

        # Build processing pipeline
        from ..pipeline import ImageProcessingPipeline

        logger.info(f"Building pipeline for bands: {datasets}")
        logger.info(f"Output projection: {params.output_proj}")

        pipeline = ImageProcessingPipeline()

        # Stage 1: Load
        pipeline.load(load_band, datasets)

        # Stage 2: Resample directly to target area (if needed)
        if target_area is not None:
            logger.info(f"Resampling to target area: {params.output_proj}")
            pipeline.resample(
                target_area,
                resample_method=params.resample_method
            )

        # Stage 3: Normalize
        logger.info("Normalizing bands (2-98 percentile)")
        pipeline.normalize(low_percent=2.0, high_percent=98.0)

        # Stage 4: Composite
        if len(datasets) == 3:
            logger.info(f"Compositing RGB: {datasets[:3]}")
            pipeline.composite(datasets[:3])

        # Execute pipeline (lazy)
        logger.info("Executing pipeline...")
        pipeline.execute()

        # Compute result
        logger.info("Computing result...")
        img = pipeline.compute()
        logger.info(f"Computed image shape: {img.shape}, dtype: {img.dtype}")
        logger.info(f"Image stats: min={np.nanmin(img):.6f}, max={np.nanmax(img):.6f}")

        # Ensure we have area for return (use target_area or fall back to source_area)
        if target_area is None:
            try:
                target_area = source_area
            except Exception:
                target_area = None

        return img, target_area

    def export_image_pipeline(self, bands: List[str],
                            output_path: str,
                            proj_name: str = 'plate_carree_china',
                            export_format: str = 'png',
                            gamma: float = 1.0,
                            region: str = 'china',
                            calibration: bool = False) -> Dict:
        """
        Export image using memory-efficient pipeline.

        Key optimizations:
        1. Resamples directly to target area (no intermediate global)
        2. Uses Dask for lazy evaluation
        3. Computes directly to file (doesn't hold full result in memory)

        Args:
            bands: List of band names
            output_path: Output file path
            proj_name: Projection name
            export_format: Output format ('png', 'geotiff')
            gamma: Gamma correction
            region: Geographic region for cropping
            calibration: Whether to apply calibration

        Returns:
            Dict with status and details
        """
        import os
        import gc
        from PIL import Image
        from ..geometry import create_target_area, ProjectionFactory
        from ..pipeline import Pipeline, PipelineConfig

        if not self._is_loaded or self._scene is None:
            raise ValueError("No scene loaded")

        try:
            # Memory cleanup before starting
            gc.collect()

            # Map band names
            clean_bands = []
            for band in bands:
                clean_band = self._extract_canonical_from_display(band)
                ds_name = self._dataset_map.get(clean_band, band)
                clean_bands.append(ds_name)

            logger.info(f"Exporting bands: {clean_bands}")

            # Determine target area and output shape
            target_area = None
            output_shape = None

            if proj_name != 'geostationary_native':
                if region != 'global':
                    # Create custom area for region
                    reg_info = {
                        'china': (70, 142, 15, 55),
                        'east_asia': (70, 150, 0, 60),
                        'southeast_asia': (90, 140, -10, 25),
                    }
                    if region in reg_info:
                        west, east, south, north = reg_info[region]
                        resolution = 0.05  # ~5km
                        width = int((east - west) / resolution)
                        height = int((north - south) / resolution)
                        output_shape = (height, width)

                        target_area = ProjectionFactory.create_from_extent(
                            name=f'export_{region}',
                            west=west, east=east, south=south, north=north,
                            resolution=resolution
                        )
                else:
                    target_area = create_target_area(proj_name)
                    proj_config = ProjectionFactory.get_config(proj_name)
                    if proj_config:
                        output_shape = (proj_config.height, proj_config.width)

            # Load bands
            band_data = {}
            for band in clean_bands:
                arr = self._scene[band].values.astype(np.float32)
                band_data[band] = arr

            # Apply calibration if requested
            if calibration:
                for i, band in enumerate(clean_bands):
                    try:
                        # Simplified calibration
                        arr_min, arr_max = band_data[band].min(), band_data[band].max()
                        if arr_max > arr_min:
                            band_data[band] = (band_data[band] - arr_min) / (arr_max - arr_min)
                    except Exception as e:
                        logger.warning(f"Calibration failed for {band}: {e}")

            # Resample if needed (directly to target area)
            if target_area is not None:
                from pyresample import geometry as _geom

                # Create target arrays
                target_shape = output_shape or (1000, 1000)
                height, width = target_shape

                # Create target coordinate grids
                extent = target_area.area_extent
                x_coords = np.linspace(extent[0], extent[2], width)
                y_coords = np.linspace(extent[3], extent[1], height)
                x_grid, y_grid = np.meshgrid(x_coords, y_coords)

                # Resample each band directly to target area
                resampled_data = {}
                for band, arr in band_data.items():
                    try:
                        # Get source coordinates
                        source_area = self._scene[band].attrs.get('area')
                        if hasattr(source_area, 'get_lonlats'):
                            src_lons, src_lats = source_area.get_lonlats()
                        else:
                            continue

                        # Nearest neighbor resampling
                        from scipy.spatial import cKDTree

                        src_flat = np.column_stack([src_lons.ravel(), src_lats.ravel()])
                        tgt_flat = np.column_stack([x_grid.ravel(), y_grid.ravel()])

                        tree = cKDTree(src_flat)
                        _, indices = tree.query(tgt_flat, k=1)

                        resampled = arr.ravel()[indices].reshape(height, width)
                        resampled_data[band] = resampled

                    except Exception as e:
                        logger.warning(f"Resampling failed for {band}: {e}")
                        resampled_data[band] = np.zeros(target_shape, dtype=np.float32)

                band_data = resampled_data

            # Composite
            if len(clean_bands) == 3:
                # RGB composite
                r = band_data.get(clean_bands[0], np.zeros(output_shape or (1000, 1000)))
                g = band_data.get(clean_bands[1], np.zeros(output_shape or (1000, 1000)))
                b = band_data.get(clean_bands[2], np.zeros(output_shape or (1000, 1000)))

                # Normalize
                for arr in [r, g, b]:
                    arr_min, arr_max = arr.min(), arr.max()
                    if arr_max > arr_min:
                        arr[...] = (arr - arr_min) / (arr_max - arr_min)

                img = np.stack([r, g, b], axis=-1)
            else:
                # Single band
                img = band_data.get(clean_bands[0], np.zeros((1000, 1000), dtype=np.float32))
                if img.ndim == 2:
                    img = np.stack([img] * 3, axis=-1)

            # Apply gamma
            if gamma != 1.0:
                img = np.power(np.clip(img, 0, 1), 1.0 / gamma)

            # Ensure proper dtype
            img = np.clip(img, 0, 1).astype(np.float32)

            # Save
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            if export_format == 'png':
                img_uint8 = (img * 255).astype(np.uint8)
                if img_uint8.ndim == 3 and img_uint8.shape[2] == 4:
                    # RGBA to RGB
                    from PIL import Image as PILImage
                    pil_img = PILImage.fromarray(img_uint8, mode='RGBA')
                    rgb_img = pil_img.convert('RGB')
                    rgb_img.save(output_path)
                elif img_uint8.ndim == 3:
                    PILImage.fromarray(img_uint8, mode='RGB').save(output_path)
                else:
                    PILImage.fromarray(img_uint8, mode='L').save(output_path)

            elif export_format == 'geotiff':
                self._save_geotiff_with_pipeline(img, output_path, target_area)

            # Memory cleanup
            del band_data, img
            gc.collect()

            return {
                'status': 'success',
                'path': output_path,
                'shape': img.shape if 'img' in dir() else 'unknown'
            }

        except Exception as e:
            logger.error(f"Export failed: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def _save_geotiff_with_pipeline(self, img: np.ndarray,
                                   output_path: str,
                                   target_area: Any) -> None:
        """Save image as GeoTIFF using pipeline approach."""
        try:
            from osgeo import gdal, osr
            import os

            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            # Get dimensions
            if img.ndim == 3:
                height, width, bands = img.shape
            else:
                height, width = img.shape
                bands = 1

            # Create driver
            driver = gdal.GetDriverByName('GTiff')
            options = ['COMPRESS=LZW', 'TILED=YES', 'BLOCKXSIZE=256', 'BLOCKYSIZE=256']
            out_ds = driver.Create(
                output_path, width, height, bands,
                gdal.GDT_Float32,
                options=options
            )

            # Set geotransform
            if target_area and hasattr(target_area, 'area_extent'):
                extent = target_area.area_extent
                x_res = (extent[2] - extent[0]) / width
                y_res = (extent[3] - extent[1]) / height
                geotransform = (extent[0], x_res, 0, extent[3], 0, -y_res)
                out_ds.SetGeoTransform(geotransform)

                # Set projection
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(4326)
                out_ds.SetProjection(srs.ExportToWkt())

            # Write data
            if img.ndim == 3:
                for i in range(bands):
                    out_ds.GetRasterBand(i + 1).WriteArray(img[:, :, i])
            else:
                out_ds.GetRasterBand(1).WriteArray(img)

            out_ds = None
            logger.info(f"Saved GeoTIFF: {output_path}")

        except ImportError:
            logger.error("GDAL not available")
            raise
        except Exception as e:
            logger.error(f"GeoTIFF save failed: {e}")
            raise
            raise

    def _process_rgb(self, r: np.ndarray, g: np.ndarray, b: np.ndarray,
                     gamma: float) -> np.ndarray:
        """Process RGB bands."""
        # Normalize each band
        def normalize(arr):
            arr_min, arr_max = np.nanmin(arr), np.nanmax(arr)
            if arr_max - arr_min > 0:
                return (arr - arr_min) / (arr_max - arr_min)
            return arr

        r = normalize(r)
        g = normalize(g)
        b = normalize(b)

        # Apply gamma correction
        if gamma != 1.0:
            r = np.power(np.clip(r, 0, 1), 1.0 / gamma)
            g = np.power(np.clip(g, 0, 1), 1.0 / gamma)
            b = np.power(np.clip(b, 0, 1), 1.0 / gamma)

        # Stack as RGB
        img = np.stack([r, g, b], axis=-1)

        # Handle NaN
        img = np.nan_to_num(img, nan=0.0)

        return img

    def _process_single(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Process single band."""
        data_min, data_max = np.nanmin(data), np.nanmax(data)
        if data_max - data_min > 0:
            norm = (data - data_min) / (data_max - data_min)
        else:
            norm = data

        if gamma != 1.0:
            norm = np.power(np.clip(norm, 0, 1), 1.0 / gamma)

        img = np.stack([norm] * 3, axis=-1)
        img = np.nan_to_num(img, nan=0.0)

        return img

    def get_metadata(self) -> Dict[str, Any]:
        """Get standardized metadata."""
        if self._scene is None:
            return {}

        try:
            start_time = self._scene.start_time
            platform = self._scene.attrs.get('platform_name', self._satellite_variant)
            sensor = self._scene.attrs.get('sensor', 'AGRI')
        except Exception:
            start_time = None
            platform = self._satellite_variant
            sensor = 'AGRI'

        return {
            'satellite': platform,
            'sensor': sensor,
            'satellite_type': self._satellite_variant,
            'product_level': self._current_level.value if self._current_level else 'UNKNOWN',
            'start_time': start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else "N/A",
            'n_bands': len(self._dataset_map),
            'is_loaded': self._is_loaded,
        }

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for this satellite."""
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """Get file groups organized by timestamp."""
        return list(self._group_files_by_time(file_paths).values())

    @property
    def satellite_variant(self) -> str:
        """Get the satellite variant."""
        return self._satellite_variant

    def __repr__(self) -> str:
        return f"FengYunDriver(satellite={self._satellite_variant}, level={self._current_level.value})"
