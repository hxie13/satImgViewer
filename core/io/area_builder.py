"""
Area Definition Builder

Constructs pyresample AreaDefinition objects directly from satellite
navigation metadata, without requiring satpy.
"""
import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def build_geos_area(
    lon_0: float,
    sat_height_m: float,
    img_width: int,
    img_height: int,
    ifov_x: float,
    ifov_y: float,
    area_id: Optional[str] = None,
):
    """
    Build a geostationary AreaDefinition from satellite navigation parameters.

    Args:
        lon_0:         Sub-satellite longitude in degrees (e.g. 104.7 for FY-4A)
        sat_height_m:  Satellite height above Earth center in meters (~35786023)
        img_width:     Image pixel width
        img_height:    Image pixel height
        ifov_x:        Pixel angular size in the E-W direction (radians/pixel)
        ifov_y:        Pixel angular size in the N-S direction (radians/pixel)
        area_id:       Optional ID string for the AreaDefinition

    Returns:
        pyresample.geometry.AreaDefinition
    """
    from pyresample import geometry

    h = sat_height_m
    # Half-extent in metres on the projection plane
    half_x = ifov_x * h * img_width / 2.0
    half_y = ifov_y * h * img_height / 2.0

    proj_dict = {
        'proj': 'geos',
        'lon_0': lon_0,
        'h': h,
        'a': 6378137.0,
        'b': 6356752.3142,
        'units': 'm',
    }

    _id = area_id or f'geos_{lon_0:.1f}'
    area = geometry.AreaDefinition(
        _id,
        f'Geostationary native {lon_0:.1f}°E',
        _id,
        proj_dict,
        img_width,
        img_height,
        area_extent=(-half_x, -half_y, half_x, half_y),
    )
    logger.debug(
        f"[AreaBuilder] GEOS area: lon_0={lon_0}, size={img_width}x{img_height}, "
        f"extent=({-half_x:.0f}, {-half_y:.0f}, {half_x:.0f}, {half_y:.0f})"
    )
    return area


def build_lonlat_area(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    area_id: str = 'lonlat',
):
    """
    Build a WGS84 plate-carree AreaDefinition from geographic bounds.

    Args:
        west, south, east, north: Bounding box in degrees
        width, height:            Grid dimensions in pixels
        area_id:                  ID string for the AreaDefinition

    Returns:
        pyresample.geometry.AreaDefinition
    """
    from pyresample import geometry

    # PROJ no longer accepts '+units=deg' for longlat in recent versions.
    proj_dict = {'proj': 'longlat', 'datum': 'WGS84'}
    area = geometry.AreaDefinition(
        area_id,
        'WGS84 Plate Carree',
        area_id,
        proj_dict,
        width,
        height,
        area_extent=(west, south, east, north),
    )
    logger.debug(
        f"[AreaBuilder] LonLat area: ({west},{south})→({east},{north}), size={width}x{height}"
    )
    return area


def build_area_from_lonlat_arrays(
    lons: np.ndarray,
    lats: np.ndarray,
    target_resolution_deg: float = 0.01,
    area_id: str = 'swath_lonlat',
):
    """
    Derive a regular lon/lat grid AreaDefinition from swath coordinate arrays.

    Args:
        lons:                   2-D array of longitudes
        lats:                   2-D array of latitudes
        target_resolution_deg:  Target pixel size in degrees
        area_id:                ID string for the AreaDefinition

    Returns:
        pyresample.geometry.AreaDefinition
    """
    valid_lons = lons[np.isfinite(lons)]
    valid_lats = lats[np.isfinite(lats)]

    if valid_lons.size == 0 or valid_lats.size == 0:
        raise ValueError("No valid coordinate points found in swath arrays")

    west = float(np.nanmin(valid_lons))
    east = float(np.nanmax(valid_lons))
    south = float(np.nanmin(valid_lats))
    north = float(np.nanmax(valid_lats))

    # Add a small padding
    pad = target_resolution_deg * 2
    west = max(-180.0, west - pad)
    east = min(180.0, east + pad)
    south = max(-90.0, south - pad)
    north = min(90.0, north + pad)

    width = max(1, int(round((east - west) / target_resolution_deg)))
    height = max(1, int(round((north - south) / target_resolution_deg)))

    return build_lonlat_area(west, south, east, north, width, height, area_id)
