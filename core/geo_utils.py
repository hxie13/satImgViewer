"""
Geographic and projection utilities for coordinate transformation and extent handling.
"""
import os
import logging
import numpy as np
from typing import Optional, Tuple, Any
from .geometry import extract_geographic_extent

logger = logging.getLogger(__name__)

# Debug flag - check once at module load
_DEBUG = os.environ.get('SATIMG_DEBUG') is not None


def get_geographic_extent(area_def):
    """
    Convert satellite projection extent to geographic (lat/lon) coordinates.

    Uses the metadata-based extent extraction from projections module.

    Args:
        area_def: Pyresample AreaDefinition with area_extent in native projection

    Returns:
        Tuple (west, east, south, north) in degrees, or None if conversion fails
    """
    if not area_def:
        if _DEBUG:
            logger.debug("[GeoUtils] area_def is None")
        return None

    # Fast path: longlat/plate_carree AreaDefinition — area_extent IS the geographic extent
    # (west, south, east, north) in degrees, so no projection math needed.
    try:
        proj_dict = getattr(area_def, 'proj_dict', {})
        if proj_dict.get('proj') in ('longlat', 'latlong', 'eqc'):
            ae = getattr(area_def, 'area_extent', None)
            if ae and len(ae) == 4:
                west  = max(-180.0, min(180.0, float(ae[0])))
                south = max( -90.0, min( 90.0, float(ae[1])))
                east  = max(-180.0, min(180.0, float(ae[2])))
                north = max( -90.0, min( 90.0, float(ae[3])))
                if _DEBUG:
                    logger.debug(f"[GeoUtils] longlat fast path: W={west}, E={east}, S={south}, N={north}")
                return (west, east, south, north)
    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] longlat fast path failed: {e}")

    # NOTE: satellite_coverage attribute is not set by any current driver — removed.

    try:
        # Use the new metadata-based extraction from projections module
        if _DEBUG:
            logger.debug("[GeoUtils] Calling extract_geographic_extent()...")
        extent = extract_geographic_extent(area_def)
        if extent:
            west, east, south, north = extent
            if _DEBUG:
                logger.debug(f"[GeoUtils] Extracted extent: W={west}, E={east}, S={south}, N={north}")

            # Convert to Python native types to avoid numpy comparison issues
            west = float(west)
            east = float(east)
            south = float(south)
            north = float(north)

            # Clamp to valid ranges
            west = max(-180, min(180, west))
            east = max(-180, min(180, east))
            south = max(-90, min(90, south))
            north = max(-90, min(90, north))

            if _DEBUG:
                logger.debug(f"[GeoUtils] After clamping: W={west}, E={east}, S={south}, N={north}")

            # Return in (west, east, south, north) order for consistency
            return (west, east, south, north)
        else:
            if _DEBUG:
                logger.debug("[GeoUtils] extract_geographic_extent returned None")
    except Exception as e:
        if _DEBUG:
            logger.exception(f"[GeoUtils] extract_geographic_extent() exception: {e}")

    # Fallback: try to_cartopy_crs() and manually compute bounds
    try:
        # Get the CRS and use it to transform corners
        if hasattr(area_def, 'crs'):
            crs = area_def.crs
            extent = getattr(area_def, 'area_extent', None)

            if extent and len(extent) == 4:
                # area_extent is (x_min, y_min, x_max, y_max) in projection coords
                x_min, y_min, x_max, y_max = extent

                # Try to use pyproj to transform to lat/lon
                try:
                    from pyproj import Transformer
                    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

                    # Transform corners
                    corners_x = [x_min, x_max, x_min, x_max]
                    corners_y = [y_min, y_max, y_min, y_max]

                    lons, lats = transformer.transform(corners_x, corners_y)

                    west = float(np.nanmin(lons))
                    east = float(np.nanmax(lons))
                    south = float(np.nanmin(lats))
                    north = float(np.nanmax(lats))

                    if not any(np.isnan([west, south, east, north])):
                        # Clamp and validate
                        return (west, east, south, north)
                except Exception:
                    pass
    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] CRS-based conversion failed: {e}")

    return None


def create_extent_array_for_imshow(area_def):
    """
    Create an extent array suitable for matplotlib imshow() in geographic coordinates.

    For matplotlib imshow, extent is [left, right, bottom, top] in data coordinates.
    For geographic display, this is [west, east, south, north] in degrees.

    Args:
        area_def: Pyresample AreaDefinition

    Returns:
        Tuple (left, right, bottom, top) for imshow, or None if conversion fails
    """
    geo_extent = get_geographic_extent(area_def)

    if geo_extent is None:
        return None

    # geo_extent is (west, east, south, north)
    west, east, south, north = geo_extent

    # For imshow: extent = [left, right, bottom, top]
    # which corresponds to [west, east, south, north] in geographic coordinates
    if _DEBUG:
        logger.debug(f"[GeoUtils] create_extent_array_for_imshow: returning ({west}, {east}, {south}, {north})")
    return (west, east, south, north)


def transform_coordinates(lons: Any, lats: Any,
                         src_crs: str = 'EPSG:4326',
                         dst_crs: str = 'EPSG:3857') -> Tuple[Any, Any]:
    """
    Transform coordinates between CRS.

    Args:
        lons: Longitude array
        lats: Latitude array
        src_crs: Source CRS
        dst_crs: Destination CRS

    Returns:
        Tuple of (transformed_lons, transformed_lats)
    """
    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
        return transformer.transform(lons, lats)

    except ImportError:
        if _DEBUG:
            logger.debug("Pyproj not available for coordinate transformation")
        return lons, lats


def create_meshgrid_from_extent(west: float, east: float,
                                south: float, north: float,
                                width: int, height: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Create lon/lat meshgrid from extent.

    Args:
        west, east: Longitude bounds
        south, north: Latitude bounds
        width: Grid width
        height: Grid height

    Returns:
        Tuple of (lon_grid, lat_grid)
    """
    lons = np.linspace(west, east, width)
    lats = np.linspace(south, north, height)

    lon_grid, lat_grid = np.meshgrid(lons, lats)

    return lon_grid, lat_grid
