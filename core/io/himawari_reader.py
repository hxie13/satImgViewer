"""
Himawari-8/9 AHI L1b Gridded NetCDF Reader

Reads Himawari-8/9 AHI L1b gridded data directly from CF-compliant NetCDF
files using xarray, without requiring satpy.

Supported format: AHI L1b gridded NetCDF (.nc)
  Variables: albedo_01...albedo_06  (VIS/NIR, reflectance in %)
             tbb_07...tbb_16        (IR, brightness temperature in K)
  Coordinates: longitude (1-D), latitude (1-D)
  Attributes: sub_lon, etc.

NOT supported: HSD binary (.dat, .bz2) — see user decision notes.
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Band → NetCDF variable name mapping
# ---------------------------------------------------------------------------
# AHI L1b gridded uses:
#   albedo_NN for VIS/NIR/SWIR bands (N=01-06, reflectance in %)
#   tbb_NN    for IR bands (N=07-16, brightness temperature in K)

_VIS_BANDS  = {f'B{i:02d}' for i in range(1, 7)}
_IR_BANDS   = {f'B{i:02d}' for i in range(7, 17)}
_ALL_BANDS  = sorted(_VIS_BANDS | _IR_BANDS)

_NC_VAR: Dict[str, str] = {
    **{f'B{i:02d}': f'albedo_{i:02d}' for i in range(1, 7)},
    **{f'B{i:02d}': f'tbb_{i:02d}'    for i in range(7, 17)},
}

# Canonical band → display name  (same mapping used by driver's _canonical_from_dataset)
_BAND_DISPLAY: Dict[str, str] = {
    'B01': 'VIS006', 'B02': 'VIS008', 'B03': 'RED',
    'B04': 'NIR016', 'B05': 'SWIR16', 'B06': 'SWIR22',
    'B07': 'IR039',  'B08': 'WV062',  'B09': 'WV070',
    'B10': 'WV073',  'B11': 'IR086',  'B12': 'IR096',
    'B13': 'IR105',  'B14': 'IR112',  'B15': 'IR123',
    'B16': 'IR133',
}

# Default sub-satellite longitudes
_DEFAULT_SUB_LON = {
    'H08': 140.7,
    'H09': 140.7,
}


class HimawariNCReader:
    """
    Reader for Himawari-8/9 AHI L1b gridded NetCDF files.

    Usage::

        reader = HimawariNCReader('/path/to/H08_20230101_0000_B01_FLDK...nc')
        bands = reader.available_bands()      # ['B01', 'B02', ..., 'B16']
        refl  = reader.load_band('B03')       # float32 [0, 1]
        bt    = reader.load_band('B13')       # float32 K
        area  = reader.get_area_definition()
        meta  = reader.get_metadata()
        reader.close()
    """

    def __init__(self, file_path: str):
        """
        Open a Himawari L1b gridded NetCDF file.

        Args:
            file_path:  Path to a .nc file produced by the Himawari L1b gridded reader.

        Raises:
            IOError:  If the file cannot be opened.
            ValueError: If the file is not a recognised Himawari L1b gridded product.
        """
        self._path = file_path
        self._ds = None
        self._satellite = _detect_satellite(file_path)
        self._available: List[str] = []
        self._lons: Optional[np.ndarray] = None
        self._lats: Optional[np.ndarray] = None

        self._open()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def available_bands(self) -> List[str]:
        """Return list of available AHI band IDs (e.g. ['B01', ..., 'B16'])."""
        return list(self._available)

    def load_band(self, band: str, calibration: str = 'auto') -> np.ndarray:
        """
        Load a single AHI band.

        Args:
            band:         Band ID such as 'B01' or 'B13'.
            calibration:  'auto'  → reflectance [0,1] for VIS; BT[K] for IR.
                          'raw'   → raw values as stored in the NetCDF file.

        Returns:
            float32 ndarray (H, W).
              VIS/NIR/SWIR bands: reflectance [0, 1]
              IR bands: brightness temperature in K
        """
        band = band.upper()
        if band not in self._available:
            raise KeyError(f"Band '{band}' not available; got: {self._available}")

        if self._ds is None:
            raise IOError("NetCDF dataset is not open")

        nc_var = _NC_VAR[band]
        data = self._ds[nc_var].values.astype(np.float32)

        if calibration == 'raw':
            return data

        # Apply scaling
        if band in _VIS_BANDS:
            # albedo_NN is in percent [0, 100] → convert to [0, 1]
            data = data / 100.0
            data = np.clip(data, 0.0, 1.0)
        # tbb_NN is already in K; just replace obvious fill values
        else:
            fill_candidates = [self._ds[nc_var].attrs.get('_FillValue'),
                               self._ds[nc_var].attrs.get('missing_value')]
            for fv in fill_candidates:
                if fv is not None:
                    data = np.where(data == float(fv), np.nan, data)
            # Physical sanity
            data = np.where((data > 170.0) & (data < 400.0), data, np.nan)

        return data

    def get_lonlats(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Return (lon, lat) coordinate arrays.

        Returns:
            (lons 1-D, lats 1-D) or (None, None) if unavailable.
        """
        return self._lons, self._lats

    def get_area_definition(self):
        """
        Return a pyresample AreaDefinition built from coordinate arrays.

        For L1b gridded data the coordinates are regular, so a simple
        plate-carree grid is constructed.

        Returns:
            pyresample.geometry.AreaDefinition or None
        """
        if self._lons is None or self._lats is None:
            return None

        from .area_builder import build_lonlat_area
        try:
            return build_lonlat_area(
                west=float(self._lons.min()),
                south=float(self._lats.min()),
                east=float(self._lons.max()),
                north=float(self._lats.max()),
                width=len(self._lons),
                height=len(self._lats),
                area_id=f'himawari_{self._satellite}',
            )
        except Exception as exc:
            logger.warning(f"[HimawariNCReader] Cannot build area definition: {exc}")
            return None

    def get_metadata(self) -> Dict[str, Any]:
        """Return a metadata dictionary."""
        meta: Dict[str, Any] = {
            'file_path': self._path,
            'satellite': self._satellite,
            'n_bands': len(self._available),
            'format': 'l1b_gridded',
        }
        if self._ds is not None:
            for key in ('sub_lon', 'satellite', 'sensor', 'platform'):
                val = self._ds.attrs.get(key)
                if val is not None:
                    meta[key] = str(val)
        t = _extract_timestamp(os.path.basename(self._path))
        if t:
            meta['start_time'] = t
        if self._lons is not None:
            meta['lon_range'] = (float(self._lons.min()), float(self._lons.max()))
            meta['lat_range'] = (float(self._lats.min()), float(self._lats.max()))
        return meta

    def close(self) -> None:
        """Close the NetCDF dataset."""
        if self._ds is not None:
            try:
                self._ds.close()
            except Exception:
                pass
            self._ds = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> None:
        """Open NetCDF file and discover available bands + coordinates."""
        import xarray as xr

        try:
            # Use netcdf4 engine; fall back to scipy for older environments
            engines = ['netcdf4', 'h5netcdf', 'scipy']
            last_exc = None
            for eng in engines:
                try:
                    self._ds = xr.open_dataset(
                        self._path,
                        engine=eng,
                        mask_and_scale=False,
                        decode_timedelta=False,
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    continue
            if self._ds is None:
                raise IOError(f"Cannot open NetCDF with any engine: {last_exc}")
        except Exception as exc:
            raise IOError(f"Cannot open '{self._path}': {exc}") from exc

        self._available = self._discover_bands()
        if not self._available:
            logger.warning(
                f"[HimawariNCReader] No AHI band variables found in {os.path.basename(self._path)}"
            )

        self._lons, self._lats = self._read_coordinates()

    def _discover_bands(self) -> List[str]:
        """Find which AHI band variables are present in the NetCDF file."""
        found = []
        for band in _ALL_BANDS:
            nc_var = _NC_VAR[band]
            if nc_var in self._ds.data_vars:
                found.append(band)
        logger.debug(f"[HimawariNCReader] Found bands: {found}")
        return found

    def _read_coordinates(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Read lon/lat 1-D coordinate arrays from the NetCDF dataset."""
        lon_candidates = ('longitude', 'lon', 'x', 'Longitude', 'Lon')
        lat_candidates = ('latitude',  'lat', 'y', 'Latitude',  'Lat')

        lons = _find_coord(self._ds, lon_candidates)
        lats = _find_coord(self._ds, lat_candidates)

        if lons is None:
            logger.warning("[HimawariNCReader] Longitude coordinate not found")
        if lats is None:
            logger.warning("[HimawariNCReader] Latitude coordinate not found")

        return lons, lats


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _find_coord(ds, candidates: Tuple[str, ...]) -> Optional[np.ndarray]:
    """Return the first matching coordinate array."""
    for name in candidates:
        if name in ds.coords:
            arr = ds.coords[name].values
            if arr.ndim == 1:
                return arr.astype(np.float32)
    # Also check data variables that might hold coordinate data
    for name in candidates:
        if name in ds.data_vars:
            arr = ds[name].values
            if arr.ndim == 1:
                return arr.astype(np.float32)
    return None


def _detect_satellite(file_path: str) -> str:
    """Infer satellite variant from filename."""
    name = os.path.basename(file_path).upper()
    if 'H09' in name:
        return 'H09'
    if 'H08' in name:
        return 'H08'
    # Check for HIMAWARI-9 keyword
    if 'HIMAWARI9' in name or 'HIMAWARI-9' in name:
        return 'H09'
    return 'H08'  # default to Himawari-8


def _extract_timestamp(filename: str) -> Optional[str]:
    """Extract ISO timestamp from Himawari filename (e.g. H08_20230101_0000_...)."""
    m = re.search(r'(\d{8})[_-](\d{4})', filename)
    if m:
        d, t = m.group(1), m.group(2)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}"
    return None
