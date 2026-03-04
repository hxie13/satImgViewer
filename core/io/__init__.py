"""
core.io — Direct satellite data I/O layer (satpy-free)

Provides lightweight readers for each supported satellite format,
using h5py, xarray, and numpy instead of satpy.

Exported readers:
  FY4Reader          — FY-4A/B AGRI L1 HDF5 (h5py + LUT calibration)
  FY4L2Reader        — FY-4A/B AGRI L2 NetCDF (xarray)
  FY3DReader         — FY-3D MERSI-2 L1 HDF5 (h5py + polynomial calibration)
  HimawariNCReader   — Himawari-8/9 AHI L1b gridded NetCDF (xarray)

Area builders:
  build_geos_area           — Geostationary AreaDefinition from navigation params
  build_lonlat_area         — WGS84 plate-carree AreaDefinition from bounds
  build_area_from_lonlat_arrays — Derive AreaDefinition from swath coordinates
"""

from .fy4_reader import FY4Reader, FY4L2Reader
from .fy3d_reader import FY3DReader
from .himawari_reader import HimawariNCReader
from .area_builder import build_geos_area, build_lonlat_area, build_area_from_lonlat_arrays

__all__ = [
    'FY4Reader',
    'FY4L2Reader',
    'FY3DReader',
    'HimawariNCReader',
    'build_geos_area',
    'build_lonlat_area',
    'build_area_from_lonlat_arrays',
]
