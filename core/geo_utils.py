"""
Geographic and projection utilities for coordinate transformation and extent handling.
"""
import numpy as np
from .projections import extract_geographic_extent

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
        print(f"[GeoUtils] area_def is None")
        return None
    
    # First, check if area_def has satellite coverage information
    try:
        if hasattr(area_def, 'satellite_coverage'):
            coverage = area_def.satellite_coverage
            if coverage and len(coverage) == 4:
                print(f"[GeoUtils] ✓ Using satellite coverage: {coverage}")
                west, east, south, north = coverage
                
                # Clamp to valid ranges
                west = max(-180, min(180, west))
                east = max(-180, min(180, east))
                south = max(-90, min(90, south))
                north = max(-90, min(90, north))
                
                print(f"[GeoUtils] After clamping: W={west}, E={east}, S={south}, N={north}")
                return (west, east, south, north)
    except Exception as e:
        print(f"[GeoUtils] Satellite coverage extraction failed: {e}")
    
    try:
        # Use the new metadata-based extraction from projections module
        print(f"[GeoUtils] Calling extract_geographic_extent()...")
        extent = extract_geographic_extent(area_def)
        if extent:
            west, east, south, north = extent
            print(f"[GeoUtils] ✓ Extracted extent: W={west}, E={east}, S={south}, N={north}")
            
            # Clamp to valid ranges
            west = max(-180, min(180, west))
            east = max(-180, min(180, east))
            south = max(-90, min(90, south))
            north = max(-90, min(90, north))
            
            print(f"[GeoUtils] After clamping: W={west}, E={east}, S={south}, N={north}")
            
            # Return in (west, east, south, north) order for consistency
            return (west, east, south, north)
        else:
            print(f"[GeoUtils] extract_geographic_extent returned None")
    except Exception as e:
        print(f"[GeoUtils] extract_geographic_extent() exception: {e}")
        import traceback
        traceback.print_exc()
    
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
        print(f"[GeoUtils] CRS-based conversion failed: {e}")
    
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
    print(f"[GeoUtils] create_extent_array_for_imshow: returning ({west}, {east}, {south}, {north})")
    return (west, east, south, north)
