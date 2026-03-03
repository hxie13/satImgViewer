"""
Himawari Satellite Driver

Implementation for Himawari-8 and Himawari-9 satellite data.
Supports AHI HSD (raw) and L1b gridded formats.
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from .base import (
    BaseSatelliteDriver,
    SatelliteType,
    ProductLevel,
    BandInfo,
    ProcessingParams,
)

from core.config import get_satellite_band_map, get_thermal_bands  # noqa: E402

logger = logging.getLogger(__name__)



# =============================================================================
# Band Mapping Configuration  (sourced from core.config — single source of truth)
# =============================================================================

AHI_BANDS: Dict[str, Dict[str, str]] = get_satellite_band_map('AHI')
THERMAL_BANDS: set = get_thermal_bands('AHI')

# Satellite coverage configurations
SATELLITE_COVERAGE = {
    SatelliteType.HIMAWARI_8: (80, 160, -60, 60),
    SatelliteType.HIMAWARI_9: (80, 160, -60, 60),
}


class HimawariDriver(BaseSatelliteDriver):
    """
    Driver for Himawari-8/9 satellites.

    Supports:
    - Himawari-8/9 AHI HSD raw data (.dat, .bz2)
    - Himawari-8/9 AHI L1b gridded data (.nc)
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.HIMAWARI_8
    SUPPORTED_FORMATS = ['.dat', '.bz2', '.nc', '.grb']

    def __init__(self, satellite: str = "H08", config: Optional[Dict] = None):
        """
        Initialize Himawari driver.

        Args:
            satellite: Specific satellite variant ('H08' or 'H09')
            config: Optional configuration dictionary
        """
        self._satellite_variant = satellite.upper()
        if self._satellite_variant not in ('H08', 'H09'):
            self._satellite_variant = 'H08'

        # Set satellite type
        if '9' in self._satellite_variant:
            self.SATELLITE_TYPE = SatelliteType.HIMAWARI_9
        else:
            self.SATELLITE_TYPE = SatelliteType.HIMAWARI_8

        super().__init__(config)

        # Lazy import flag
        self._satpy = None
        self._scenes: List = []
        self._data_format = 'hsd'  # 'hsd' or 'l1b_gridded'
        self._loaded_reader: Optional[str] = None   # cache for dataset-map reuse

    def _init_driver(self) -> None:
        """Initialize driver-specific resources."""
        self._band_map = self._build_band_mapping()

    def _build_band_mapping(self) -> Dict[str, str]:
        """Build canonical to AHI band name mapping."""
        return {canonical: info['name'] for canonical, info in AHI_BANDS.items()}

    def identify(self, file_path: str) -> bool:
        """Check if file is compatible with Himawari driver."""
        filename = os.path.basename(file_path).upper()

        # Check for Himawari satellite markers
        if 'HIMAWARI' in filename:
            return True
        if 'H08' in filename or 'H09' in filename:
            return True

        # Check for AHI sensor marker
        if 'AHI' in filename:
            return True

        return False

    def get_band_mapping(self) -> Dict[str, str]:
        """Get canonical to AHI band name mapping."""
        return self._band_map

    def get_available_bands(self) -> List[BandInfo]:
        """Get list of available bands with standardized information."""
        bands = []
        for canonical, info in AHI_BANDS.items():
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=f"{info['name']} ({info['wavelength']})",
                wavelength=info['wavelength'],
                resolution=info['resolution'],
                is_thermal=canonical in THERMAL_BANDS
            )
            bands.append(band_info)

        return bands

    def _detect_data_format(self, file_paths: List[str]) -> str:
        """
        Detect data format from file paths.

        Args:
            file_paths: List of file paths

        Returns:
            Format identifier ('hsd' or 'l1b_gridded')
        """
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            filename = os.path.basename(path).upper()

            # .dat or .bz2 are typically HSD format
            if ext in ('.dat', '.bz2'):
                return 'hsd'

            # L1b gridded data is typically .nc
            if ext == '.nc':
                # Check if it's gridded format
                if 'GRIDDED' in filename or 'L1B' in filename:
                    return 'l1b_gridded'
                # Default to HSD for .nc as well
                return 'hsd'

        return 'hsd'

    def _detect_reader(self, file_paths: List[str]) -> str:
        """
        Detect appropriate Satpy reader for files.

        Args:
            file_paths: List of file paths

        Returns:
            Reader name string
        """
        data_format = self._detect_data_format(file_paths)

        if data_format == 'l1b_gridded':
            return 'ahi_l1b_gridded'

        # Default to HSD reader
        return 'ahi_hsd'

    def _group_files_by_segment(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """
        Group HSD files by segment and time.

        AHI HSD data comes in segments (B01 through B15, plus image navigation).

        Args:
            file_paths: List of file paths

        Returns:
            Dict mapping time_key to file list
        """
        groups: Dict[str, List[str]] = {}

        for path in sorted(file_paths):
            filename = os.path.basename(path)

            # Extract time from filename
            # Pattern: HS_H08_20230101_0300_B01_R10_S0101.DAT
            match = re.search(r'(\d{8}_\d{4})', filename)
            if match:
                time_key = match.group(1)
            else:
                time_key = filename

            if time_key not in groups:
                groups[time_key] = []
            groups[time_key].append(path)

        return groups

    def load(self, file_paths: List[str]) -> bool:
        """
        Load Himawari satellite data from file paths.

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

            # Detect data format and reader
            self._data_format = self._detect_data_format(file_paths)
            reader_name = self._detect_reader(file_paths)
            logger.info(f"Detected format: {self._data_format}, reader: {reader_name}")

            # Group files
            if self._data_format == 'hsd':
                file_groups = self._group_files_by_segment(file_paths)
            else:
                file_groups = {'default': file_paths}

            logger.info(f"Found {len(file_groups)} time groups")

            if not file_groups:
                logger.error("No valid file groups found")
                return False

            # Load first time group as primary scene
            primary_time = next(iter(file_groups.keys()))
            primary_files = file_groups[primary_time]

            # Create scene
            self._scene = self._satpy.Scene(
                reader=reader_name,
                filenames=primary_files
            )

            # Build dataset map only when reader changes — band structure is
            # identical across all frames of the same satellite/reader.
            if reader_name != self._loaded_reader:
                self._build_dataset_map()
                self._loaded_reader = reader_name

            self._is_loaded = True
            logger.info(f"Successfully loaded {len(primary_files)} files")

            # Store time groups
            self._time_groups = file_groups

            return True

        except Exception as e:
            logger.error(f"Failed to load files: {e}")
            import traceback
            traceback.print_exc()
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
        # Try B## pattern (e.g., B01 -> VIS006)
        match = re.search(r'(B\d{2})', dataset_name, re.IGNORECASE)
        if match:
            band_id = match.group(1).upper()
            # Map B## to canonical
            band_map = {
                'B01': 'VIS006', 'B02': 'VIS008', 'B03': 'RED',
                'B04': 'NIR016', 'B05': 'SWIR16', 'B06': 'SWIR22',
                'B07': 'IR039', 'B08': 'WV062', 'B09': 'WV070',
                'B10': 'WV073', 'B11': 'IR086', 'B12': 'IR096',
                'B13': 'IR105', 'B14': 'IR112', 'B15': 'IR123',
            }
            return band_map.get(band_id, dataset_name)

        return dataset_name

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

    def _extract_canonical_from_display(self, display_name: str) -> str:
        """
        Extract canonical band name from display name.

        Args:
            display_name: Display name (e.g., 'IR105 (10.4 μm)' or 'IR105')

        Returns:
            Canonical band name (e.g., 'IR105')
        """
        import re
        match = re.match(r'^([A-Z0-9]+)', display_name.strip())
        if match:
            return match.group(1)
        return display_name.split()[0]

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded scene.

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
                clean_band = self._extract_canonical_from_display(band)
                ds_name = self._dataset_map.get(clean_band, band)
                datasets.append(ds_name)

            # Debug logging
            logger.debug(f"Requested bands: {params.bands}")
            logger.debug(f"Cleaned bands: {[self._extract_canonical_from_display(b) for b in params.bands]}")
            logger.debug(f"Dataset names: {datasets}")

            # Load datasets
            self._scene.load(datasets)

            # Get first dataset for area info
            first_ds = self._scene[datasets[0]]
            source_area = first_ds.attrs.get('area')

            # Resample if needed
            from ..geometry import create_target_area
            local_scn = self._scene

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
                if target_area is not None:
                    local_scn = self._scene.resample(
                        target_area,
                        resampler=params.resample_method
                    )

            # Read data and process
            if len(datasets) == 3:
                r = local_scn[datasets[0]].values
                g = local_scn[datasets[1]].values
                b = local_scn[datasets[2]].values

                img = self._process_rgb(r, g, b, params.gamma)
            else:
                raw = local_scn[datasets[0]].values
                img = self._process_single(raw, params.gamma)

            # Get area definition
            area = local_scn[datasets[0]].attrs.get('area')

            return img, area

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            raise

    def _process_rgb(self, r: np.ndarray, g: np.ndarray, b: np.ndarray,
                     gamma: float) -> np.ndarray:
        """Process RGB bands."""
        def normalize(arr):
            arr_min, arr_max = np.nanmin(arr), np.nanmax(arr)
            if arr_max - arr_min > 0:
                return (arr - arr_min) / (arr_max - arr_min)
            return arr

        r = normalize(r)
        g = normalize(g)
        b = normalize(b)

        if gamma != 1.0:
            r = np.power(np.clip(r, 0, 1), 1.0 / gamma)
            g = np.power(np.clip(g, 0, 1), 1.0 / gamma)
            b = np.power(np.clip(b, 0, 1), 1.0 / gamma)

        img = np.stack([r, g, b], axis=-1)
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
            sensor = self._scene.attrs.get('sensor', 'AHI')
        except Exception:
            start_time = None
            platform = self._satellite_variant
            sensor = 'AHI'

        return {
            'satellite': platform,
            'sensor': sensor,
            'satellite_type': self._satellite_variant,
            'data_format': self._data_format,
            'start_time': start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else "N/A",
            'n_bands': len(self._dataset_map),
            'is_loaded': self._is_loaded,
        }

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for this satellite."""
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """Get file groups organized by timestamp."""
        if self._data_format == 'hsd':
            return list(self._group_files_by_segment(file_paths).values())
        return [file_paths]

    @property
    def satellite_variant(self) -> str:
        """Get the satellite variant."""
        return self._satellite_variant

    def __repr__(self) -> str:
        return f"HimawariDriver(satellite={self._satellite_variant}, format={self._data_format})"
