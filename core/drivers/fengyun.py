"""
Fengyun Satellite Driver

Implementation for Fengyun-4A and Fengyun-4B satellite data.
Supports AGRI L1 data and various L2 products.

satpy dependency removed: data is read directly via core.io.FY4Reader (h5py + LUT calibration).
"""
import os
import re
import glob
import gc
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
    - FY-4A AGRI L1 data (HDF5, direct h5py reading via FY4Reader)
    - FY-4B AGRI L1 data (HDF5, direct h5py reading via FY4Reader)
    - FY-4B L2 products (NetCDF, xarray via FY4L2Reader)
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.UNKNOWN
    SUPPORTED_FORMATS = ['.nc', '.h5', '.hdf', '.HDF5']

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
        self.SATELLITE_TYPE = (SatelliteType.FENGYUN_4A
                               if 'FY4A' in self._satellite_variant
                               else SatelliteType.FENGYUN_4B)

        super().__init__(config)

        # Direct reader (replaces satpy Scene)
        self._reader = None          # FY4Reader instance (L1)
        self._l2_reader = None       # FY4L2Reader instance (L2)
        self._area_def = None        # pyresample AreaDefinition
        self._time_groups: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Driver interface implementation
    # ------------------------------------------------------------------

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

        if 'FY4B' in filename or 'FY-4B' in filename:
            self._satellite_variant = 'FY4B'
            return True
        if 'FY4A' in filename or 'FY-4A' in filename:
            self._satellite_variant = 'FY4A'
            return True
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
        """Detect product level from file paths."""
        for path in file_paths:
            filename = os.path.basename(path).upper()

            if '_L2' in filename or ('L2' in filename and 'AGRI' in filename):
                if any(marker in filename for marker in ['CLM', 'FOG', 'CWP', 'CTT', 'SST', 'L2_']):
                    return ProductLevel.L2

            if 'AGRI' in filename:
                if '_L1' in filename or '_L1-' in filename:
                    return ProductLevel.L1
                return ProductLevel.L1

        return ProductLevel.L1

    def _group_files_by_time(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """Group files by timestamp."""
        groups: Dict[str, List[str]] = {}

        for path in sorted(file_paths):
            filename = os.path.basename(path)
            match = re.search(r'(\d{8}[_-]?\d{4})', filename)
            ts = match.group(1) if match else filename

            if ts not in groups:
                groups[ts] = []
            groups[ts].append(path)

        return groups

    def load(self, file_paths: List[str]) -> bool:
        """
        Load Fengyun satellite data from file paths.

        Uses FY4Reader (h5py) for L1 HDF5 data and FY4L2Reader (xarray)
        for L2 NetCDF products — no satpy required.

        Args:
            file_paths: List of paths to satellite data files

        Returns:
            True if loading successful
        """
        if not file_paths:
            logger.error("No file paths provided")
            return False

        try:
            # Auto-detect satellite variant from filenames
            for fp in file_paths:
                name = os.path.basename(fp).upper()
                if 'FY4B' in name or 'FY-4B' in name:
                    self._satellite_variant = 'FY4B'
                    self.SATELLITE_TYPE = SatelliteType.FENGYUN_4B
                    break
                if 'FY4A' in name or 'FY-4A' in name:
                    self._satellite_variant = 'FY4A'
                    self.SATELLITE_TYPE = SatelliteType.FENGYUN_4A
                    break

            # Detect product level
            self._current_level = self._detect_product_level(file_paths)
            logger.info(f"[FY4] Product level: {self._current_level.value}")

            # Group files by time
            time_groups = self._group_files_by_time(file_paths)
            logger.info(f"[FY4] Time groups: {len(time_groups)}")

            if not time_groups:
                logger.error("[FY4] No valid time groups found")
                return False

            primary_time = next(iter(time_groups))
            primary_files = time_groups[primary_time]
            primary_file = primary_files[0]

            # Release previous reader
            self._close_readers()

            if self._current_level == ProductLevel.L2:
                # L2 NetCDF: use xarray-based reader
                from ..io import FY4L2Reader
                self._l2_reader = FY4L2Reader(primary_file)
                self._area_def = self._l2_reader.get_area_definition()
                self._build_l2_dataset_map()
                logger.info(f"[FY4] L2 loaded: {list(self._dataset_map.keys())[:5]}")
            else:
                # L1 HDF5: use h5py-based reader
                from ..io import FY4Reader
                self._reader = FY4Reader(primary_file, satellite=self._satellite_variant)
                self._area_def = self._reader.get_area_definition()
                self._build_dataset_map()
                logger.info(f"[FY4] L1 loaded: {self._reader.available_bands()}")

            self._is_loaded = True
            self._time_groups = time_groups
            return True

        except Exception as e:
            logger.error(f"[FY4] Failed to load files: {e}")
            import traceback
            traceback.print_exc()
            self._is_loaded = False
            return False

    def _build_dataset_map(self) -> None:
        """Build mapping from canonical names (VIS006) to reader band IDs (C01)."""
        self._dataset_map = {}
        self._band_catalog = {}

        if self._reader is None:
            return

        for band_id in self._reader.available_bands():
            canonical = self._canonical_from_dataset(band_id)
            self._dataset_map[canonical] = band_id

            band_info = BandInfo(
                canonical_name=canonical,
                display_name=band_id,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

        logger.debug(f"[FY4] Dataset map: {self._dataset_map}")

    def _build_l2_dataset_map(self) -> None:
        """Build dataset map for L2 NetCDF variables."""
        self._dataset_map = {}
        self._band_catalog = {}

        if self._l2_reader is None:
            return

        for var_name in self._l2_reader.available_variables():
            canonical = var_name.upper()
            self._dataset_map[canonical] = var_name

            band_info = BandInfo(
                canonical_name=canonical,
                display_name=var_name,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

    def _canonical_from_dataset(self, dataset_name: str) -> str:
        """Convert reader band ID (C01, Channel01) to canonical name (VIS006)."""
        # C## pattern (FY-4B style, also used by our FY4Reader)
        match = re.search(r'^C(\d{2})$', dataset_name, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return self._channel_to_canonical(num)

        # Channel## pattern (FY-4A satpy legacy)
        match = re.search(r'Channel(\d{2})', dataset_name, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return self._channel_to_canonical(num)

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
        """Extract canonical band name from display name like 'IR133 (13.5 μm)'."""
        match = re.match(r'^([A-Z0-9]+)', display_name.strip())
        if match:
            return match.group(1)
        return display_name.split()[0]

    def _resolve_dataset_name(self, band_name: str) -> str:
        """
        Resolve a band name to a reader band ID (C01..C14).

        Accepts: canonical names (IR133), short names (C14), channel names (Channel14).
        Returns: reader band ID like 'C14', or the input unchanged as last resort.
        """
        available = (self._reader.available_bands()
                     if self._reader is not None
                     else list(self._dataset_map.values()))

        # Direct match against available IDs
        if band_name in available:
            return band_name

        # Canonical name → band ID via dataset_map
        if band_name in self._dataset_map:
            ds_name = self._dataset_map[band_name]
            if ds_name in available:
                return ds_name

        # Reverse lookup
        for canonical, ds_name in self._dataset_map.items():
            if ds_name == band_name:
                return ds_name

        # C## → try available list
        match = re.match(r'^C(\d{2})$', band_name, re.IGNORECASE)
        if match:
            cid = f'C{int(match.group(1)):02d}'
            if cid in available:
                return cid

        # Channel## → C##
        match = re.match(r'^Channel(\d{2})$', band_name, re.IGNORECASE)
        if match:
            cid = f'C{int(match.group(1)):02d}'
            if cid in available:
                return cid

        # Numeric-only pattern
        match = re.search(r'(\d{1,2})', band_name)
        if match:
            cid = f'C{int(match.group(1)):02d}'
            if cid in available:
                return cid

        logger.warning(f"[FY4] Could not resolve band '{band_name}', using as-is")
        return band_name

    def unload(self) -> None:
        """Release loaded resources."""
        self._close_readers()
        self._dataset_map.clear()
        self._band_catalog.clear()
        self._area_def = None
        self._is_loaded = False
        logger.info("[FY4] Driver resources released")

    def _close_readers(self) -> None:
        """Close reader handles."""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
        if self._l2_reader is not None:
            try:
                self._l2_reader.close()
            except Exception:
                pass
            self._l2_reader = None

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded data.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array, area_definition)
        """
        if not self._is_loaded:
            raise ValueError("No data loaded")
        if self._current_level == ProductLevel.L2 and self._l2_reader is None:
            raise ValueError("L2 reader not initialised")
        if self._current_level != ProductLevel.L2 and self._reader is None:
            raise ValueError("L1 reader not initialised")

        try:
            # Resolve band names to reader band IDs
            band_ids = []
            for band in params.bands:
                clean = self._extract_canonical_from_display(band)
                bid = self._resolve_dataset_name(clean)
                band_ids.append(bid)

            logger.info(f"[FY4] Requested bands: {params.bands} → {band_ids}")

            return self._request_image_pipeline(band_ids, params)

        except Exception as e:
            logger.error(f"[FY4] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _request_image_pipeline(self, band_ids: List[str],
                                 params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Internal image-generation pipeline.

        Loads band data via the direct reader, resamples via pyresample,
        then normalises and composites.

        Args:
            band_ids: List of reader band IDs (C01..C14) or L2 variable names.
            params:   Processing parameters.

        Returns:
            Tuple of (H×W×3 float32 image, area_definition).
        """
        from ..geometry import create_target_area

        source_area = self._area_def

        # Determine target projection area
        target_area = None
        if params.output_proj != 'geostationary_native':
            custom_width = custom_height = None
            if params.output_size:
                custom_width  = int(params.output_size[0])
                custom_height = int(params.output_size[1])
            target_area = create_target_area(
                params.output_proj,
                source_area=source_area,
                custom_width=custom_width,
                custom_height=custom_height,
            )

        # Define band loader
        def load_band(band_id: str) -> np.ndarray:
            """Load calibrated band data as float32 numpy array."""
            try:
                if self._current_level == ProductLevel.L2:
                    return self._l2_reader.load_variable(band_id)
                else:
                    return self._reader.load_band(band_id)
            except Exception as exc:
                logger.error(f"[FY4] load_band({band_id}) failed: {exc}")
                return np.zeros((1, 1), dtype=np.float32)

        # Load all bands
        band_data: Dict[str, np.ndarray] = {}
        for bid in band_ids:
            band_data[bid] = load_band(bid)
            logger.debug(f"[FY4] Loaded {bid}: shape={band_data[bid].shape}")

        # Resample to target area if required
        if target_area is not None and source_area is not None:
            band_data = self._resample_bands(band_data, source_area, target_area,
                                             params.resample_method)
            result_area = target_area
        else:
            result_area = source_area

        # Composite / process
        if len(band_ids) == 3:
            r = band_data.get(band_ids[0], np.zeros((1, 1), dtype=np.float32))
            g = band_data.get(band_ids[1], np.zeros((1, 1), dtype=np.float32))
            b = band_data.get(band_ids[2], np.zeros((1, 1), dtype=np.float32))
            img = self._process_rgb(r, g, b, params.gamma)
        else:
            raw = band_data.get(band_ids[0], np.zeros((1, 1), dtype=np.float32))
            img = self._process_single(raw, params.gamma, band_ids[0])

        return img, result_area

    def _resample_bands(
        self,
        band_data: Dict[str, np.ndarray],
        source_area,
        target_area,
        method: str = 'nearest',
    ) -> Dict[str, np.ndarray]:
        """
        Resample all bands from source_area to target_area via pyresample.

        Args:
            band_data:   Dict of band_id → 2-D float32 array (H×W).
            source_area: Source pyresample AreaDefinition.
            target_area: Target pyresample AreaDefinition.
            method:      Resampling method ('nearest' or 'bilinear').

        Returns:
            Dict of band_id → resampled float32 array.
        """
        try:
            from pyresample.kd_tree import resample_nearest
        except ImportError:
            logger.warning("[FY4] pyresample not available; skipping resampling")
            return band_data

        # bilinear lives in pyresample.bilinear (not kd_tree) in modern pyresample
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
                    out = _bilinear_fn(
                        arr, source_area, target_area,
                        radius=50000, fill_value=np.nan
                    )
                else:
                    out = resample_nearest(
                        source_area, arr, target_area,
                        radius_of_influence=50000,
                        fill_value=np.nan
                    )
                resampled[bid] = out.astype(np.float32)
            except Exception as exc:
                logger.warning(f"[FY4] Resample failed for {bid}: {exc}")
                resampled[bid] = arr
        return resampled

    def _process_rgb(self, r: np.ndarray, g: np.ndarray, b: np.ndarray,
                     gamma: float) -> np.ndarray:
        """Process RGB bands: percentile normalisation + gamma + stack."""
        def norm(arr: np.ndarray) -> np.ndarray:
            valid = arr[np.isfinite(arr)]
            if valid.size == 0:
                return np.zeros_like(arr)
            lo, hi = np.percentile(valid, 2), np.percentile(valid, 98)
            if hi > lo:
                out = (arr - lo) / (hi - lo)
            else:
                out = np.zeros_like(arr)
            return np.clip(out, 0.0, 1.0)

        r, g, b = norm(r), norm(g), norm(b)
        if gamma != 1.0:
            r = np.power(np.clip(r, 0, 1), 1.0 / gamma)
            g = np.power(np.clip(g, 0, 1), 1.0 / gamma)
            b = np.power(np.clip(b, 0, 1), 1.0 / gamma)

        img = np.stack([r, g, b], axis=-1)
        return np.nan_to_num(img, nan=0.0).astype(np.float32)

    def _process_single(self, data: np.ndarray, gamma: float,
                         band_id: str = '') -> np.ndarray:
        """Process single band: normalisation + gamma + grayscale→RGB."""
        # Detect thermal bands by channel number
        is_thermal = False
        m = re.match(r'^C(\d{2})$', band_id)
        if m and int(m.group(1)) >= 7:
            is_thermal = True

        valid = data[np.isfinite(data)]
        if valid.size == 0:
            norm = np.zeros_like(data)
        elif is_thermal:
            # BT in K: fixed physical range
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
            'sensor': 'AGRI',
            'satellite_type': self._satellite_variant,
            'product_level': self._current_level.value,
            'n_bands': len(self._dataset_map),
            'is_loaded': self._is_loaded,
        }

        if self._reader is not None:
            reader_meta = self._reader.get_metadata()
            meta.update({
                'start_time': reader_meta.get('start_time', 'N/A'),
                'data_format': 'L1_HDF5',
            })
        elif self._l2_reader is not None:
            reader_meta = self._l2_reader.get_metadata()
            meta.update({
                'start_time': reader_meta.get('start_time', 'N/A'),
                'data_format': 'L2_NetCDF',
            })

        return meta

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for this satellite."""
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """Get file groups organised by timestamp."""
        groups = self._group_files_by_time(file_paths)
        return list(groups.values())

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_image_pipeline(self, bands: List[str],
                               output_path: str,
                               proj_name: str = 'plate_carree_china',
                               export_format: str = 'png',
                               gamma: float = 1.0,
                               region: str = 'china',
                               calibration: bool = False) -> Dict:
        """
        Export image to PNG or GeoTIFF.

        Args:
            bands: List of band names (canonical or display form)
            output_path: Destination file path
            proj_name: Projection name for resampling
            export_format: 'png' or 'geotiff'
            gamma: Gamma correction
            region: Geographic region for cropping
            calibration: (unused; data is always calibrated by FY4Reader)

        Returns:
            Dict with 'status' and 'path'.
        """
        if not self._is_loaded:
            raise ValueError("No data loaded")

        try:
            gc.collect()

            # Resolve band names
            band_ids = []
            for band in bands:
                clean = self._extract_canonical_from_display(band)
                bid = self._resolve_dataset_name(clean)
                band_ids.append(bid)

            logger.info(f"[FY4 Export] Bands: {bands} → {band_ids}")

            # Determine export area
            from ..geometry import create_target_area, ProjectionFactory
            target_area = None

            if proj_name != 'geostationary_native':
                reg_info = {
                    'china':        (70, 142, 15, 55),
                    'east_asia':    (70, 150, 0, 60),
                    'southeast_asia': (90, 140, -10, 25),
                }
                if region in reg_info:
                    west, east, south, north = reg_info[region]
                    resolution = 0.05
                    width  = int((east - west) / resolution)
                    height = int((north - south) / resolution)
                    target_area = ProjectionFactory.create_from_extent(
                        name=f'export_{region}',
                        west=west, east=east, south=south, north=north,
                        resolution=resolution
                    )
                else:
                    target_area = create_target_area(proj_name)

            # Load all bands
            band_data: Dict[str, np.ndarray] = {}
            for bid in band_ids:
                try:
                    if self._current_level == ProductLevel.L2:
                        band_data[bid] = self._l2_reader.load_variable(bid)
                    else:
                        band_data[bid] = self._reader.load_band(bid)
                except Exception as exc:
                    logger.warning(f"[FY4 Export] load {bid} failed: {exc}")
                    band_data[bid] = np.zeros((1, 1), dtype=np.float32)

            # Resample
            if target_area is not None and self._area_def is not None:
                band_data = self._resample_bands(band_data, self._area_def,
                                                 target_area, 'nearest')

            # Composite
            if len(band_ids) == 3:
                r = band_data.get(band_ids[0], np.zeros((1, 1)))
                g = band_data.get(band_ids[1], np.zeros((1, 1)))
                b = band_data.get(band_ids[2], np.zeros((1, 1)))
                img = self._process_rgb(r, g, b, gamma)
            else:
                raw = band_data.get(band_ids[0], np.zeros((1, 1)))
                img = self._process_single(raw, gamma, band_ids[0])

            img = np.clip(img, 0.0, 1.0).astype(np.float32)

            # Save
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            if export_format == 'png':
                from PIL import Image as PILImage
                img_u8 = (img * 255).astype(np.uint8)
                PILImage.fromarray(img_u8, mode='RGB').save(output_path)
            elif export_format == 'geotiff':
                self._save_geotiff_with_pipeline(img, output_path, target_area or self._area_def)

            del band_data, img
            gc.collect()

            return {'status': 'success', 'path': output_path}

        except Exception as exc:
            logger.error(f"[FY4 Export] Failed: {exc}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(exc)}

    def _save_geotiff_with_pipeline(self, img: np.ndarray,
                                    output_path: str,
                                    area_def: Any) -> None:
        """Save image as GeoTIFF."""
        try:
            from osgeo import gdal, osr

            if img.ndim == 3:
                height, width, n_bands = img.shape
            else:
                height, width = img.shape
                n_bands = 1

            driver = gdal.GetDriverByName('GTiff')
            options = ['COMPRESS=LZW', 'TILED=YES', 'BLOCKXSIZE=256', 'BLOCKYSIZE=256']
            out_ds = driver.Create(output_path, width, height, n_bands,
                                   gdal.GDT_Float32, options=options)

            if area_def is not None and hasattr(area_def, 'area_extent'):
                extent = area_def.area_extent
                x_res = (extent[2] - extent[0]) / width
                y_res = (extent[3] - extent[1]) / height
                out_ds.SetGeoTransform((extent[0], x_res, 0, extent[3], 0, -y_res))

                srs = osr.SpatialReference()
                srs.ImportFromProj4('+proj=longlat +datum=WGS84')
                out_ds.SetProjection(srs.ExportToWkt())

            for i in range(n_bands):
                band_arr = img[:, :, i] if img.ndim == 3 else img
                out_ds.GetRasterBand(i + 1).WriteArray(band_arr)

            out_ds.FlushCache()
            out_ds = None

        except ImportError:
            logger.warning("[FY4] GDAL not available; cannot save GeoTIFF")
        except Exception as exc:
            logger.error(f"[FY4] GeoTIFF save failed: {exc}")

    @property
    def satellite_variant(self) -> str:
        """Get the satellite variant."""
        return self._satellite_variant

    def __repr__(self) -> str:
        return f"FengYunDriver(satellite={self._satellite_variant}, level={self._current_level.value})"
