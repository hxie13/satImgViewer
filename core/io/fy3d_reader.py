"""
FY-3D MERSI-2 Direct HDF5 Reader

Reads Fengyun-3D MERSI-2 L1 data directly from HDF5 files without satpy,
using h5py for raw data access.

FY-3D MERSI-2 HDF5 file structure (radiance file):
  /EV_250_Ref_Band1    (H×W, uint16)    → B01  (250 m VIS)
  /EV_250_Ref_Band2    (H×W, uint16)    → B02  (250 m VIS)
  /EV_250_Ref_Band3    (H×W, uint16)    → B03  (250 m RED)
  /EV_250_Ref_Band4    (H×W, uint16)    → B04  (250 m NIR)
  /EV_1000_RefSB       (15×H×W, uint16) → B05–B19  (1000 m reflective)
  /EV_1000_Emissive    (6×H×W, uint16)  → B20–B25  (1000 m thermal, BT)

GEO file:
  /Longitude  (H×W, float32)  swath longitude
  /Latitude   (H×W, float32)  swath latitude

Calibration coefficients are stored as dataset attributes:
  slope + intercept   (per band, stored in dataset attrs or separate dataset)
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Any

import h5py
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Band routing table
# ---------------------------------------------------------------------------
# Each entry: (hdf5_group, index_in_group_or_None)
# index=None  → dataset is 2-D (single band per dataset)
# index=int   → dataset is 3-D, pick that slice
#
# Canonical group names use the "1000" convention; _MERSI_GROUP_ALIASES below
# maps them to the "1KM" convention used in most real FY-3D products.

_BAND_ROUTE: Dict[str, Tuple[str, Optional[int]]] = {
    'B01': ('EV_250_Ref_Band1', None),
    'B02': ('EV_250_Ref_Band2', None),
    'B03': ('EV_250_Ref_Band3', None),
    'B04': ('EV_250_Ref_Band4', None),
    **{f'B{i:02d}': ('EV_1000_RefSB', i - 5) for i in range(5, 20)},
    **{f'B{i:02d}': ('EV_1000_Emissive', i - 20) for i in range(20, 26)},
}

# Alternative HDF5 group names found in different FY-3D product versions.
# Real files often use EV_1KM_* instead of EV_1000_*.
_MERSI_GROUP_ALIASES: Dict[str, List[str]] = {
    'EV_1000_RefSB':    ['EV_1KM_RefSB',    'EV_1km_RefSB',    'EV_1000M_RefSB'],
    'EV_1000_Emissive': ['EV_1KM_Emissive', 'EV_1km_Emissive', 'EV_1000M_Emissive'],
}

# Bands B01-B19 are reflective; B20-B25 are thermal
_REFLECTIVE_BANDS = {f'B{i:02d}' for i in range(1, 20)}
_THERMAL_BANDS    = {f'B{i:02d}' for i in range(20, 26)}

# Central wavenumbers (cm⁻¹) for MERSI-2 thermal bands B20-B25
# Used in Planck inversion: BT = C2*ν / ln(1 + C1*ν³ / L)
# Values from FY-3D MERSI-2 product specification
_THERMAL_WAVENUMBER: Dict[str, float] = {
    'B20': 2622.5,   # 3.8 µm
    'B21': 2507.3,   # 4.0 µm  (approximate; some sensors differ)
    'B22': 1030.2,   # 9.7 µm
    'B23':  929.3,   # 10.8 µm
    'B24':  832.0,   # 12.0 µm
    'B25':  752.4,   # 13.3 µm
}

# Planck constants (radiation constant C1=2hc², C2=hc/k in cm units)
_C1 = 1.19104e-5   # mW · m⁻² · sr⁻¹ · cm⁻⁴  (for wavenumber in cm⁻¹, L in mW/m²/sr/cm⁻¹)
_C2 = 1.43877      # K · cm

# Fill / invalid DN flags
_FILL_DN_UINT16 = 65535
_FILL_DN_REFLECTIVE_MAX = 32767  # some products use this as fill


class FY3DReader:
    """
    Direct HDF5 reader for FY-3D MERSI-2 L1 data.

    Usage::

        reader = FY3DReader('/path/to/FY3D_MERSI...HDF',
                            geo_file='/path/to/FY3D_MERSI...GEO1K...HDF')
        bands = reader.available_bands()     # ['B01', ..., 'B25']
        refl  = reader.load_band('B04', calibration='reflectance')   # [0,1]
        bt    = reader.load_band('B23', calibration='brightness_temperature')  # K
        lons, lats = reader.get_lonlats()
        meta  = reader.get_metadata()
        reader.close()
    """

    def __init__(self, file_path: str, geo_file: Optional[str] = None):
        """
        Open FY-3D MERSI-2 radiance HDF5 file.

        Args:
            file_path:  Path to the radiance HDF5 file (1000M or 250M).
            geo_file:   Path to the GEO file containing lon/lat arrays.
                        If None, an attempt is made to auto-locate it.
        """
        self._path = file_path
        self._geo_path = geo_file or _find_geo_file(file_path)
        self._f: Optional[h5py.File] = None
        self._geo_f: Optional[h5py.File] = None
        self._available: List[str] = []
        self._cal_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}  # band→(slope, intercept)

        self._open()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def available_bands(self) -> List[str]:
        """Return canonical band IDs available in this file, e.g. ['B01',...,'B25']."""
        return list(self._available)

    def load_band(self, band: str, calibration: str = 'auto') -> np.ndarray:
        """
        Load and calibrate a single band.

        Args:
            band:         Canonical ID such as 'B04' or 'B23'.
            calibration:  'auto'                   → reflectance for B01-B19, BT for B20-B25.
                          'reflectance'             → float [0, 1] (reflective bands).
                          'brightness_temperature'  → float K (thermal bands).
                          'raw'                     → raw DN (float32).

        Returns:
            float32 ndarray, shape (H, W).
        """
        band = band.upper()
        if band not in self._available:
            raise KeyError(f"Band '{band}' not available; got: {self._available}")
        if self._f is None:
            raise IOError("HDF5 file is not open")

        dn = self._read_raw_dn(band)

        if calibration == 'raw':
            return dn.astype(np.float32)

        # Auto-select calibration type
        if calibration == 'auto':
            calibration = 'brightness_temperature' if band in _THERMAL_BANDS else 'reflectance'

        if calibration == 'reflectance':
            return self._dn_to_reflectance(band, dn)
        elif calibration == 'brightness_temperature':
            return self._dn_to_bt(band, dn)
        else:
            raise ValueError(f"Unknown calibration mode: '{calibration}'")

    def get_lonlats(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Return (longitude, latitude) arrays from the GEO file (or radiance file
        itself if geo coordinates are embedded there).

        Returns:
            (lons, lats) as float32 2-D arrays, or (None, None) if unavailable.
        """
        # 1. Prefer dedicated GEO file when available (often higher quality than
        # embedded quick-look geolocation). If it fails, fall back to embedded.
        if self._geo_f is None and self._geo_path:
            try:
                self._geo_f = h5py.File(self._geo_path, 'r')
                logger.info(f"[FY3DReader] Opened GEO file: {os.path.basename(self._geo_path)}")
            except Exception as exc:
                logger.warning(
                    "[FY3DReader] Cannot open GEO file %s (%s); falling back to embedded geolocation",
                    os.path.basename(self._geo_path), exc
                )
                # Avoid retry spam on every call.
                self._geo_path = None

        if self._geo_f is not None:
            lons = None
            lats = None
            # Common GEO-file layout: /Geolocation/{Longitude,Latitude}
            if 'Geolocation' in self._geo_f and hasattr(self._geo_f['Geolocation'], 'keys'):
                geo_grp = self._geo_f['Geolocation']
                lons = _read_geo_var(geo_grp, ('Longitude', 'longitude', 'Lon', 'lon'))
                lats = _read_geo_var(geo_grp, ('Latitude', 'latitude', 'Lat', 'lat'))
            # Fallback: lon/lat variables at root level
            if lons is None or lats is None:
                lons = _read_geo_var(self._geo_f, ('Longitude', 'longitude', 'Lon', 'lon'))
                lats = _read_geo_var(self._geo_f, ('Latitude', 'latitude', 'Lat', 'lat'))
            if lons is not None and lats is not None:
                logger.info("[FY3DReader] Using lon/lat from dedicated GEO file")
                lons = np.where(np.abs(lons) < 360.0, lons, np.nan).astype(np.float32)
                lats = np.where(np.abs(lats) <  90.1, lats, np.nan).astype(np.float32)
                return lons, lats
            logger.warning("[FY3DReader] Dedicated GEO file lacks Longitude/Latitude; falling back")

        # 2a. Check embedded 'Geolocation/' subgroup (Layout B: Data/Geolocation/*)
        if 'Geolocation' in self._f and hasattr(self._f['Geolocation'], 'keys'):
            geo_grp = self._f['Geolocation']
            lons = _read_geo_var(geo_grp, ('Longitude', 'longitude', 'Lon', 'lon'))
            lats = _read_geo_var(geo_grp, ('Latitude', 'latitude', 'Lat', 'lat'))
            if lons is not None and lats is not None:
                logger.info("[FY3DReader] Using lon/lat from embedded 'Geolocation/' group")
                lons = np.where(np.abs(lons) < 360.0, lons, np.nan).astype(np.float32)
                lats = np.where(np.abs(lats) <  90.1, lats, np.nan).astype(np.float32)
                return lons, lats

        # 2b. Check lon/lat at root level (some products embed them directly)
        lons = _read_geo_var(self._f, ('Longitude', 'longitude', 'Lon', 'lon'))
        lats = _read_geo_var(self._f, ('Latitude', 'latitude', 'Lat', 'lat'))
        if lons is not None and lats is not None:
            logger.info("[FY3DReader] Using embedded lon/lat from radiance file root")
            lons = np.where(np.abs(lons) < 360.0, lons, np.nan).astype(np.float32)
            lats = np.where(np.abs(lats) <  90.1, lats, np.nan).astype(np.float32)
            return lons, lats

        logger.warning("[FY3DReader] Geolocation unavailable (no usable GEO/embedded lon-lat)")
        return None, None

    def get_area_definition(self):
        """
        Derive a lon/lat AreaDefinition from swath extents.
        Useful only as a rough bounding-box — real resampling must use SwathDefinition.
        """
        lons, lats = self.get_lonlats()
        if lons is None:
            return None
        from .area_builder import build_area_from_lonlat_arrays
        try:
            return build_area_from_lonlat_arrays(lons, lats)
        except Exception as exc:
            logger.warning(f"[FY3DReader] Cannot build area def: {exc}")
            return None

    def get_metadata(self) -> Dict[str, Any]:
        """Return metadata dictionary."""
        meta: Dict[str, Any] = {
            'file_path': self._path,
            'geo_file': self._geo_path,
            'satellite': 'FY3D',
            'sensor': 'MERSI-2',
            'n_bands': len(self._available),
        }
        if self._f is not None:
            # Try to read time from attributes
            for key in ('Beginning_Time_of_Ascending_Node', 'Start_Time',
                        'Orbit_Start_Time', 'begin_time'):
                val = self._f.attrs.get(key)
                if val is not None:
                    meta['start_time'] = str(val)
                    break
        t = _extract_timestamp(os.path.basename(self._path))
        if t:
            meta['start_time'] = t
        return meta

    def close(self) -> None:
        """Release all HDF5 file handles."""
        for fh in (self._f, self._geo_f):
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
        self._f = None
        self._geo_f = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> None:
        """Open HDF5 and discover available bands."""
        try:
            self._f = h5py.File(self._path, 'r')
        except Exception as exc:
            raise IOError(f"Cannot open HDF5 file '{self._path}': {exc}") from exc

        # _eff_route: resolved group names for this specific file (built in _discover_bands)
        self._eff_route: Dict[str, Tuple[str, Optional[int]]] = {}
        self._available = self._discover_bands()
        logger.debug(f"[FY3DReader] Available bands: {self._available}")

    def _discover_bands(self) -> List[str]:
        """
        Discover which bands are present in this file and build effective routing.

        Handles two file layouts observed in FY-3D MERSI-2 products:
          Layout A (older):  datasets at root level  → /EV_1KM_RefSB
          Layout B (newer):  datasets inside 'Data/' → /Data/EV_1KM_RefSB

        Also supports 'EV_1000_*' vs 'EV_1KM_*' naming differences, and the
        stacked 250m format 'EV_250_RefSB' (4, H, W) as an alternative to
        individual 'EV_250_Ref_Band1'..'EV_250_Ref_Band4' datasets.
        """
        root_keys = set(self._f.keys())

        # Determine search space: root level, and optionally 'Data/' subgroup
        search_spaces: List[Tuple[str, set]] = [('', root_keys)]
        if 'Data' in root_keys and hasattr(self._f['Data'], 'keys'):
            data_keys = set(self._f['Data'].keys())
            search_spaces.append(('Data/', data_keys))
            logger.info("[FY3DReader] Found 'Data/' group — keys: %s",
                        sorted(data_keys))

        found = []
        for prefix, keys in search_spaces:
            # Resolve group-name aliases within this search space
            group_resolve: Dict[str, str] = {}
            for canonical, aliases in _MERSI_GROUP_ALIASES.items():
                if canonical in keys:
                    group_resolve[canonical] = canonical
                else:
                    for alias in aliases:
                        if alias in keys:
                            group_resolve[canonical] = alias
                            logger.debug(f"[FY3DReader] Using '{prefix}{alias}' for '{canonical}'")
                            break

            # Cache 3D dataset sizes to avoid repeated h5py calls
            _ds_sizes: Dict[str, int] = {}

            def _ds_n_bands(path: str) -> int:
                """Return first-dimension size of a dataset (i.e. number of bands)."""
                if path not in _ds_sizes:
                    try:
                        _ds_sizes[path] = self._f[path].shape[0]
                    except Exception:
                        _ds_sizes[path] = 9999  # assume large enough on error
                return _ds_sizes[path]

            for band, (group, idx) in _BAND_ROUTE.items():
                if band in self._eff_route:
                    continue  # already resolved from root level
                actual = group_resolve.get(group, group)
                full_path = f'{prefix}{actual}'
                if actual in keys:
                    # For 3D datasets, verify the index is within bounds
                    if idx is not None and idx >= _ds_n_bands(full_path):
                        logger.debug("[FY3DReader] Band %s idx=%d out of range "
                                     "for %s (n=%d); skipping",
                                     band, idx, full_path, _ds_n_bands(full_path))
                        continue
                    self._eff_route[band] = (full_path, idx)
                    if band not in found:
                        found.append(band)

            # Handle stacked 250m format: EV_250_RefSB (4, H, W)
            # Some FY-3D files store all four 250m bands in one 3D dataset.
            _250m_stacked = ('EV_250_RefSB', 'EV_250M_RefSB')
            for stacked_name in _250m_stacked:
                if stacked_name in keys:
                    full_path = f'{prefix}{stacked_name}'
                    n = _ds_n_bands(full_path)
                    logger.debug("[FY3DReader] Using stacked 250m dataset '%s' (n=%d)",
                                 full_path, n)
                    for i, band in enumerate(('B01', 'B02', 'B03', 'B04')):
                        if band not in self._eff_route and i < n:
                            self._eff_route[band] = (full_path, i)
                            if band not in found:
                                found.append(band)
                    break

        if not found:
            logger.warning(
                "[FY3DReader] No known MERSI-2 datasets found. "
                "Root keys: %s", sorted(root_keys)
            )
        else:
            logger.info("[FY3DReader] Discovered %d bands: %s", len(found), sorted(found))
        return found

    def _read_raw_dn(self, band: str) -> np.ndarray:
        """Read raw DN values for a band, returning a 2-D (H,W) uint16 array."""
        group, idx = self._eff_route.get(band, _BAND_ROUTE[band])
        ds = self._f[group]

        if idx is None:
            # 2-D dataset (single 250m band)
            dn = ds[:]
        else:
            # 3-D dataset: (n_bands, H, W)
            dn = ds[idx, :, :]

        return dn  # uint16

    def _get_cal_coeffs(self, band: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Retrieve per-band calibration slope and intercept.

        Returns (slope_arr, intercept_arr); each is a 1-D array (may be scalar-wrapped).
        """
        if band in self._cal_cache:
            return self._cal_cache[band]

        group, idx = self._eff_route.get(band, _BAND_ROUTE[band])
        ds = self._f[group]

        slope = np.array([1.0], dtype=np.float32)
        intercept = np.array([0.0], dtype=np.float32)

        # Try standard attribute names
        for slope_key in ('Slope', 'slope', 'scale_factor', 'Scale'):
            val = ds.attrs.get(slope_key)
            if val is not None:
                s = np.atleast_1d(np.asarray(val, dtype=np.float32))
                # Use slice (not index) so result is always a 1-D array, not a 0-d scalar
                slope = s[idx:idx+1] if (idx is not None and len(s) > 1) else s[0:1]
                break

        for intercept_key in ('Intercept', 'intercept', 'add_offset', 'Offset'):
            val = ds.attrs.get(intercept_key)
            if val is not None:
                b = np.atleast_1d(np.asarray(val, dtype=np.float32))
                intercept = b[idx:idx+1] if (idx is not None and len(b) > 1) else b[0:1]
                break

        # Also check a per-band calibration coefficient dataset.
        # Layout B: coefficients are inside the 'Calibration/' group.
        # Layout A: coefficients are at root level.
        # VIS_Cal_Coeff covers reflective bands (B01-B19), indexed 0-18.
        # IR_Cal_Coeff covers thermal bands (B20-B25), indexed 0-5.
        m = re.match(r'B(\d+)', band)
        if m:
            band_num = int(m.group(1))
            if 1 <= band_num <= 19:
                cal_idx = band_num - 1
                vis_paths = (
                    'Calibration/VIS_Cal_Coeff', 'Calibration/RSB_Cal_Coeff',
                    'VIS_Cal_Coeff', 'RSB_Cal_Coeff', 'EV_Cal_Coeff',
                )
                for cal_path in vis_paths:
                    if cal_path in self._f:
                        try:
                            coeff = self._f[cal_path][:]
                            if coeff.ndim == 2 and cal_idx < coeff.shape[0]:
                                slope = np.array([coeff[cal_idx, 0]], dtype=np.float32)
                                intercept = np.array([coeff[cal_idx, 1]], dtype=np.float32)
                                logger.debug("[FY3DReader] Cal from %s[%d]", cal_path, cal_idx)
                                break
                        except Exception:
                            pass
            elif 20 <= band_num <= 25:
                cal_idx = band_num - 20
                ir_paths = (
                    'Calibration/IR_Cal_Coeff', 'Calibration/TEB_Cal_Coeff',
                    'IR_Cal_Coeff', 'TEB_Cal_Coeff',
                )
                for cal_path in ir_paths:
                    if cal_path in self._f:
                        try:
                            coeff = self._f[cal_path][:]
                            if coeff.ndim == 2 and cal_idx < coeff.shape[0]:
                                slope = np.array([coeff[cal_idx, 0]], dtype=np.float32)
                                intercept = np.array([coeff[cal_idx, 1]], dtype=np.float32)
                                logger.debug("[FY3DReader] Cal from %s[%d]", cal_path, cal_idx)
                                break
                        except Exception:
                            pass

        self._cal_cache[band] = (slope, intercept)
        return slope, intercept

    def _dn_to_reflectance(self, band: str, dn: np.ndarray) -> np.ndarray:
        """
        Convert raw DN to reflectance [0, 1].

        Uses linear calibration: L = DN * slope + intercept, then normalises by
        solar spectral irradiance or simply clips to [0, 1] range.
        """
        slope, intercept = self._get_cal_coeffs(band)
        dn_f = dn.astype(np.float32)

        # Mask fill values
        fill_mask = (dn == _FILL_DN_UINT16) | (dn == 0)
        dn_f = np.where(fill_mask, np.nan, dn_f)

        radiance = dn_f * slope[0] + intercept[0]

        # Normalise to [0, 1] using a robust percentile approach
        # This avoids needing per-file E0/d² which are not always available
        valid = radiance[np.isfinite(radiance)]
        if valid.size > 0:
            lo = np.percentile(valid, 0.5)
            hi = np.percentile(valid, 99.5)
            if hi > lo:
                refl = (radiance - lo) / (hi - lo)
            else:
                refl = np.zeros_like(radiance)
        else:
            refl = np.zeros_like(radiance)

        refl = np.clip(refl, 0.0, 1.0)
        refl = np.where(fill_mask, np.nan, refl)
        return refl.astype(np.float32)

    def _dn_to_bt(self, band: str, dn: np.ndarray) -> np.ndarray:
        """
        Convert raw DN to brightness temperature (K) via Planck inversion.

        BT = C2 * ν / ln(1 + C1 * ν³ / L)
        """
        slope, intercept = self._get_cal_coeffs(band)
        dn_f = dn.astype(np.float32)

        fill_mask = (dn == _FILL_DN_UINT16) | (dn == 0)
        dn_f = np.where(fill_mask, np.nan, dn_f)

        radiance = dn_f * slope[0] + intercept[0]

        nu = _THERMAL_WAVENUMBER.get(band)
        if nu is None:
            logger.warning(f"[FY3DReader] No wavenumber for {band}; returning raw radiance")
            return radiance

        # Planck inversion; guard against zero/negative radiance
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = _C1 * (nu ** 3) / radiance
            bt = np.where(
                ratio > 0,
                _C2 * nu / np.log1p(ratio),
                np.nan
            )

        # Physical sanity check
        bt = np.where((bt > 170.0) & (bt < 400.0), bt, np.nan)
        bt = np.where(fill_mask, np.nan, bt)
        return bt.astype(np.float32)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _find_geo_file(data_file: str) -> Optional[str]:
    """
    Attempt to locate the matching GEO file for a MERSI-2 radiance file.

    Searches:
      1) the radiance file directory itself;
      2) immediate GEO-like subdirectories (for example "GEO/").

    Matching is based on shared timestamp and GEO indicators in filename.

    Typical naming:
      FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_GEO1K_MS.HDF
    """
    directory = os.path.dirname(data_file)
    basename = os.path.basename(data_file)

    # Extract the timestamp portion (YYYYMMDD_HHMM)
    m = re.search(r'(\d{8}_\d{4})', basename)
    if not m:
        return None

    ts = m.group(1)

    # Build deterministic list of search directories: same folder first,
    # then common GEO subfolders (and any immediate folder containing "GEO").
    search_dirs = [directory]
    for sub in ('GEO', 'Geo', 'geo'):
        subdir = os.path.join(directory, sub)
        if os.path.isdir(subdir) and subdir not in search_dirs:
            search_dirs.append(subdir)
    try:
        for entry in os.listdir(directory):
            subdir = os.path.join(directory, entry)
            if os.path.isdir(subdir) and 'GEO' in entry.upper() and subdir not in search_dirs:
                search_dirs.append(subdir)
    except OSError:
        pass

    candidates: List[Tuple[str, str]] = []
    for d in search_dirs:
        try:
            for fname in os.listdir(d):
                full = os.path.join(d, fname)
                if os.path.isfile(full):
                    candidates.append((d, fname))
        except OSError:
            continue

    if not candidates:
        return None

    # Pass 1: specific GEO suffixes (highest confidence)
    for geo_suffix in ('GEO1K', 'GEODK', 'GEO1KM', 'GEO250', 'GEO500', 'GEOLOC'):
        pattern = re.compile(rf'.*{ts}.*{geo_suffix}.*', re.IGNORECASE)
        for d, fname in candidates:
            if pattern.match(fname):
                geo_path = os.path.join(d, fname)
                if os.path.isfile(geo_path):
                    logger.debug(f"[FY3DReader] Found GEO file: {geo_path}")
                    return geo_path

    # Pass 2: any file with same timestamp and 'GEO' anywhere in name
    loose = re.compile(rf'.*{ts}.*GEO.*', re.IGNORECASE)
    for d, fname in candidates:
        if loose.match(fname) and fname != basename:
            geo_path = os.path.join(d, fname)
            if os.path.isfile(geo_path):
                logger.debug(f"[FY3DReader] Found GEO file (loose match): {geo_path}")
                return geo_path

    return None


def _read_geo_var(f: h5py.File, candidates: Tuple[str, ...]) -> Optional[np.ndarray]:
    """Try multiple variable name candidates and return the first found."""
    for name in candidates:
        if name in f:
            return f[name][:].astype(np.float32)
    return None


def _extract_timestamp(filename: str) -> Optional[str]:
    """Extract ISO timestamp string from filename."""
    m = re.search(r'(\d{8})[_-](\d{4})', filename)
    if m:
        d, t = m.group(1), m.group(2)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}"
    return None
