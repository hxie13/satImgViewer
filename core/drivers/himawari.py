"""
Himawari Satellite Driver

Implementation for Himawari-8 and Himawari-9 satellite data.
Supports AHI L1b gridded NetCDF format only.

Note: AHI HSD raw binary format (.dat, .bz2) is NOT supported.
      Only the L1b gridded NetCDF format (.nc) is supported.

satpy dependency removed: data is read directly via core.io.HimawariNCReader (xarray).
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
    Driver for Himawari-8/9 satellites — AHI L1b gridded NetCDF only.

    Supported format:
    - Himawari-8/9 AHI L1b gridded NetCDF (.nc), read via HimawariNCReader (xarray)

    NOT supported:
    - AHI HSD raw binary (.dat, .bz2)
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.HIMAWARI_8
    SUPPORTED_FORMATS = ['.nc']

    def __init__(self, satellite: str = "H08", config: Optional[Dict] = None):
        """
        Initialize Himawari driver.

        Args:
            satellite: 'H08' or 'H09'
            config:    Optional configuration dictionary
        """
        self._satellite_variant = satellite.upper()
        if self._satellite_variant not in ('H08', 'H09'):
            self._satellite_variant = 'H08'

        self.SATELLITE_TYPE = (SatelliteType.HIMAWARI_9
                               if '9' in self._satellite_variant
                               else SatelliteType.HIMAWARI_8)

        super().__init__(config)

        # Direct reader (replaces satpy Scene)
        self._reader = None          # HimawariNCReader instance
        self._area_def = None        # pyresample AreaDefinition
        self._data_format = 'l1b_gridded'

    # ------------------------------------------------------------------
    # Driver interface
    # ------------------------------------------------------------------

    def _init_driver(self) -> None:
        """Initialize driver-specific resources."""
        self._band_map = self._build_band_mapping()

    def _build_band_mapping(self) -> Dict[str, str]:
        """Build canonical → AHI band name mapping."""
        return {canonical: info['name'] for canonical, info in AHI_BANDS.items()}

    def identify(self, file_path: str) -> bool:
        """Check if file is compatible with Himawari driver."""
        filename = os.path.basename(file_path).upper()
        if 'HIMAWARI' in filename:
            return True
        if 'H08' in filename or 'H09' in filename:
            return True
        if 'AHI' in filename:
            return True
        return False

    def get_band_mapping(self) -> Dict[str, str]:
        """Get canonical → AHI band name mapping."""
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
        """Detect data format from file extensions."""
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.dat', '.bz2'):
                return 'hsd'
            if ext == '.nc':
                return 'l1b_gridded'
        return 'unknown'

    def _group_files_by_time(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """Group files by timestamp extracted from filename."""
        groups: Dict[str, List[str]] = {}
        for path in sorted(file_paths):
            m = re.search(r'(\d{8}_\d{4})', os.path.basename(path))
            key = m.group(1) if m else os.path.basename(path)
            groups.setdefault(key, []).append(path)
        return groups

    def load(self, file_paths: List[str]) -> bool:
        """
        Load Himawari L1b gridded NetCDF data.

        Args:
            file_paths: List of paths to .nc files.

        Returns:
            True if loading successful.
        """
        if not file_paths:
            logger.error("[Himawari] No file paths provided")
            return False

        try:
            # Detect and validate format
            fmt = self._detect_data_format(file_paths)
            if fmt == 'hsd':
                logger.error(
                    "[Himawari] HSD binary format (.dat/.bz2) is not supported. "
                    "Please use the AHI L1b gridded NetCDF format (.nc)."
                )
                return False
            if fmt == 'unknown':
                logger.error(f"[Himawari] Unrecognised file format in: {file_paths}")
                return False

            # Auto-detect satellite variant
            for fp in file_paths:
                name = os.path.basename(fp).upper()
                if 'H09' in name or 'HIMAWARI9' in name:
                    self._satellite_variant = 'H09'
                    self.SATELLITE_TYPE = SatelliteType.HIMAWARI_9
                    break

            # Group by time and pick primary group
            time_groups = self._group_files_by_time(file_paths)
            primary_time = next(iter(time_groups))
            primary_files = time_groups[primary_time]
            primary_file = primary_files[0]

            logger.info(f"[Himawari] Loading: {os.path.basename(primary_file)}")

            # Close previous reader
            self._close_reader()

            # Instantiate direct NetCDF reader
            from ..io import HimawariNCReader
            self._reader = HimawariNCReader(primary_file)
            self._area_def = self._reader.get_area_definition()

            self._build_dataset_map()
            self._is_loaded = True
            self._data_format = 'l1b_gridded'
            self._time_groups = time_groups

            logger.info(f"[Himawari] Loaded bands: {self._reader.available_bands()}")
            return True

        except Exception as exc:
            logger.error(f"[Himawari] Failed to load files: {exc}")
            import traceback
            traceback.print_exc()
            self._is_loaded = False
            return False

    def _close_reader(self) -> None:
        """Close reader handle."""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None

    def _build_dataset_map(self) -> None:
        """Build mapping from canonical names to reader band IDs."""
        self._dataset_map = {}
        self._band_catalog = {}

        if self._reader is None:
            return

        for band_id in self._reader.available_bands():  # e.g. 'B01'..'B16'
            canonical = self._canonical_from_dataset(band_id)
            self._dataset_map[canonical] = band_id

            band_info = BandInfo(
                canonical_name=canonical,
                display_name=band_id,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

    def _canonical_from_dataset(self, dataset_name: str) -> str:
        """Convert B## reader band ID to canonical name (VIS006, IR105, etc.)."""
        match = re.search(r'(B\d{2})', dataset_name, re.IGNORECASE)
        if match:
            band_id = match.group(1).upper()
            _map = {
                'B01': 'VIS006', 'B02': 'VIS008', 'B03': 'RED',
                'B04': 'NIR016', 'B05': 'SWIR16', 'B06': 'SWIR22',
                'B07': 'IR039',  'B08': 'WV062',  'B09': 'WV070',
                'B10': 'WV073',  'B11': 'IR086',  'B12': 'IR096',
                'B13': 'IR105',  'B14': 'IR112',  'B15': 'IR123',
                'B16': 'IR133',
            }
            return _map.get(band_id, dataset_name)
        return dataset_name

    def _extract_canonical_from_display(self, display_name: str) -> str:
        """Extract canonical band name from display name like 'IR105 (10.4 μm)'."""
        match = re.match(r'^([A-Z0-9]+)', display_name.strip())
        return match.group(1) if match else display_name.split()[0]

    def _resolve_dataset_name(self, band_name: str) -> Optional[str]:
        """Resolve any band name to a reader band ID (B01..B16)."""
        available = self._reader.available_bands() if self._reader else []

        if band_name in available:
            return band_name
        if band_name in self._dataset_map:
            bid = self._dataset_map[band_name]
            if bid in available:
                return bid

        # Try canonical → band ID
        for canon, bid in self._dataset_map.items():
            if canon == band_name and bid in available:
                return bid

        logger.warning(f"[Himawari] Could not resolve band '{band_name}'")
        return None

    def unload(self) -> None:
        """Release loaded resources."""
        self._close_reader()
        self._dataset_map.clear()
        self._band_catalog.clear()
        self._area_def = None
        self._is_loaded = False
        logger.info("[Himawari] Driver resources released")

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded Himawari data.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array H×W×3, area_definition)
        """
        if not self._is_loaded or self._reader is None:
            raise ValueError("[Himawari] No data loaded")

        try:
            # Resolve band names → reader band IDs
            band_ids = []
            for band in params.bands:
                clean = self._extract_canonical_from_display(band)
                bid = self._resolve_dataset_name(clean)
                if bid:
                    band_ids.append(bid)

            logger.info(f"[Himawari] Requested: {params.bands} → {band_ids}")

            if not band_ids:
                raise ValueError(f"[Himawari] Could not resolve any bands from: {params.bands}")

            # Load band data
            band_data: Dict[str, np.ndarray] = {}
            for bid in band_ids:
                band_data[bid] = self._reader.load_band(bid)

            source_area = self._area_def

            # Resample to target projection if needed
            target_area = None
            if params.output_proj != 'geostationary_native' and source_area is not None:
                custom_w = custom_h = None
                if params.output_size:
                    custom_w = int(params.output_size[0])
                    custom_h = int(params.output_size[1])
                from ..geometry import create_target_area
                target_area = create_target_area(
                    params.output_proj,
                    source_area=source_area,
                    custom_width=custom_w,
                    custom_height=custom_h,
                )
                if target_area is not None:
                    band_data = self._resample_bands(band_data, source_area,
                                                     target_area, params.resample_method)

            result_area = target_area or source_area

            # Composite / process
            if len(band_ids) == 3:
                r = band_data.get(band_ids[0], np.zeros((1, 1)))
                g = band_data.get(band_ids[1], np.zeros((1, 1)))
                b = band_data.get(band_ids[2], np.zeros((1, 1)))
                img = self._process_rgb(r, g, b, params.gamma)
            else:
                raw = band_data.get(band_ids[0], np.zeros((1, 1)))
                img = self._process_single(raw, params.gamma, band_ids[0])

            return img, result_area

        except Exception as exc:
            logger.error(f"[Himawari] Failed to generate image: {exc}")
            raise

    def _resample_bands(
        self,
        band_data: Dict[str, np.ndarray],
        source_area,
        target_area,
        method: str = 'nearest',
    ) -> Dict[str, np.ndarray]:
        """Resample all bands from source to target area via pyresample."""
        try:
            from pyresample.kd_tree import resample_nearest
        except ImportError:
            logger.warning("[Himawari] pyresample not available; skipping resampling")
            return band_data

        _bilinear_fn = None
        if method == 'bilinear':
            try:
                from pyresample.bilinear import resample_bilinear as _bilinear_fn
            except ImportError:
                pass  # fall back to nearest

        resampled: Dict[str, np.ndarray] = {}
        for bid, arr in band_data.items():
            try:
                if _bilinear_fn is not None:
                    out = _bilinear_fn(arr, source_area, target_area,
                                      radius=50000, fill_value=np.nan)
                else:
                    out = resample_nearest(source_area, arr, target_area,
                                          radius_of_influence=50000,
                                          fill_value=np.nan)
                resampled[bid] = out.astype(np.float32)
            except Exception as exc:
                logger.warning(f"[Himawari] Resample {bid} failed: {exc}")
                resampled[bid] = arr
        return resampled

    def _process_rgb(self, r: np.ndarray, g: np.ndarray, b: np.ndarray,
                     gamma: float) -> np.ndarray:
        """Process RGB bands with percentile normalisation."""
        def norm(arr: np.ndarray) -> np.ndarray:
            valid = arr[np.isfinite(arr)]
            if valid.size == 0:
                return np.zeros_like(arr)
            lo, hi = np.percentile(valid, 2), np.percentile(valid, 98)
            return np.clip((arr - lo) / (hi - lo), 0.0, 1.0) if hi > lo else np.zeros_like(arr)

        r, g, b = norm(r), norm(g), norm(b)
        if gamma != 1.0:
            r = np.power(np.clip(r, 0, 1), 1.0 / gamma)
            g = np.power(np.clip(g, 0, 1), 1.0 / gamma)
            b = np.power(np.clip(b, 0, 1), 1.0 / gamma)

        img = np.stack([r, g, b], axis=-1)
        return np.nan_to_num(img, nan=0.0).astype(np.float32)

    def _process_single(self, data: np.ndarray, gamma: float,
                         band_id: str = '') -> np.ndarray:
        """Process single band as grayscale → RGB."""
        # Detect IR bands by B## number
        is_thermal = False
        m = re.match(r'^B(\d{2})$', band_id)
        if m and int(m.group(1)) >= 7:
            is_thermal = True

        valid = data[np.isfinite(data)]
        if valid.size == 0:
            norm = np.zeros_like(data)
        elif is_thermal:
            lo, hi = 200.0, 320.0
            norm = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
        else:
            lo, hi = np.percentile(valid, 2), np.percentile(valid, 98)
            norm = np.clip((data - lo) / (hi - lo), 0.0, 1.0) if hi > lo else np.zeros_like(data)

        if gamma != 1.0:
            norm = np.power(np.clip(norm, 0, 1), 1.0 / gamma)

        img = np.stack([norm] * 3, axis=-1)
        return np.nan_to_num(img, nan=0.0).astype(np.float32)

    def get_metadata(self) -> Dict[str, Any]:
        """Get standardised metadata."""
        if not self._is_loaded:
            return {}

        meta: Dict[str, Any] = {
            'satellite': self._satellite_variant,
            'sensor': 'AHI',
            'satellite_type': self._satellite_variant,
            'data_format': self._data_format,
            'n_bands': len(self._dataset_map),
            'is_loaded': self._is_loaded,
        }

        if self._reader is not None:
            reader_meta = self._reader.get_metadata()
            meta.update({
                'start_time': reader_meta.get('start_time', 'N/A'),
            })

        return meta

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for this satellite."""
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """Get file groups organised by timestamp."""
        return list(self._group_files_by_time(file_paths).values())

    @property
    def satellite_variant(self) -> str:
        return self._satellite_variant

    def __repr__(self) -> str:
        return f"HimawariDriver(satellite={self._satellite_variant}, format={self._data_format})"
