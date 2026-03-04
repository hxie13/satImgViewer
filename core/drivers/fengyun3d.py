"""
FY3D MERSI Satellite Driver

Implementation for Fengyun-3D (FY3D) satellite MERSI L1 data support.
Supports MERSI-2 (Medium Resolution Spectral Imager) data in HDF5 format.

Filename pattern: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_1000M_MS.HDF
GEO file pattern: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_GEO1K_MS.HDF

satpy dependency removed: data is read directly via core.io.FY3DReader
(h5py + Planck calibration).
"""
import os
import re
import glob
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
from .polar_base import BasePolarDriver

from core.config import get_satellite_band_map, get_thermal_bands  # noqa: E402

logger = logging.getLogger(__name__)


def _scale_geo_to_data(lons: np.ndarray, lats: np.ndarray,
                       target_shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Resample lon/lat arrays to match a band's pixel shape.

    Used when the stored geolocation has a different resolution than the band
    data (e.g. geo at 1 km but band at 250 m, or geo at 250 m but band at 1 km).
    Uses nearest-neighbour subsampling / repetition along each axis.
    """
    gh, gw = lons.shape
    th, tw = target_shape

    if gh == th and gw == tw:
        return lons, lats

    # Build index arrays for nearest-neighbour rescaling
    row_idx = np.clip(np.round(np.linspace(0, gh - 1, th)).astype(int), 0, gh - 1)
    col_idx = np.clip(np.round(np.linspace(0, gw - 1, tw)).astype(int), 0, gw - 1)
    lons_scaled = lons[np.ix_(row_idx, col_idx)]
    lats_scaled = lats[np.ix_(row_idx, col_idx)]
    logger.info("[FY3D] Scaled geo (%d,%d) → (%d,%d) to match band",
                gh, gw, th, tw)
    return lons_scaled, lats_scaled


# =============================================================================
# Band Mapping Configuration  (sourced from core.config — single source of truth)
# =============================================================================

MERSI_L1_BANDS: Dict[str, Dict[str, Any]] = get_satellite_band_map('MERSI_L1')
THERMAL_BANDS: set = get_thermal_bands('MERSI_L1')

# FY3D satellite coverage (global coverage with sun-synchronous orbit)
SATELLITE_COVERAGE = {
    SatelliteType.FENGYUN_3D: (-180, 180, -90, 90),  # Global
}


class FengYun3DDriver(BasePolarDriver):
    """
    Driver for Fengyun-3D (FY3D) satellite MERSI sensor.

    Supports:
    - FY3D MERSI-2 L1 data in HDF5 format
    - 25 spectral bands (4 at 250m, 15 at 1000m, 6 thermal at 1000m)
    - Global coverage (sun-synchronous satellite)
    - Swath-to-grid resampling via pyresample
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.FENGYUN_3D
    SUPPORTED_FORMATS = ['.hdf', '.h5', '.nc', '.HDF', '.H5']
    DEFAULT_RESAMPLE_RESOLUTION_M = 1000

    def __init__(self, config: Optional[Dict] = None):
        """Initialize FY3D MERSI driver."""
        super().__init__(config)
        self._reader = None          # FY3DReader instance
        self._current_level = ProductLevel.L1
        self._dataset_names: List[str] = []
        self._primary_file_path: Optional[str] = None
        self._swath_extent: Optional[Tuple[float, float, float, float]] = None
        self._swath_overlaps_china: Optional[bool] = None

    def _init_driver(self) -> None:
        """Initialize driver-specific resources."""
        pass

    def identify(self, file_path: str) -> bool:
        """Check if file is compatible with FY3D MERSI driver."""
        filename = os.path.basename(file_path).upper()
        if 'FY3D' in filename and 'MERSI' in filename:
            return True
        if 'MERSI' in filename:
            return True
        return False

    def get_band_mapping(self) -> Dict[str, str]:
        """Get mapping from canonical names to satellite-specific dataset names."""
        return {canonical: info['name'] for canonical, info in MERSI_L1_BANDS.items()}

    def get_available_bands(self) -> List[BandInfo]:
        """Get list of available bands with standardized information."""
        # Return only bands actually found in the loaded file
        if self._band_catalog:
            return list(self._band_catalog.values())

        # No file loaded yet — return full config list as a preview
        bands = []
        for canonical, info in MERSI_L1_BANDS.items():
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=f"{canonical} ({info['wavelength']} - {info['type']})",
                wavelength=info['wavelength'],
                resolution=info['resolution'],
                is_thermal=canonical in THERMAL_BANDS
            )
            bands.append(band_info)
        return bands

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, file_paths: List[str]) -> bool:
        """
        Load FY3D MERSI satellite data from file paths.

        Uses FY3DReader (h5py) for direct HDF5 reading — no satpy required.

        Args:
            file_paths: List of paths to HDF5 data files

        Returns:
            True if loading successful
        """
        if not file_paths:
            logger.error("No file paths provided")
            return False

        try:
            # Filter out physically broken HDF/H5 files
            valid_file_paths = self._filter_readable_input_files(file_paths)
            if not valid_file_paths:
                logger.error("[FY3D] No readable files left after validation")
                return False

            # Select primary radiance file
            primary_file = self._select_primary_file(valid_file_paths)
            if primary_file is None:
                logger.error("[FY3D] No valid FY3D MERSI files found")
                return False

            self._primary_file_path = primary_file
            logger.info(f"[FY3D] Primary file: {os.path.basename(primary_file)}")

            # Close previous reader
            self._close_reader()

            # Instantiate direct HDF5 reader (auto-locates GEO file)
            from ..io import FY3DReader
            self._reader = FY3DReader(primary_file)

            self._dataset_names = self._reader.available_bands()
            self._build_dataset_map()

            # Cache lon/lat immediately if GEO file is available
            lons, lats = self._reader.get_lonlats()
            if lons is not None:
                self._swath_lons = lons
                self._swath_lats = lats
                self._is_swath = True
                self._update_swath_coverage_cache()
                logger.info(f"[FY3D] GEO loaded: lons.shape={lons.shape}")
            else:
                self._is_swath = True   # FY-3D is always swath
                self._swath_extent = None
                self._swath_overlaps_china = None
                logger.warning("[FY3D] GEO file not found — lon/lat unavailable")

            self._is_loaded = True
            logger.info(f"[FY3D] Loaded {len(self._dataset_names)} bands: {self._dataset_names}")
            return True

        except Exception as e:
            logger.error(f"[FY3D] Failed to load files: {e}")
            import traceback
            traceback.print_exc()
            self._is_loaded = False
            return False

    def _filter_readable_input_files(self, file_paths: List[str]) -> List[str]:
        """Remove physically unreadable HDF/H5 files before reader creation."""
        valid: List[str] = []
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext not in {'.hdf', '.h5'}:
                valid.append(path)
                continue
            try:
                import h5py
                with h5py.File(path, 'r'):
                    pass
                valid.append(path)
            except Exception as exc:
                logger.warning(f"[FY3D] Skip unreadable file: {os.path.basename(path)} ({exc})")

        return valid

    def _select_primary_file(self, file_paths: List[str]) -> Optional[str]:
        """Select the primary radiance file (HDF5 with MERSI in name)."""
        # Prefer files explicitly named as MERSI HDF5
        radiance_candidates: List[str] = []
        for path in file_paths:
            fname = os.path.basename(path).upper()
            ext = os.path.splitext(fname)[1]
            if ext in {'.HDF', '.H5'} and 'MERSI' in fname:
                # Exclude GEO files (they contain Lon/Lat, not radiance)
                if not any(k in fname for k in ('GEO1K', 'GEODK', 'GEO250', '_GEO_')):
                    radiance_candidates.append(path)

        # Prefer radiance files with a usable dedicated GEO match.
        if radiance_candidates:
            try:
                import h5py
                from ..io.fy3d_reader import _find_geo_file

                def _geo_has_lonlat(geo_path: str) -> bool:
                    try:
                        with h5py.File(geo_path, 'r') as gf:
                            if 'Geolocation' in gf and hasattr(gf['Geolocation'], 'keys'):
                                grp = gf['Geolocation']
                                return ('Longitude' in grp and 'Latitude' in grp)
                            return ('Longitude' in gf and 'Latitude' in gf)
                    except Exception:
                        return False

                for path in radiance_candidates:
                    geo = _find_geo_file(path)
                    if geo and _geo_has_lonlat(geo):
                        logger.info("[FY3D] Prefer file with dedicated GEO: %s", os.path.basename(path))
                        return path
            except Exception:
                # Any failure in preference probing should not block loading.
                pass

            return radiance_candidates[0]

        # Fallback: first HDF5 file
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext in {'.hdf', '.h5', '.nc'}:
                return path

        return file_paths[0] if file_paths else None

    def _close_reader(self) -> None:
        """Release reader resources."""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None

    def _update_swath_coverage_cache(self) -> None:
        """
        Cache swath extent and a fast China-overlap estimate from lon/lat arrays.

        This keeps UI-side risk checks lightweight when switching to
        plate_carree_china projection.
        """
        self._swath_extent = None
        self._swath_overlaps_china = None

        if self._swath_lons is None or self._swath_lats is None:
            return

        try:
            self._swath_extent = self._extent_from_swath(
                self._swath_lons,
                self._swath_lats,
                padding_deg=0.0,
            )
        except Exception as exc:
            logger.debug("[FY3D] Failed to derive swath extent: %s", exc)
            self._swath_extent = None

        try:
            # Down-sample to cap cost at roughly 200k sample points.
            total_points = int(self._swath_lons.size)
            step = max(1, int(np.sqrt(max(1, total_points // 200_000))))
            lons_sample = self._swath_lons[::step, ::step]
            lats_sample = self._swath_lats[::step, ::step]
            valid = np.isfinite(lons_sample) & np.isfinite(lats_sample)
            if not np.any(valid):
                self._swath_overlaps_china = None
                return

            in_china = (
                valid &
                (lons_sample >= 70.0) & (lons_sample <= 142.0) &
                (lats_sample >= 15.0) & (lats_sample <= 55.0)
            )
            self._swath_overlaps_china = bool(np.any(in_china))
        except Exception as exc:
            logger.debug("[FY3D] Failed to estimate China overlap: %s", exc)
            self._swath_overlaps_china = None

    def _build_dataset_map(self) -> None:
        """Build mapping from canonical names (B01) to reader band IDs."""
        self._dataset_map = {}
        self._band_catalog = {}

        for band_id in self._dataset_names:  # e.g. 'B01'..'B25'
            canonical = self._canonical_from_dataset(band_id, self._dataset_names)
            self._dataset_map[canonical] = band_id

            # Also add reverse (band_id → band_id) for direct lookup
            self._dataset_map[band_id] = band_id

            band_info = BandInfo(
                canonical_name=canonical,
                display_name=band_id,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

        logger.debug(f"[FY3D] Dataset map: {self._dataset_map}")

    def _canonical_from_dataset(self, dataset_name: str, available: List[str]) -> str:
        """
        Convert dataset name to canonical name (B01..B25).

        Handles our FY3DReader band IDs (B01..B25) as well as
        HDF5 group names (EV_250_Ref_Band1, EV_1000_RefSB, etc.).
        """
        orig = dataset_name
        _stripped = dataset_name.strip()

        # Fast path: already B## format
        if re.match(r'^B\d{2}$', _stripped):
            return _stripped

        # Pure integer string '1'..'25' (satpy legacy)
        if re.match(r'^\d{1,2}$', _stripped):
            num = int(_stripped)
            if 1 <= num <= 25:
                return f'B{num:02d}'

        # Pattern matching for HDF5 naming conventions
        patterns = [
            (r'EV_250[_-]Ref_?Band(\d{1,2})',   lambda m: f'B{int(m.group(1)):02d}'),
            (r'EV_250[_-]RefSB(\d{2})',           lambda m: f'B{m.group(1)}'),
            (r'EV_1000[_-]RefSB',                 None),  # 3-D, handled by index
            (r'EV_1000[_-]Emissive(\d{2})',       lambda m: f'B{int(m.group(1))+19:02d}'),
            (r'EV_1000[_-]RefSB(\d{2})',          lambda m: f'B{m.group(1)}'),
            (r'RefSB(\d{2})',                     lambda m: f'B{m.group(1)}'),
            (r'Emissive(\d{2})',                  lambda m: f'B{int(m.group(1))+19:02d}'),
            (r'_B?(\d{2})$',                      lambda m: f'B{m.group(1)}'),
            (r'^B?(\d{2})[_-]',                  lambda m: f'B{m.group(1)}'),
            (r'\b(\d{2})\b',                      lambda m: f'B{m.group(1)}'),
        ]

        for pattern, mapper in patterns:
            if mapper is None:
                continue
            match = re.search(pattern, dataset_name, re.IGNORECASE)
            if match:
                canonical = mapper(match)
                if re.match(r'^B\d{2}$', canonical):
                    num = int(canonical[1:])
                    if 1 <= num <= 25:
                        logger.debug(f"[FY3D] {orig} → {canonical}")
                        return canonical

        # Number extraction fallback
        m = re.search(r'(\d{1,2})', dataset_name)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 25:
                return f'B{num:02d}'

        return dataset_name

    def _extract_canonical_from_display(self, display_name: str) -> str:
        """Extract canonical band name from display name like 'B04 (0.86 µm - Reflective)'."""
        match = re.match(r'^([A-Z][A-Z0-9]+)', display_name.strip())
        if match:
            return match.group(1)
        return display_name.split()[0]

    def _resolve_dataset_name(self, band_name: str) -> Optional[str]:
        """
        Resolve a band name to a reader band ID (B01..B25).

        Accepts canonical names (B04), display names, or HDF5 patterns.
        """
        available = self._reader.available_bands() if self._reader else list(self._dataset_map.values())

        # Direct match
        if band_name in available:
            return band_name

        # Strip display-name suffix: 'B03 (0.65 μm - visible)' → 'B03'
        stripped = self._extract_canonical_from_display(band_name)
        if stripped != band_name:
            if stripped in available:
                return stripped
            band_name = stripped  # continue resolution with clean name

        # Canonical → band ID via dataset_map
        if band_name in self._dataset_map:
            bid = self._dataset_map[band_name]
            if bid in available:
                return bid

        # Try converting to B## format
        canonical = self._canonical_from_dataset(band_name, available)
        if canonical in available:
            return canonical
        if canonical in self._dataset_map:
            bid = self._dataset_map[canonical]
            if bid in available:
                return bid

        # Contains-search
        for avail in available:
            if band_name.upper() in avail.upper() or avail.upper() in band_name.upper():
                return avail

        logger.warning(f"[FY3D] Could not resolve band '{band_name}'")
        return None

    def load_files(self, file_paths: List[str], **kwargs) -> bool:
        """Satisfy BasePolarDriver abstract contract."""
        return self.load(file_paths)

    def unload(self) -> None:
        """Release loaded resources."""
        self._close_reader()
        self._dataset_map.clear()
        self._band_catalog.clear()
        self._dataset_names.clear()
        self._primary_file_path = None
        self._swath_lons = None
        self._swath_lats = None
        self._swath_extent = None
        self._swath_overlaps_china = None
        self._is_swath = False
        self._is_loaded = False
        logger.info("[FY3D] Driver resources released")

    # ------------------------------------------------------------------
    # Image Generation
    # ------------------------------------------------------------------

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded FY3D MERSI data.

        FY-3D is always a swath satellite, so data is always resampled to a
        regular lon/lat grid via pyresample before display.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array H×W×3, area_definition)
        """
        if not self._is_loaded or self._reader is None:
            raise ValueError("[FY3D] No data loaded")

        try:
            # Resolve band names → reader band IDs
            band_ids: List[str] = []
            for band in params.bands:
                clean = self._extract_canonical_from_display(band)
                bid = self._resolve_dataset_name(clean)
                if bid:
                    band_ids.append(bid)

            logger.info(f"[FY3D] Requested: {params.bands} → {band_ids}")

            if not band_ids:
                raise ValueError(f"[FY3D] Could not resolve any bands from: {params.bands}")

            # Ensure lon/lat is loaded
            if self._swath_lons is None:
                lons, lats = self._reader.get_lonlats()
                if lons is not None:
                    self._swath_lons = lons
                    self._swath_lats = lats
                    self._update_swath_coverage_cache()

            if self._swath_lons is None:
                raise ValueError("[FY3D] Geolocation (lon/lat) not available — GEO file required")

            # Determine calibration and load band data
            from core.config import get_thermal_bands
            thermal_set = get_thermal_bands('MERSI_L1')

            band_data: Dict[str, np.ndarray] = {}
            for bid in band_ids:
                canonical = self._canonical_from_dataset(bid, band_ids)
                cal = 'brightness_temperature' if canonical in thermal_set else 'reflectance'
                arr = self._reader.load_band(bid, calibration=cal)
                # Validate BT values
                if canonical in thermal_set:
                    arr = self._convert_to_brightness_temp(bid, arr)
                band_data[bid] = arr
                logger.debug(
                    f"[FY3D] {bid} ({cal}): shape={arr.shape}, "
                    f"min={np.nanmin(arr):.3f}, max={np.nanmax(arr):.3f}"
                )

            # Determine target area for resampling
            from core.geometry import ProjectionFactory
            target_area = None
            effective_proj = params.output_proj

            # geostationary_native is meaningless for polar swath — use auto-extent grid
            if effective_proj == 'geostationary_native':
                effective_proj = None

            if effective_proj is not None:
                custom_w = custom_h = None
                if params.output_size:
                    custom_w = int(params.output_size[0])
                    custom_h = int(params.output_size[1])
                target_area = ProjectionFactory.create_target_area(
                    effective_proj,
                    custom_width=custom_w,
                    custom_height=custom_h,
                    source_area=None,
                )

            # Build target area from swath extent if not already defined
            if target_area is None:
                lons_valid = self._swath_lons[np.isfinite(self._swath_lons)]
                lats_valid = self._swath_lats[np.isfinite(self._swath_lats)]
                if len(lons_valid) > 0:
                    west  = float(np.min(lons_valid))
                    east  = float(np.max(lons_valid))
                    south = float(np.min(lats_valid))
                    north = float(np.max(lats_valid))
                    from pyresample import geometry as _geom
                    custom_w = int(params.output_size[0]) if params.output_size else None
                    custom_h = int(params.output_size[1]) if params.output_size else None
                    # ~5 km resolution, capped at 2048 px to keep resampling fast
                    _res = 0.05
                    _w = custom_w or min(2048, max(1, int((east - west) / _res)))
                    _h = custom_h or min(2048, max(1, int((north - south) / _res)))
                    target_area = _geom.AreaDefinition(
                        'fy3d_swath_grid', 'FY3D swath grid (5 km)',
                        'longlat', {'proj': 'longlat', 'datum': 'WGS84'},
                        _w, _h,
                        area_extent=(west, south, east, north),
                    )
                    logger.info(f"[FY3D] Auto extent: ({west:.1f},{south:.1f})→({east:.1f},{north:.1f})")

            # Resample each band from swath → regular grid
            area_def = None
            swath_failed = False
            for bid in band_ids:
                arr = band_data[bid]
                # Adapt lon/lat to match band resolution if shapes differ
                lons_use = self._swath_lons
                lats_use = self._swath_lats
                if lons_use.shape != arr.shape:
                    lons_use, lats_use = _scale_geo_to_data(lons_use, lats_use, arr.shape)
                try:
                    resampled, area_def = self.resample_swath_to_grid(
                        arr,
                        lons_use,
                        lats_use,
                        target_resolution_m=5000,  # 5 km — prevents OOM on global swaths
                        target_extent=(
                            target_area.area_extent[0],
                            target_area.area_extent[2],
                            target_area.area_extent[1],
                            target_area.area_extent[3],
                        ) if target_area else None,
                        method=params.resample_method,
                    )
                    band_data[bid] = resampled
                    logger.debug(f"[FY3D] Resampled {bid}: {arr.shape} → {resampled.shape}")
                except Exception as exc:
                    logger.error(f"[FY3D] Resample failed for {bid}: {exc}")
                    swath_failed = True
                    # keep original (unresampled) as fallback

            # Composite / process
            if len(band_ids) == 3:
                img = self._process_rgb_composite(band_ids, band_data, params.gamma)
            elif len(band_ids) == 1:
                img = self._process_single_band(band_ids[0], band_data, params.gamma)
            else:
                rgb_ids = band_ids[:3] if len(band_ids) >= 3 else band_ids
                if len(rgb_ids) >= 3:
                    img = self._process_rgb_composite(rgb_ids, band_data, params.gamma)
                else:
                    img = self._process_single_band(band_ids[0], band_data, params.gamma)

            return img, (None if swath_failed else area_def)

        except Exception as exc:
            logger.error(f"[FY3D] Failed to generate image: {exc}")
            import traceback
            traceback.print_exc()
            raise

    def _convert_to_brightness_temp(self, band_id: str, data: np.ndarray) -> np.ndarray:
        """
        Validate brightness temperature array.

        FY3DReader already applies Planck inversion; this method just confirms
        values are in the physical BT range and applies a linear rescale fallback
        if they are not (e.g. reader got raw DN instead of BT).

        Args:
            band_id: Band identifier (for logging)
            data:    Data array from reader

        Returns:
            float32 BT array in K
        """
        BT_MIN, BT_MAX = 170.0, 340.0
        arr_min = float(np.nanmin(data)) if np.any(np.isfinite(data)) else 0.0
        arr_max = float(np.nanmax(data)) if np.any(np.isfinite(data)) else 0.0

        if BT_MIN <= arr_min and arr_max <= BT_MAX:
            return data.astype(np.float32)

        logger.warning(
            f"[FY3D] {band_id} values ({arr_min:.2f}~{arr_max:.2f}) outside BT range; "
            "applying linear rescale fallback"
        )
        if arr_max > arr_min:
            norm = (data - arr_min) / (arr_max - arr_min)
            return (norm * (BT_MAX - BT_MIN) + BT_MIN).astype(np.float32)
        return np.full_like(data, 250.0, dtype=np.float32)

    def _align_bands(self, band_data: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """Align bands of different resolutions to a common (finest) grid."""
        if not band_data:
            return band_data

        shapes = [arr.shape for arr in band_data.values()]
        target_shape = max(shapes, key=lambda s: s[0] * s[1])
        logger.debug(f"[FY3D] Target shape for alignment: {target_shape}")

        from scipy.ndimage import zoom
        aligned: Dict[str, np.ndarray] = {}

        for band_name, arr in band_data.items():
            if arr.shape == target_shape:
                aligned[band_name] = arr
            else:
                zoom_factor = (target_shape[0] / arr.shape[0], target_shape[1] / arr.shape[1])
                canonical = self._canonical_from_dataset(band_name, list(band_data.keys()))
                order = 0 if canonical in THERMAL_BANDS else 1
                aligned[band_name] = zoom(arr, zoom_factor, order=order).astype(np.float32)
                logger.debug(f"[FY3D] Aligned {band_name}: {arr.shape} → {aligned[band_name].shape}")

        return aligned

    def _process_rgb_composite(self, datasets: List[str],
                                band_data: Dict[str, np.ndarray],
                                gamma: float) -> np.ndarray:
        """Process RGB composite from three bands."""
        r = band_data.get(datasets[0], np.zeros((1000, 1000)))
        g = band_data.get(datasets[1], np.zeros((1000, 1000)))
        b = band_data.get(datasets[2], np.zeros((1000, 1000)))

        # Align to common resolution
        aligned = self._align_bands({datasets[0]: r, datasets[1]: g, datasets[2]: b})
        r = aligned.get(datasets[0], r)
        g = aligned.get(datasets[1], g)
        b = aligned.get(datasets[2], b)

        def norm_band(arr: np.ndarray) -> np.ndarray:
            p2, p98 = np.nanpercentile(arr, (2, 98))
            if p98 > p2:
                return np.clip((arr - p2) / (p98 - p2), 0.0, 1.0)
            return np.zeros_like(arr)

        r, g, b = norm_band(r), norm_band(g), norm_band(b)

        img = np.stack([r, g, b], axis=-1)
        if gamma != 1.0:
            img = np.power(np.clip(img, 0, 1), 1.0 / gamma)

        return np.nan_to_num(img, nan=0.0).astype(np.float32)

    def _process_single_band(self, dataset_name: str,
                              band_data: Dict[str, np.ndarray],
                              gamma: float) -> np.ndarray:
        """Process single band as grayscale→RGB image."""
        arr = band_data.get(dataset_name, np.zeros((1000, 1000)))

        canonical = self._canonical_from_dataset(dataset_name, [dataset_name])
        if canonical in THERMAL_BANDS:
            # BT range [200K, 320K] → [0, 1]
            norm = np.clip((arr - 200.0) / (320.0 - 200.0), 0.0, 1.0)
        else:
            p2, p98 = np.nanpercentile(arr, (2, 98))
            norm = np.clip((arr - p2) / (p98 - p2), 0.0, 1.0) if p98 > p2 else np.zeros_like(arr)

        if gamma != 1.0:
            norm = np.power(np.clip(norm, 0, 1), 1.0 / gamma)

        img = np.stack([norm] * 3, axis=-1)
        return np.nan_to_num(img, nan=0.0).astype(np.float32)

    # ------------------------------------------------------------------
    # Metadata and coverage
    # ------------------------------------------------------------------

    def get_metadata(self) -> Dict[str, Any]:
        """Get standardised metadata."""
        if not self._is_loaded:
            return {}

        meta: Dict[str, Any] = {
            'satellite': 'FY3D',
            'sensor': 'MERSI-2',
            'satellite_type': 'FY3D',
            'n_bands': len(self._dataset_names),
            'is_loaded': self._is_loaded,
        }

        if self._reader is not None:
            reader_meta = self._reader.get_metadata()
            meta.update({
                'start_time': reader_meta.get('start_time', 'N/A'),
                'geo_file': reader_meta.get('geo_file', 'N/A'),
                'data_format': 'L1_HDF5',
            })

        meta['swath_extent'] = self._swath_extent
        meta['swath_overlaps_china'] = self._swath_overlaps_china

        return meta

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """Get geographic coverage for this satellite."""
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """Group files by timestamp for time-series processing."""
        groups: Dict[str, List[str]] = {}
        for path in sorted(file_paths):
            m = re.search(r'(\d{8}[_-]\d{4})', os.path.basename(path))
            key = m.group(1) if m else os.path.basename(path)
            groups.setdefault(key, []).append(path)
        return list(groups.values())

    def __repr__(self) -> str:
        return f"FengYun3DDriver(loaded={self._is_loaded}, bands={len(self._dataset_names)})"
