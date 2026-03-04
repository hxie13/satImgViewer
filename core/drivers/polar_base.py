"""
Polar-Orbit Satellite Base Driver

Provides common swath-data handling shared by all sun-synchronous / polar-orbit
satellite drivers (e.g. FY-3D, FY-3E, Terra/Aqua MODIS, Suomi-NPP VIIRS).

Subclasses typically only need to implement:
  - ``_detect_product_level()``
  - ``_load_level_data()`` (or ``load_files()``)
  - ``get_available_bands()``
  - Satellite-specific resampling grids / resolutions
"""
import logging
from abc import abstractmethod
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from .base import BaseSatelliteDriver, SatelliteFileInfo, ProcessingParams

logger = logging.getLogger(__name__)


class BasePolarDriver(BaseSatelliteDriver):
    """
    Intermediate base class for polar-orbit (swath) satellite drivers.

    Adds:
    - Swath data type detection
    - Swath → regular grid resampling via pyresample
    - Multi-resolution band alignment (e.g. 250 m + 1 km → common grid)
    - Geographic extent extraction from swath lon/lat arrays
    """

    # Subclasses set these at the class level
    NATIVE_SWATH_RESOLUTIONS: Dict[str, int] = {}  # band_name -> resolution_m
    DEFAULT_RESAMPLE_RESOLUTION_M: int = 1000       # target grid resolution in metres

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self._swath_lons: Optional[np.ndarray] = None
        self._swath_lats: Optional[np.ndarray] = None
        self._is_swath: bool = False
        self._geo_file_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Swath Detection
    # ------------------------------------------------------------------

    def is_swath_data(self) -> bool:
        """Return True if the currently loaded data is swath (not gridded)."""
        return self._is_swath

    def _detect_swath(self, file_paths: List[str]) -> bool:
        """
        Heuristically determine whether the file set contains swath data.

        Swath data is recognised by the presence of a separate geolocation
        file (e.g. GEO suffix for FY-3D MERSI) or by examining the HDF5
        group structure.  Subclasses should override this if the heuristic
        does not apply.

        Args:
            file_paths: List of file paths in the current group.

        Returns:
            True if swath data is detected.
        """
        geo_suffixes = ('_GEO', '_GEO.HDF', '_GEO.h5', '_GEO.nc')
        for p in file_paths:
            upper = p.upper()
            if any(upper.endswith(s.upper()) for s in geo_suffixes):
                self._geo_file_path = p
                return True
        return False

    # ------------------------------------------------------------------
    # Swath → Grid Resampling
    # ------------------------------------------------------------------

    def resample_swath_to_grid(
        self,
        data: np.ndarray,
        lons: np.ndarray,
        lats: np.ndarray,
        target_resolution_m: Optional[int] = None,
        target_extent: Optional[Tuple[float, float, float, float]] = None,
        method: str = 'nearest',
    ) -> Tuple[np.ndarray, Any]:
        """
        Resample swath data to a regular lon/lat grid using pyresample.

        Args:
            data:                2-D (or 3-D band-last) swath data array.
            lons:                Swath longitude array (same shape as data[..., 0]).
            lats:                Swath latitude array (same shape as data[..., 0]).
            target_resolution_m: Grid resolution in metres; defaults to
                                 ``DEFAULT_RESAMPLE_RESOLUTION_M``.
            target_extent:       (west, east, south, north) in degrees.
                                 Computed from swath bounds if not provided.
            method:              Resampling method: 'nearest' or 'bilinear'.

        Returns:
            Tuple of (resampled_data, area_definition).
        """
        try:
            from pyresample import geometry as _geom
            from pyresample.kd_tree import resample_nearest, resample_gauss
        except ImportError as exc:
            raise ImportError("pyresample is required for swath resampling.") from exc

        res_m = target_resolution_m or self.DEFAULT_RESAMPLE_RESOLUTION_M

        # 1. Determine geographic extent
        if target_extent is None:
            target_extent = self._extent_from_swath(lons, lats)

        west, east, south, north = target_extent

        # 2. Build grid dimensions — cap at MAX_SIDE to prevent OOM on global swaths
        MAX_SIDE = 2048
        lon_range = east - west
        lat_range = north - south
        deg_per_m = 1.0 / 111_320.0          # approx degrees per metre at equator
        res_deg = res_m * deg_per_m
        width  = min(MAX_SIDE, max(1, int(round(lon_range / res_deg))))
        height = min(MAX_SIDE, max(1, int(round(lat_range / res_deg))))
        logger.info("[PolarBase] Resample grid: %dx%d (res=%.0fm, extent=%.1f°×%.1f°)",
                    width, height, res_m, lon_range, lat_range)

        # 3. Create pyresample AreaDefinition
        proj_dict = {'proj': 'longlat', 'datum': 'WGS84'}
        area_extent = (west, south, east, north)
        area_def = _geom.AreaDefinition(
            area_id='swath_grid',
            description=f'Polar swath resampled at {res_m}m',
            proj_id='longlat',
            projection=proj_dict,
            width=width,
            height=height,
            area_extent=area_extent,
        )

        # 4. Build SwathDefinition
        valid = np.isfinite(lons) & np.isfinite(lats)
        lons_clean = np.where(valid, lons, 0.0)
        lats_clean = np.where(valid, lats, 0.0)
        swath_def = _geom.SwathDefinition(lons=lons_clean, lats=lats_clean)

        # 5. Resample
        radius = res_m * 2.5  # search radius in metres
        try:
            if method == 'nearest':
                resampled = resample_nearest(
                    swath_def, data, area_def,
                    radius_of_influence=radius,
                    fill_value=np.nan,
                )
            else:
                resampled = resample_gauss(
                    swath_def, data, area_def,
                    radius_of_influence=radius,
                    sigmas=radius / 2,
                    fill_value=np.nan,
                )
        except Exception as exc:
            logger.error(f"[PolarBase] Resampling failed: {exc}")
            raise

        return resampled, area_def

    # ------------------------------------------------------------------
    # Multi-resolution Alignment
    # ------------------------------------------------------------------

    def align_to_common_resolution(
        self,
        bands_data: Dict[str, np.ndarray],
        target_resolution_m: Optional[int] = None,
    ) -> Dict[str, np.ndarray]:
        """
        Upsample or downsample each band so all arrays share the same shape.

        Uses nearest-neighbour zoom (scipy.ndimage.zoom) so no new values
        are invented for categorical / quality-flag bands.

        Args:
            bands_data:          {band_name: 2-D array}
            target_resolution_m: Desired resolution; defaults to the finest
                                 available resolution across all bands.

        Returns:
            Dict with all bands at the target shape.
        """
        if not bands_data:
            return bands_data

        try:
            from scipy.ndimage import zoom
        except ImportError:
            logger.warning("[PolarBase] scipy not available; skipping alignment")
            return bands_data

        # Determine target shape as the largest (finest) array
        shapes = {k: v.shape[:2] for k, v in bands_data.items()}
        target_shape = max(shapes.values(), key=lambda s: s[0] * s[1])

        aligned: Dict[str, np.ndarray] = {}
        for band, arr in bands_data.items():
            h, w = arr.shape[:2]
            th, tw = target_shape
            if (h, w) == target_shape:
                aligned[band] = arr
            else:
                zoom_h = th / h
                zoom_w = tw / w
                if arr.ndim == 2:
                    aligned[band] = zoom(arr, (zoom_h, zoom_w), order=0)
                else:
                    # 3-D: zoom spatial dims only
                    aligned[band] = zoom(arr, (zoom_h, zoom_w, 1), order=0)
                logger.debug(f"[PolarBase] Aligned {band}: {(h,w)} -> {aligned[band].shape[:2]}")

        return aligned

    # ------------------------------------------------------------------
    # Geographic Extent Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extent_from_swath(
        lons: np.ndarray,
        lats: np.ndarray,
        padding_deg: float = 0.1,
    ) -> Tuple[float, float, float, float]:
        """
        Compute (west, east, south, north) from swath lon/lat arrays.

        Args:
            lons:        Longitude array (may contain NaN / fill values).
            lats:        Latitude array (same shape).
            padding_deg: Extra margin added to all sides.

        Returns:
            (west, east, south, north) in degrees.
        """
        valid = np.isfinite(lons) & np.isfinite(lats)
        if not np.any(valid):
            return (-180.0, 180.0, -90.0, 90.0)

        west  = float(np.min(lons[valid]))  - padding_deg
        east  = float(np.max(lons[valid]))  + padding_deg
        south = float(np.min(lats[valid]))  - padding_deg
        north = float(np.max(lats[valid]))  + padding_deg

        # Clamp to valid ranges
        west  = max(west,  -180.0)
        east  = min(east,   180.0)
        south = max(south,  -90.0)
        north = min(north,   90.0)

        return (west, east, south, north)

    # ------------------------------------------------------------------
    # Abstract stubs (remind subclasses what to implement)
    # ------------------------------------------------------------------

    @abstractmethod
    def load_files(self, file_paths: List[str], **kwargs) -> bool:
        """Load a group of satellite files.  Must set self._is_swath."""
        ...
