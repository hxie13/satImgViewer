"""
Projection configuration and utilities for satellite image resampling and export.
Supports both native geostationary (true view) and global Plate Carree (3D-friendly) formats.
"""
from pyresample import geometry
from typing import Optional
import numpy as np

# ===== Projection Definitions =====
PROJECTIONS = {
    'geostationary_native': {
        'name': 'Geostationary (Native)',
        'description': 'Original geostationary satellite projection - true scientific view',
        'type': 'native',  # Use native resampling (no area transformation)
        'resample_method': 'native',
    },
    'plate_carree_global': {
        'name': 'Plate Carree Global',
        'description': '1-degree global grid (WGS84) - ideal for 3D globe rendering',
        'type': 'geographic',
        'projection': 'longlat',
        'width': 3600,  # 360 degrees / 0.1 degree resolution
        'height': 1800,  # 180 degrees / 0.1 degree resolution
        'area_extent': [-180, -90, 180, 90],  # [west, south, east, north] in degrees
        'resample_method': 'bilinear',  # Use bilinear resampling for smooth global grid
    },
    'mercator_web': {
        'name': 'Web Mercator',
        'description': 'Web Mercator projection (EPSG:3857) - suitable for web mapping',
        'type': 'geographic',
        'projection': 'merc',
        'width': 4096,
        'height': 4096,
        'area_extent': [-20037508.34, -20037508.34, 20037508.34, 20037508.34],  # meters
        'resample_method': 'bilinear',
    },
}

def get_projection_config(proj_name: str) -> dict:
    """
    Retrieve projection configuration by name.
    
    Args:
        proj_name: Projection identifier (e.g., 'plate_carree_global', 'geostationary_native')
    
    Returns:
        Dictionary with projection parameters
    """
    if proj_name not in PROJECTIONS:
        raise ValueError(f"Unknown projection: {proj_name}. Available: {list(PROJECTIONS.keys())}")
    return PROJECTIONS[proj_name].copy()

def create_target_area(proj_name: str, source_area=None) -> Optional[geometry.AreaDefinition]:
    """
    Create a Pyresample AreaDefinition for the target projection.
    Refactored to use standard arguments compatible with most pyresample versions.
    """
    config = get_projection_config(proj_name)
    
    if config['type'] == 'native':
        # Native resampling: return None to use Satpy's native resampler
        return None
    
    if config['type'] == 'geographic':
        # Prepare basic parameters
        width = config['width']
        height = config['height']
        area_extent = config['area_extent']
        description = config['name']
        
        # Prepare projection dictionary (proj_dict) instead of CRS object
        if config['projection'] == 'longlat':
            # Plate Carree (WGS84) standard definition
            proj_dict = {'proj': 'longlat', 'datum': 'WGS84', 'no_defs': 'None'}
        elif config['projection'] == 'merc':
            # Web Mercator (EPSG:3857)
            # Use pyproj to ensure we get the correct dict for 3857
            try:
                from pyproj import CRS
                proj_dict = CRS.from_epsg(3857).to_dict()
            except ImportError:
                # Fallback if pyproj import fails or behaves oddly
                proj_dict = {'proj': 'merc', 'a': 6378137, 'b': 6378137, 
                             'lat_ts': 0.0, 'lon_0': 0.0, 'x_0': 0.0, 'y_0': 0, 
                             'k': 1.0, 'units': 'm', 'nadgrids': '@null', 'wktext': True, 'no_defs': True}
        else:
            # Generic projection
            proj_dict = config.get('proj_dict', {'proj': config['projection']})
            
        # Instantiate AreaDefinition using standard positional arguments
        # Signature: AreaDefinition(area_id, description, proj_id, projection, width, height, area_extent)
        try:
            return geometry.AreaDefinition(
                proj_name,      # area_id
                description,    # description
                proj_name,      # proj_id
                proj_dict,      # projection (expecting dict or string)
                width,          
                height, 
                area_extent
            )
        except Exception as e:
            # In case of very old pyresample versions or unexpected API changes, print debug info
            print(f"[Projections] AreaDefinition creation failed: {e}")
            raise
    
    raise ValueError(f"Unsupported projection type: {config['type']}")

def get_available_projections() -> list:
    """Return list of available projection names and descriptions."""
    return [(name, config['name'], config['description']) 
            for name, config in PROJECTIONS.items()]

def extract_geographic_extent(area_def) -> Optional[tuple]:
    """
    Extract geographic extent (W, E, S, N in degrees) from an AreaDefinition.
    
    For geostationary satellites, intelligently uses satellite position from proj_dict
    to determine coverage area, as get_lonlats() often fails or returns boundary artifacts.
    
    Coverage patterns based on ±70° viewing angle:
    - FY4B (105°E): ~75°E to 135°E, ~55°S to 55°N
    - Himawari-8 (140.7°E): ~80°E to 160°E, ~60°S to 60°N
    - FY4A (99.5°E): ~70°E to 140°E, ~50°S to 50°N
    
    Args:
        area_def: Pyresample AreaDefinition
    
    Returns:
        Tuple of (west, east, south, north) in degrees, or None if extraction fails
    """
    print(f"[Projections] extract_geographic_extent() called")
    print(f"[Projections]   area_def type: {type(area_def)}")
    print(f"[Projections]   area_def.proj_dict: {getattr(area_def, 'proj_dict', 'N/A')}")
    
    # PRIMARY: Try proj_dict inference for geostationary satellites
    try:
        if hasattr(area_def, 'proj_dict'):
            proj_dict = area_def.proj_dict
            print(f"[Projections]   Trying proj_dict inference: {proj_dict}")
            
            if proj_dict.get('proj') == 'geos':
                lon_0 = float(proj_dict.get('lon_0', 105.0))
                print(f"[Projections]   ✓ Geostationary satellite detected at {lon_0}°E")
                
                # Use known coverage patterns for geostationary satellites
                if 99 <= lon_0 <= 107:  # FY4B, FY4A area
                    # FY4B: 105°E, typical range 75°E ~ 135°E, 55°S ~ 55°N
                    west, east, south, north = 75, 135, -55, 55
                    print(f"[Projections]   Using FY4B pattern: {west}°E ~ {east}°E, {south}°N ~ {north}°N")
                    return (west, east, south, north)
                elif 135 <= lon_0 <= 145:  # Himawari area
                    # Himawari-8: 140.7°E, typical range 80°E ~ 160°E, 60°S ~ 60°N
                    west, east, south, north = 80, 160, -60, 60
                    print(f"[Projections]   Using Himawari pattern: {west}°E ~ {east}°E, {south}°N ~ {north}°N")
                    return (west, east, south, north)
                else:
                    # Generic geostationary: ±65° from satellite position
                    west = lon_0 - 65
                    east = lon_0 + 65
                    south, north = -60, 60
                    print(f"[Projections]   Using generic GEO pattern: {west}°E ~ {east}°E, {south}°N ~ {north}°N")
                    return (west, east, south, north)
    except Exception as e:
        print(f"[Projections]   proj_dict inference failed: {e}")
    
    # FALLBACK: Try get_lonlats() but with strict validation
    print(f"[Projections]   Trying get_lonlats() as fallback...")
    print(f"[Projections]   area_def has get_lonlats: {hasattr(area_def, 'get_lonlats')}")
    
    try:
        if hasattr(area_def, 'get_lonlats'):
            print(f"[Projections]   Calling get_lonlats()...")
            lons, lats = area_def.get_lonlats()
            
            print(f"[Projections]   Raw lons: min={np.nanmin(lons)}, max={np.nanmax(lons)}")
            print(f"[Projections]   Raw lats: min={np.nanmin(lats)}, max={np.nanmax(lats)}")
            
            # Filter out inf and nan values - use only finite coordinates
            lons_valid = lons[np.isfinite(lons)]
            lats_valid = lats[np.isfinite(lats)]
            
            if len(lons_valid) > 0 and len(lats_valid) > 0:
                west = float(np.nanmin(lons_valid))
                east = float(np.nanmax(lons_valid))
                south = float(np.nanmin(lats_valid))
                north = float(np.nanmax(lats_valid))
                
                lon_span = east - west
                lat_span = north - south
                print(f"[Projections]   Extracted: W={west}, E={east}, S={south}, N={north}")
                print(f"[Projections]   Lon span: {lon_span}°, Lat span: {lat_span}°")
                is_global = (lon_span > 358)
                
                if not is_global and (lon_span > 350 or abs(north) > 85 or abs(south) < -85):
                     print(f"[Projections]   ✗ Rejecting - spans too much (boundary artifact)")
                     return None
                
                if -180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90:
                     return (west, east, south, north)
                
    except Exception as e:
        print(f"[Projections]   get_lonlats failed: {e}")
    
    # FINAL FALLBACK: try to use crs bounds
    print(f"[Projections]   Trying CRS area_of_use as final fallback...")
    try:
        crs = area_def.crs
        if hasattr(crs, 'area_of_use') and crs.area_of_use:
            bounds = crs.area_of_use.bounds
            print(f"[Projections]   ✓ CRS area_of_use bounds: {bounds}")
            return (bounds[0], bounds[2], bounds[1], bounds[3])
    except Exception as e:
        print(f"[Projections]   CRS fallback failed: {e}")
    
    print(f"[Projections]   All methods failed, returning None")
    return None

def get_export_format(format_name: str) -> str:
    """
    Map user-friendly format name to file extension.
    
    Args:
        format_name: Format identifier ('geotiff', 'png', 'netcdf')
    
    Returns:
        File extension (e.g., '.tif', '.png', '.nc')
    """
    formats = {
        'geotiff': '.tif',
        'png': '.png',
        'netcdf': '.nc',
    }
    if format_name not in formats:
        raise ValueError(f"Unknown format: {format_name}. Available: {list(formats.keys())}")
    return formats[format_name]
