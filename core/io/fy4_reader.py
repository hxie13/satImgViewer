"""
FY-4A/B AGRI Direct HDF5 Reader

Reads Fengyun-4A and Fengyun-4B AGRI L1 and L2 data directly from HDF5 files
without satpy, using h5py for raw data access and numpy for calibration.

Supported file types:
  - L1 Full-disk / Region / China Region (.HDF, .h5, .nc)
    HDF5 structure:
      /Data/NOMChannel01 ... /Data/NOMChannel14  (uint16 DN, shape H×W)
      /Calibration/CALChannel01 ... /Calibration/CALChannel14  (float32 LUT)
      Root attrs: NOMCenterLon, NOMSatHeight, dSamplingAngle, dSteppingAngle, etc.

  - L2 products (.NC, .nc) read with xarray (already calibrated physical values)
"""
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import h5py
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Band channel → HDF5 dataset mapping
# ---------------------------------------------------------------------------
# FY-4A/B AGRI L1 HDF5 files store raw DN values as NOMChannelXX datasets.
# Calibration LUTs are stored in /Calibration/CALChannelXX.
# Channel numbers 1-6 → VIS/SWIR bands (reflectance), 7-14 → IR bands (BT in K).

# Canonical short names C01-C14 used throughout this reader.
_N_CHANNELS = 14
_CHANNEL_IDS = [f'C{i:02d}' for i in range(1, _N_CHANNELS + 1)]

# HDF5 dataset paths.
# FY-4A/B AGRI L1 stores DN under a 'Data/' group prefix (e.g. Data/NOMChannel01).
# Calibration LUTs remain under 'Calibration/CALChannelXX'.
_DATA_PATH: Dict[str, str] = {f'C{i:02d}': f'Data/NOMChannel{i:02d}' for i in range(1, _N_CHANNELS + 1)}
_CAL_PATH:  Dict[str, str] = {f'C{i:02d}': f'Calibration/CALChannel{i:02d}' for i in range(1, _N_CHANNELS + 1)}

# VIS/SWIR channels produce reflectance factor [0, ~1.0] after LUT (dimensionless, NOT percent).
# IR channels produce brightness temperature [K] after LUT.
_VIS_CHANNELS = {f'C{i:02d}' for i in range(1, 7)}   # C01–C06: reflectance
_IR_CHANNELS  = {f'C{i:02d}' for i in range(7, 15)}  # C07–C14: BT in K

# FY-4B has an additional C15 channel in some products
_FY4B_EXTRA_CHANNEL = 'C15'

# Default geostationary parameters (used if HDF5 attrs are absent).
# IFOV is derived from actual attr 'dSamplingAngle'; 112 µrad ≈ 4 km at GEO orbit.
_DEFAULT_SAT_HEIGHT_M = 35786023.0  # metres above Earth equator
_DEFAULT_IFOV_URAD = 112.0         # µrad/pixel (4 km full-disk product default)

# Thermal BT normalisation range (K) used when converting to display image
BT_RANGE = (170.0, 340.0)


class FY4Reader:
    """
    Direct HDF5 reader for FY-4A/B AGRI L1 data.

    Usage::

        reader = FY4Reader('/path/to/FY4A-_AGRI--...HDF')
        area = reader.get_area_definition()
        bands = reader.available_bands()          # ['C01', 'C02', ..., 'C14']
        refl = reader.load_band('C01')            # float32 [0, 1]
        bt   = reader.load_band('C13')            # float32 K
        meta = reader.get_metadata()
        reader.close()
    """

    def __init__(self, file_path: str, satellite: str = 'auto'):
        """
        Open an FY-4A/B AGRI L1 HDF5 file.

        Args:
            file_path:  Absolute path to the HDF5 data file.
            satellite:  'FY4A', 'FY4B', or 'auto' (auto-detect from filename).
        """
        self._path = file_path
        self._f: Optional[h5py.File] = None
        self._nav: Dict[str, Any] = {}
        self._available: List[str] = []
        self._satellite = satellite

        self._open()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def available_bands(self) -> List[str]:
        """Return list of available channel IDs (e.g. ['C01', …, 'C14'])."""
        return list(self._available)

    def load_band(self, band: str, calibration: str = 'auto') -> np.ndarray:
        """
        Load and calibrate a single channel.

        Args:
            band:         Channel ID such as 'C01' or 'C13'.
            calibration:  'auto'  → reflectance for VIS, BT(K) for IR.
                          'raw'   → raw DN values (uint16 as float32).

        Returns:
            float32 ndarray (H, W).
              VIS channels: reflectance [0, 1]  (NaN for fill values)
              IR  channels: brightness temperature in K  (NaN for fill values)
        """
        band = band.upper()
        if band not in self._available:
            raise KeyError(f"Band '{band}' not available; got: {self._available}")

        if self._f is None:
            raise IOError("HDF5 file is not open")

        ds_path = _DATA_PATH.get(band)
        if ds_path is None:
            raise KeyError(f"No HDF5 path mapping for band '{band}'")

        # Read raw DN (uint16)
        raw = self._f[ds_path][:]  # shape (H, W), uint16
        if calibration == 'raw':
            return raw.astype(np.float32)

        # Apply calibration LUT
        return self._apply_lut(band, raw)

    def get_area_definition(self):
        """
        Return a pyresample AreaDefinition for the native geostationary grid.

        Returns:
            pyresample.geometry.AreaDefinition or None on failure.
        """
        if not self._nav:
            logger.warning("[FY4Reader] Navigation not parsed; cannot build area definition")
            return None

        from .area_builder import build_geos_area
        try:
            return build_geos_area(
                lon_0=self._nav['lon_0'],
                sat_height_m=self._nav['sat_height_m'],
                img_width=self._nav['width'],
                img_height=self._nav['height'],
                ifov_x=self._nav['ifov_x'],
                ifov_y=self._nav['ifov_y'],
            )
        except Exception as exc:
            logger.error(f"[FY4Reader] Failed to build area definition: {exc}")
            return None

    def get_metadata(self) -> Dict[str, Any]:
        """Return a metadata dictionary (satellite ID, time, resolution, …)."""
        meta: Dict[str, Any] = {
            'file_path': self._path,
            'satellite': self._satellite,
            'n_channels': len(self._available),
        }
        if self._nav:
            meta.update({
                'lon_0': self._nav.get('lon_0'),
                'width': self._nav.get('width'),
                'height': self._nav.get('height'),
                'resolution_m': self._nav.get('resolution_m'),
            })
        # Try to extract time from filename
        t = _extract_timestamp(os.path.basename(self._path))
        if t:
            meta['start_time'] = t
        return meta

    def close(self) -> None:
        """Release HDF5 file handle."""
        if self._f is not None:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> None:
        """Open HDF5 file and parse navigation + available bands."""
        try:
            self._f = h5py.File(self._path, 'r')
        except Exception as exc:
            raise IOError(f"Cannot open HDF5 file '{self._path}': {exc}") from exc

        # Auto-detect satellite variant
        if self._satellite == 'auto':
            self._satellite = _detect_satellite_from_path(self._path)

        # Discover available channel datasets
        self._available = self._discover_channels()
        if not self._available:
            logger.warning(f"[FY4Reader] No NOMChannelXX datasets found in {os.path.basename(self._path)}")

        # Parse navigation parameters
        self._nav = self._parse_navigation()

    def _discover_channels(self) -> List[str]:
        """Find which NOMChannelXX datasets actually exist in the file.

        Supports two known HDF5 layouts:
          - New layout (FY-4A/B):  Data/NOMChannel01 (datasets in a 'Data' group)
          - Legacy layout:         NOMChannel01      (datasets at root)
        """
        found = []
        for cid in _CHANNEL_IDS:
            ds_path = _DATA_PATH[cid]          # 'Data/NOMChannel01'
            root_name = ds_path.split('/')[-1] # 'NOMChannel01'
            if ds_path in self._f:
                found.append(cid)
            elif root_name in self._f:
                # Legacy layout: update path map in-place to root path
                _DATA_PATH[cid] = root_name
                found.append(cid)

        # C15 (FY-4B extra channel)
        for prefix in ('Data/', ''):
            extra_path = f'{prefix}NOMChannel15'
            if extra_path in self._f and _FY4B_EXTRA_CHANNEL not in found:
                _DATA_PATH[_FY4B_EXTRA_CHANNEL] = extra_path
                _CAL_PATH[_FY4B_EXTRA_CHANNEL]  = 'Calibration/CALChannel15'
                _IR_CHANNELS.add(_FY4B_EXTRA_CHANNEL)
                found.append(_FY4B_EXTRA_CHANNEL)
                break

        logger.debug(f"[FY4Reader] Found channels: {found}")
        return found

    def _parse_navigation(self) -> Dict[str, Any]:
        """Extract geostationary navigation parameters from HDF5 root attributes."""
        nav: Dict[str, Any] = {}

        attrs = {}
        try:
            for k, v in self._f.attrs.items():
                try:
                    attrs[k] = v.item() if hasattr(v, 'item') else v
                except Exception:
                    attrs[k] = v
        except Exception as exc:
            logger.warning(f"[FY4Reader] Could not read root attrs: {exc}")
            return nav

        # Sub-satellite longitude — try several known attribute name variants
        for key in ('NOMCentLon', 'NOMCenterLon', 'CenterLon', 'sub_lon'):
            if key in attrs:
                try:
                    nav['lon_0'] = float(attrs[key])
                    break
                except Exception:
                    pass
        if 'lon_0' not in nav:
            nav['lon_0'] = 104.7 if 'FY4A' in self._satellite else 105.0
            logger.debug(f"[FY4Reader] lon_0 not in attrs; using default {nav['lon_0']}")

        # Satellite height (metres above Earth equator radius)
        for key in ('NOMSatHeight', 'SatelliteHeight', 'satellite_height'):
            if key in attrs:
                try:
                    h_val = float(attrs[key])
                    # Some files store km, some store m
                    nav['sat_height_m'] = h_val * 1000.0 if h_val < 100000 else h_val
                    break
                except Exception:
                    pass
        if 'sat_height_m' not in nav:
            nav['sat_height_m'] = _DEFAULT_SAT_HEIGHT_M

        # Pixel angular size in µrad/pixel → convert to rad/pixel.
        # FY-4A/B use 'dSamplingAngle' (E-W) / 'dSteppingAngle' (N-S); older docs
        # use 'NOMImageScaleX'/'NOMImageScaleY'.  Fall back to 28 µrad (1 km nominal).
        sx = float(attrs.get('dSamplingAngle',
                   attrs.get('NOMImageScaleX',
                   attrs.get('ImageScaleX', _DEFAULT_IFOV_URAD))))
        sy = float(attrs.get('dSteppingAngle',
                   attrs.get('NOMImageScaleY',
                   attrs.get('ImageScaleY', _DEFAULT_IFOV_URAD))))
        nav['ifov_x'] = sx * 1e-6   # rad/pixel
        nav['ifov_y'] = sy * 1e-6

        # Image dimensions from first available channel dataset
        if self._available:
            ds = self._f[_DATA_PATH[self._available[0]]]
            h, w = ds.shape
            nav['height'] = h
            nav['width']  = w
        else:
            nav['height'] = 0
            nav['width']  = 0

        # Approximate ground resolution in metres
        # res ≈ ifov (rad) × sat_height (m) at nadir
        nav['resolution_m'] = round(sx * 1e-6 * nav['sat_height_m'])

        logger.debug(
            f"[FY4Reader] nav: lon_0={nav['lon_0']}, h={nav['sat_height_m']:.0f}m, "
            f"ifov=({sx:.2f},{sy:.2f})µrad, size={nav.get('width')}x{nav.get('height')}"
        )
        return nav

    def _apply_lut(self, band: str, dn: np.ndarray) -> np.ndarray:
        """
        Apply calibration LUT to raw DN array.

        Args:
            band: Channel ID ('C01' ... 'C14').
            dn:   uint16 array of raw DN values.

        Returns:
            float32 calibrated array:
              - VIS channels: reflectance [0, 1]
              - IR  channels: brightness temperature [K]
        """
        cal_path = _CAL_PATH.get(band)
        if cal_path is None or cal_path not in self._f:
            logger.warning(f"[FY4Reader] No calibration LUT for {band}; returning raw/max normalised")
            return dn.astype(np.float32) / np.iinfo(np.uint16).max

        lut = self._f[cal_path][:]  # 1-D float array, len = LUT size (usually 65536 or 4096)
        lut = lut.astype(np.float32)

        lut_size = len(lut)
        # Clamp DN to valid LUT range; mark fill values (max DN) as NaN
        fill_val = np.iinfo(np.uint16).max
        dn_f = dn.astype(np.int32)

        valid_mask = (dn_f > 0) & (dn_f < fill_val) & (dn_f < lut_size)
        out = np.full(dn.shape, np.nan, dtype=np.float32)
        valid_idx = dn_f[valid_mask]
        out[valid_mask] = lut[valid_idx]

        # VIS channels: LUT produces reflectance factor [0, ~1.0] directly.
        # FY-4A/B AGRI uses CALIBRATION_COEF (scale*DN + offset) to pre-compute
        # the LUT; output is a dimensionless reflectance factor, NOT percent.
        if band in _VIS_CHANNELS:
            out = np.clip(out, 0.0, 1.2)   # allow slight >1 at saturation
            out = np.where(out >= 0.0, out, np.nan)
        # IR channels: LUT produces BT in K; clip to physical range
        else:
            out = np.where((out > BT_RANGE[0]) & (out < BT_RANGE[1] + 60), out, np.nan)

        return out


# ---------------------------------------------------------------------------
# FY-4 L2 NetCDF reader  (thin xarray wrapper)
# ---------------------------------------------------------------------------

class FY4L2Reader:
    """
    Reader for FY-4A/B AGRI L2 products stored as CF-compliant NetCDF.

    L2 variables (CLM, CTT, CTP, etc.) are already in physical units.
    """

    _ENGINES = ['netcdf4', 'h5netcdf', 'scipy']

    def __init__(self, file_path: str):
        import xarray as xr
        self._path = file_path
        self._ds = None
        for engine in self._ENGINES:
            try:
                self._ds = xr.open_dataset(file_path, engine=engine, mask_and_scale=True)
                break
            except (ImportError, ModuleNotFoundError, ValueError, RuntimeError):
                continue
        if self._ds is None:
            raise ImportError(
                f"Cannot open {file_path}: none of {self._ENGINES} engines available. "
                "Install netCDF4 or h5netcdf: pip install netCDF4"
            )
        self._satellite = _detect_satellite_from_path(file_path)

    def available_variables(self) -> List[str]:
        """Return list of data variable names in the NetCDF file."""
        return list(self._ds.data_vars)

    def load_variable(self, var_name: str) -> np.ndarray:
        """Load a variable as a float32 numpy array."""
        return self._ds[var_name].values.astype(np.float32)

    def get_area_definition(self):
        """Attempt to build area definition from coordinate variables."""
        lon_var = next((v for v in ['longitude', 'lon', 'x'] if v in self._ds.coords), None)
        lat_var = next((v for v in ['latitude', 'lat', 'y'] if v in self._ds.coords), None)
        if lon_var is None or lat_var is None:
            return None
        from .area_builder import build_lonlat_area
        lons = self._ds.coords[lon_var].values
        lats = self._ds.coords[lat_var].values
        if lons.ndim == 1 and lats.ndim == 1:
            return build_lonlat_area(
                float(lons.min()), float(lats.min()),
                float(lons.max()), float(lats.max()),
                len(lons), len(lats),
            )
        return None

    def get_metadata(self) -> Dict[str, Any]:
        return {
            'file_path': self._path,
            'satellite': self._satellite,
            'variables': self.available_variables(),
            'attrs': dict(self._ds.attrs),
        }

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _detect_satellite_from_path(file_path: str) -> str:
    """Infer satellite variant from filename."""
    name = os.path.basename(file_path).upper()
    if 'FY4B' in name or 'FY-4B' in name or 'FY_4B' in name:
        return 'FY4B'
    if 'FY4A' in name or 'FY-4A' in name or 'FY_4A' in name:
        return 'FY4A'
    return 'FY4A'  # default


def _extract_timestamp(filename: str) -> Optional[str]:
    """Try to extract an ISO-formatted timestamp string from a filename.

    FY-4 filenames embed a 14-digit start time (YYYYMMDDHHMMSS), e.g.
    FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20250721034500_...
                                                 ^^^^^^^^^^^^^^^^
    """
    # Prefer 14-digit compact datetime (YYYYMMDDHHMMSS)
    m = re.search(r'_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_', filename)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    # Fallback: YYYYMMDD_HHMM
    m = re.search(r'(\d{8})[_-](\d{4})', filename)
    if m:
        date, time4 = m.group(1), m.group(2)
        return f"{date[:4]}-{date[4:6]}-{date[6:8]} {time4[:2]}:{time4[2:4]}"
    return None
