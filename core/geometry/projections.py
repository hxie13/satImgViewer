"""
Projection Configuration and Factory

Enhanced projection system with factory pattern for creating custom projections.
Supports geostationary, geographic, and custom projections.
"""
import os
import threading
import logging
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

# Debug flag - check once at module load
_DEBUG = os.environ.get('SATIMG_DEBUG') is not None

# Lazy import for pyresample to avoid import errors
_geometry = None


def _get_geometry():
    """Lazy import of pyresample.geometry."""
    global _geometry
    if _geometry is None:
        from pyresample import geometry as _geom
        _geometry = _geom
    return _geometry


def _wrap_longitudes_180(lons: np.ndarray) -> np.ndarray:
    """
    Wrap longitude values to [-180, 180).

    Args:
        lons: Longitude array in degrees.

    Returns:
        Wrapped longitude array.
    """
    return ((lons + 180.0) % 360.0) - 180.0


def _compute_circular_lon_bounds(
    lons_deg: np.ndarray,
) -> Optional[Tuple[float, float, bool, float]]:
    """
    Compute longitude bounds on a circle and detect dateline crossing.

    This finds the minimum covering arc by removing the largest gap in sorted
    longitudes.

    Args:
        lons_deg: Longitude samples in degrees (any range).

    Returns:
        Tuple of (west, east, crosses_dateline, span_deg), or None.
    """
    if lons_deg is None or lons_deg.size == 0:
        return None

    lons_wrapped = _wrap_longitudes_180(np.asarray(lons_deg, dtype=np.float64))
    lons_sorted = np.sort(lons_wrapped)
    count = int(lons_sorted.size)
    if count == 0:
        return None
    if count == 1:
        lon = float(lons_sorted[0])
        return (lon, lon, False, 0.0)

    gaps = np.diff(lons_sorted)
    wrap_gap = float((lons_sorted[0] + 360.0) - lons_sorted[-1])
    gaps = np.concatenate([gaps, np.array([wrap_gap], dtype=np.float64)])
    max_gap_idx = int(np.argmax(gaps))
    max_gap = float(gaps[max_gap_idx])

    west = float(lons_sorted[(max_gap_idx + 1) % count])
    east = float(lons_sorted[max_gap_idx % count])
    span = max(0.0, 360.0 - max_gap)
    crosses_dateline = east < west
    return (west, east, crosses_dateline, span)


def _sample_area_lonlats(area_def, max_points: int = 200_000) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Sample lon/lat arrays from AreaDefinition with bounded memory cost.

    Args:
        area_def: Pyresample geometry object.
        max_points: Approximate maximum sampled points.

    Returns:
        Tuple (lons, lats), or None if unavailable.
    """
    if area_def is None or not hasattr(area_def, 'get_lonlats'):
        return None

    width = int(getattr(area_def, 'width', 0) or 0)
    height = int(getattr(area_def, 'height', 0) or 0)
    data_slice = None

    if width > 0 and height > 0:
        total_points = width * height
        if total_points > max_points:
            step = max(1, int(np.sqrt(total_points / float(max_points))))
            data_slice = np.s_[::step, ::step]

    try:
        if data_slice is not None:
            return area_def.get_lonlats(data_slice=data_slice, dtype=np.float32)
        return area_def.get_lonlats(dtype=np.float32)
    except TypeError:
        # Older pyresample variants may not support dtype kwarg consistently.
        if data_slice is not None:
            return area_def.get_lonlats(data_slice=data_slice)
        return area_def.get_lonlats()


def _extract_valid_lonlat_extent(
    area_def,
    max_points: int = 200_000,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Extract geographic extent from valid lon/lat samples.

    Handles dateline-crossing scenes by detecting circular longitude span.
    Because the current longlat target grid in this project is a single
    non-wrapping bbox, dateline-crossing cases fall back to a conservative
    non-wrapping envelope to preserve all valid pixels.

    Args:
        area_def: Pyresample geometry object.
        max_points: Approximate maximum sampled points.

    Returns:
        Tuple (west, east, south, north) in degrees, or None.
    """
    sampled = _sample_area_lonlats(area_def, max_points=max_points)
    if sampled is None:
        return None
    lons, lats = sampled

    valid = np.isfinite(lons) & np.isfinite(lats)
    if not np.any(valid):
        return None

    lons_valid = _wrap_longitudes_180(np.asarray(lons[valid], dtype=np.float64))
    lats_valid = np.asarray(lats[valid], dtype=np.float64)
    if lons_valid.size == 0 or lats_valid.size == 0:
        return None

    lon_bounds = _compute_circular_lon_bounds(lons_valid)
    if lon_bounds is None:
        return None
    west, east, crosses_dateline, lon_span = lon_bounds

    south = float(np.nanmin(lats_valid))
    north = float(np.nanmax(lats_valid))

    if crosses_dateline:
        # Current rendering/resampling chain expects non-wrapping longitude bbox.
        # Use conservative envelope to avoid dropping coverage at the dateline.
        west = float(np.nanmin(lons_valid))
        east = float(np.nanmax(lons_valid))
        if _DEBUG:
            logger.debug(
                "[GeoUtils] Dateline crossing detected (span=%.2f°); "
                "using non-wrapping envelope W=%.2f E=%.2f",
                lon_span, west, east
            )

    # Clamp to valid geographic ranges
    west = max(-180.0, min(180.0, float(west)))
    east = max(-180.0, min(180.0, float(east)))
    south = max(-90.0, min(90.0, float(south)))
    north = max(-90.0, min(90.0, float(north)))

    if east < west:
        # Safety fallback for any unexpected numeric edge cases.
        west = float(np.nanmin(lons_valid))
        east = float(np.nanmax(lons_valid))
        west = max(-180.0, min(180.0, west))
        east = max(-180.0, min(180.0, east))

    if not all(np.isfinite([west, east, south, north])):
        return None
    if north < south:
        south, north = north, south

    return (west, east, south, north)


class ProjectionType(Enum):
    """Enumeration of projection types."""
    GEOSTATIONARY = "geostationary"
    PLATE_CARREE = "plate_carree"
    LAMBERT_CONFORMAL = "lcc"
    POLAR_STEREOGRAPHIC = "ps"
    EQUAL_AREA = "aea"
    CUSTOM = "custom"


@dataclass
class ProjectionConfig:
    """Configuration for a projection."""
    name: str
    proj_type: ProjectionType
    description: str
    proj_dict: Dict[str, Any]
    width: int
    height: int
    area_extent: Tuple[float, float, float, float]  # (west, south, east, north) or (xmin, ymin, xmax, ymax)
    resample_method: str = "nearest"

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'type': self.proj_type.value,
            'description': self.description,
            'proj_dict': self.proj_dict,
            'width': self.width,
            'height': self.height,
            'area_extent': self.area_extent,
            'resample_method': self.resample_method,
        }


# =============================================================================
# Predefined Projections
# =============================================================================

PREDEFINED_PROJECTIONS: Dict[str, ProjectionConfig] = {
    'geostationary_native': ProjectionConfig(
        name='Geostationary (Native)',
        proj_type=ProjectionType.GEOSTATIONARY,
        description='Original geostationary satellite projection - true scientific view',
        proj_dict={
            'proj': 'geos',
            'lon_0': 140.7,
            'lat_0': 0.0,
            'h': 35785831,
            'x_0': 0,
            'y_0': 0,
            'units': 'm',
            'no_defs': True,
            'type': 'crs',
        },
        width=5500,
        height=5500,
        area_extent=(-5500000, -5500000, 5500000, 5500000),
        resample_method='native',
    ),
    'plate_carree_global': ProjectionConfig(
        name='Plate Carree Global',
        proj_type=ProjectionType.PLATE_CARREE,
        description='1-degree global grid (WGS84) - ideal for 3D globe rendering',
        proj_dict={
            'proj': 'longlat',
            'datum': 'WGS84',
            'no_defs': True,
            'type': 'crs',
        },
        width=3600,
        height=1800,
        area_extent=(-180, -90, 180, 90),
        resample_method='bilinear',
    ),
    'plate_carree_china': ProjectionConfig(
        name='Plate Carree China',
        proj_type=ProjectionType.PLATE_CARREE,
        description='China region at 0.05 degree resolution',
        proj_dict={
            'proj': 'longlat',
            'datum': 'WGS84',
            'no_defs': True,
            'type': 'crs',
        },
        width=1240,
        height=700,
        area_extent=(70, 15, 142, 55),
        resample_method='bilinear',
    ),
}


# =============================================================================
# Projection Factory
# =============================================================================

class ProjectionFactory:
    """
    Factory for creating projection configurations and AreaDefinitions.

    Supports predefined projections and dynamic creation of custom projections.
    """

    _registry: Dict[str, ProjectionConfig] = PREDEFINED_PROJECTIONS.copy()

    # Cache for AreaDefinition objects to avoid recreating the same objects
    _area_cache: Dict[str, Any] = {}

    # Thread safety for concurrent read/write access from QThread workers
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the AreaDefinition cache."""
        with cls._lock:
            cls._area_cache.clear()

    @classmethod
    def register(cls, name: str, config: ProjectionConfig) -> None:
        """Register a new projection."""
        with cls._lock:
            cls._registry[name] = config

    @classmethod
    def unregister(cls, name: str) -> None:
        """Remove a projection from registry."""
        with cls._lock:
            cls._registry.pop(name, None)

    @classmethod
    def get_config(cls, name: str) -> Optional[ProjectionConfig]:
        """Get projection configuration by name."""
        return cls._registry.get(name)

    @classmethod
    def get_available(cls) -> List[str]:
        """Get list of available projection names."""
        return list(cls._registry.keys())

    @classmethod
    def create_target_area(cls, proj_name: str,
                          custom_width: Optional[int] = None,
                          custom_height: Optional[int] = None,
                          source_area=None) -> Optional[Any]:
        """
        Create a Pyresample AreaDefinition for the target projection.

        Uses caching for predefined projections to avoid recreating the same objects.

        Args:
            proj_name: Projection identifier
            custom_width: Override width if needed
            custom_height: Override height if needed
            source_area: Source area for extent calculation (used for adaptive extent)

        Returns:
            AreaDefinition or None if not applicable
        """
        config = cls.get_config(proj_name)
        if config is None:
            raise ValueError(f"Unknown projection: {proj_name}. "
                            f"Available: {cls.get_available()}")

        # Native geostationary view: return None so drivers keep source geometry.
        if config.proj_type == ProjectionType.GEOSTATIONARY:
            return None

        geometry = _get_geometry()

        # Determine dimensions
        width = custom_width or config.width
        height = custom_height or config.height

        # Determine area_extent
        area_extent = config.area_extent

        # Check cache for predefined projections (no source_area)
        if source_area is None:
            cache_key = f"{proj_name}_{width}_{height}"
            with cls._lock:
                if cache_key in cls._area_cache:
                    return cls._area_cache[cache_key]

        # For plate_carree_global, use satellite's actual geographic extent
        # instead of full global extent (-180, -90, 180, 90)
        if proj_name == 'plate_carree_global' and source_area is not None:
            if os.environ.get('SATIMG_DEBUG'):
                logger.debug("[Projections] Creating plate_carree_global with satellite actual extent")
            actual_extent = cls._get_satellite_actual_extent(source_area)
            if actual_extent is not None:
                west, east, south, north = actual_extent
                # Calculate resolution
                lon_res = (east - west) / width
                lat_res = (north - south) / height
                area_extent = (west, south, east, north)
                # Keep caller-specified output_size; otherwise use adaptive default.
                if custom_width is None:
                    width = max(1, int((east - west) / 0.1))
                if custom_height is None:
                    height = max(1, int((north - south) / 0.1))
                if os.environ.get('SATIMG_DEBUG'):
                    logger.debug(f"[Projections] Adaptive extent: {area_extent}, resolution: {lon_res}x{lat_res} deg")
                    logger.debug(f"[Projections] Adaptive size: {width}x{height}")

        try:
            area_def = geometry.AreaDefinition(
                area_id=proj_name,
                description=config.name,
                proj_id=proj_name,
                projection=config.proj_dict,
                width=width,
                height=height,
                area_extent=area_extent,
            )

            # Cache predefined projections (no source_area means standard config)
            if source_area is None:
                cache_key = f"{proj_name}_{width}_{height}"
                with cls._lock:
                    cls._area_cache[cache_key] = area_def

            return area_def
        except Exception as e:
            logger.exception(f"[Projections] AreaDefinition creation failed: {e}")
            raise

    @classmethod
    def _get_satellite_actual_extent(cls, source_area) -> Optional[Tuple[float, float, float, float]]:
        """
        Extract actual geographic extent from source area.

        Args:
            source_area: Pyresample AreaDefinition with satellite data

        Returns:
            Tuple (west, east, south, north) in degrees, or None
        """
        try:
            extent = _extract_valid_lonlat_extent(source_area, max_points=200_000)
            if extent is not None:
                return extent

            # Fallback for already-geographic areas when lon/lat sampling is unavailable.
            proj_dict = getattr(source_area, 'proj_dict', {})
            if proj_dict.get('proj') in ('longlat', 'latlong', 'eqc'):
                ae = getattr(source_area, 'area_extent', None)
                if ae and len(ae) == 4:
                    west, south, east, north = map(float, ae)
                    west = max(-180.0, min(180.0, west))
                    east = max(-180.0, min(180.0, east))
                    south = max(-90.0, min(90.0, south))
                    north = max(-90.0, min(90.0, north))
                    if east >= west and north >= south:
                        return (west, east, south, north)

        except Exception as e:
            logger.debug(f"[Projections] Could not extract actual extent: {e}")

        return None

    @classmethod
    def create_custom(cls,
                     name: str,
                     proj_type: ProjectionType,
                     center_lon: float,
                     center_lat: float,
                     width: int = 1000,
                     height: int = 1000,
                     resolution: float = 0.01,
                     **kwargs) -> ProjectionConfig:
        """
        Create a custom projection configuration.

        Args:
            name: Unique identifier for the projection
            proj_type: Type of projection
            center_lon: Center longitude
            center_lat: Center latitude
            width: Output width in pixels
            height: Output height in pixels
            resolution: Resolution in degrees (for geographic) or meters (for projected)
            **kwargs: Additional projection parameters

        Returns:
            ProjectionConfig instance
        """
        if proj_type == ProjectionType.PLATE_CARREE:
            proj_dict = {
                'proj': 'longlat',
                'datum': 'WGS84',
                'no_defs': True,
            }
            area_extent = (
                center_lon - (width * resolution) / 2,
                center_lat - (height * resolution) / 2,
                center_lon + (width * resolution) / 2,
                center_lat + (height * resolution) / 2,
            )

        elif proj_type == ProjectionType.LAMBERT_CONFORMAL:
            # Lambert Conformal Conic for regional projections
            std_parallels = kwargs.get('standard_parallels', (30, 60))
            proj_dict = {
                'proj': 'lcc',
                'lon_0': center_lon,
                'lat_0': center_lat,
                'lat_1': std_parallels[0],
                'lat_2': std_parallels[1],
                'no_defs': True,
            }
            area_extent = kwargs.get('area_extent', (0, 0, width, height))

        elif proj_type == ProjectionType.POLAR_STEREOGRAPHIC:
            # Polar stereographic for polar regions
            proj_dict = {
                'proj': 'stere',
                'lon_0': center_lon,
                'lat_0': 90 if center_lat > 0 else -90,
                'lat_ts': center_lat,
                'no_defs': True,
            }
            area_extent = kwargs.get('area_extent', (0, 0, width, height))

        else:
            raise ValueError(f"Unsupported projection type: {proj_type}")

        config = ProjectionConfig(
            name=name,
            proj_type=proj_type,
            description=f"Custom {proj_type.value} centered at ({center_lon}, {center_lat})",
            proj_dict=proj_dict,
            width=width,
            height=height,
            area_extent=area_extent,
            resample_method='bilinear',
        )

        cls.register(name, config)
        return config

    @classmethod
    def create_from_extent(cls,
                          name: str,
                          west: float,
                          east: float,
                          south: float,
                          north: float,
                          resolution: float = 0.01,
                          proj_type: ProjectionType = ProjectionType.PLATE_CARREE) -> ProjectionConfig:
        """
        Create projection from geographic extent.

        Args:
            name: Projection name
            west: Western longitude
            east: Eastern longitude
            south: Southern latitude
            north: Northern latitude
            resolution: Resolution in degrees
            proj_type: Projection type

        Returns:
            ProjectionConfig
        """
        width = int((east - west) / resolution)
        height = int((north - south) / resolution)

        center_lon = (west + east) / 2
        center_lat = (south + north) / 2

        return cls.create_custom(
            name=name,
            proj_type=proj_type,
            center_lon=center_lon,
            center_lat=center_lat,
            width=width,
            height=height,
            resolution=resolution,
            area_extent=(west, south, east, north),
        )

    @classmethod
    def create_for_region(cls,
                         name: str,
                         region: str,
                         resolution: float = 0.05,
                         proj_type: ProjectionType = ProjectionType.PLATE_CARREE) -> Optional[ProjectionConfig]:
        """
        Create projection for a predefined region.

        Args:
            name: Projection name
            region: Region identifier
            resolution: Resolution in degrees
            proj_type: Projection type

        Returns:
            ProjectionConfig or None if region not found
        """
        regions = {
            'china': (70, 142, 15, 55),
            'east_asia': (70, 150, 0, 60),
            'southeast_asia': (90, 140, -10, 25),
            'global': (-180, 180, -90, 90),
        }

        if region not in regions:
            return None

        west, east, south, north = regions[region]
        return cls.create_from_extent(
            name=name,
            west=west, east=east, south=south, north=north,
            resolution=resolution,
            proj_type=proj_type,
        )


# =============================================================================
# Geographic Extent Utilities
# =============================================================================

def get_geographic_extent(area_def) -> Optional[Tuple[float, float, float, float]]:
    """
    Extract geographic extent (W, E, S, N) from an AreaDefinition.

    Args:
        area_def: Pyresample AreaDefinition

    Returns:
        Tuple of (west, east, south, north) in degrees, or None
    """
    if _DEBUG:
        logger.debug(f"[GeoUtils] get_geographic_extent called with {type(area_def)}")

    # Fast path: longlat/plate_carree AreaDefinition.
    try:
        if hasattr(area_def, 'proj_dict'):
            proj_dict = area_def.proj_dict
            if _DEBUG:
                logger.debug(f"[GeoUtils] proj_dict: {proj_dict}")

            if proj_dict.get('proj') in ('longlat', 'latlong', 'eqc'):
                ae = getattr(area_def, 'area_extent', None)
                if ae and len(ae) == 4:
                    west = max(-180.0, min(180.0, float(ae[0])))
                    south = max(-90.0, min(90.0, float(ae[1])))
                    east = max(-180.0, min(180.0, float(ae[2])))
                    north = max(-90.0, min(90.0, float(ae[3])))
                    if east >= west and north >= south:
                        return (west, east, south, north)
    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] proj_dict inference failed: {e}")

    # Primary dynamic path for geostationary/native projections:
    # derive bounds from valid lon/lat pixels sampled from source area.
    try:
        extent = _extract_valid_lonlat_extent(area_def, max_points=200_000)
        if extent is not None:
            return extent
    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] get_lonlats failed: {e}")

    return None


def create_extent_array_for_imshow(area_def) -> Optional[Tuple[float, float, float, float]]:
    """
    Create extent array for matplotlib imshow().

    Args:
        area_def: Pyresample AreaDefinition

    Returns:
        Tuple (west, east, south, north) for imshow extent
    """
    extent = get_geographic_extent(area_def)
    if extent:
        west, east, south, north = extent
        return (west, east, south, north)
    return None


# =============================================================================
# Legacy Compatibility Functions
# =============================================================================

def get_projection_config(proj_name: str) -> Dict:
    """Get projection configuration (legacy wrapper)."""
    config = ProjectionFactory.get_config(proj_name)
    if config:
        return config.to_dict()
    raise ValueError(f"Unknown projection: {proj_name}")


def create_target_area(
    proj_name: str,
    source_area=None,
    custom_width: Optional[int] = None,
    custom_height: Optional[int] = None,
) -> Optional[Any]:
    """Create target area (legacy wrapper)."""
    return ProjectionFactory.create_target_area(
        proj_name,
        custom_width=custom_width,
        custom_height=custom_height,
        source_area=source_area,
    )


def get_available_projections() -> List[Tuple[str, str, str]]:
    """Get list of available projections."""
    return [
        (name, config.name, config.description)
        for name, config in ProjectionFactory._registry.items()
    ]


def extract_geographic_extent(area_def) -> Optional[Tuple[float, float, float, float]]:
    """Extract geographic extent (legacy wrapper)."""
    return get_geographic_extent(area_def)


# =============================================================================
# Swath Handling Utilities
# =============================================================================

def get_swath_extent(lons: np.ndarray, lats: np.ndarray,
                     resolution: float = 0.01) -> Optional[Tuple[float, float, float, float]]:
    """
    Calculate geographic extent from swath coordinates.

    Args:
        lons: Longitude array
        lats: Latitude array
        resolution: Resolution in degrees for sampling (default 0.01 deg)

    Returns:
        Tuple of (west, east, south, north) in degrees, or None
    """
    if lons is None or lats is None:
        return None

    try:
        # Handle different array shapes
        if lons.ndim == 1 and lats.ndim == 1:
            # 1D coordinate arrays - create meshgrid
            lon_grid, lat_grid = np.meshgrid(lons, lats)
        elif lons.ndim == 2 and lats.ndim == 2:
            lon_grid, lat_grid = lons, lats
        else:
            logger.warning(f"[GeoUtils] Unexpected array shapes: lons={lons.shape}, lats={lats.shape}")
            return None

        # Get valid coordinates
        valid_mask = np.isfinite(lon_grid) & np.isfinite(lat_grid)
        if not np.any(valid_mask):
            return None

        lons_valid = lon_grid[valid_mask]
        lats_valid = lat_grid[valid_mask]

        # Sample if arrays are too large
        total_points = len(lons_valid)
        if total_points > 1000000:
            # Sample 1M points max for performance
            step = total_points // 1000000
            lons_valid = lons_valid[::step]
            lats_valid = lats_valid[::step]

        west = float(np.nanmin(lons_valid))
        east = float(np.nanmax(lons_valid))
        south = float(np.nanmin(lats_valid))
        north = float(np.nanmax(lats_valid))

        # Validate
        if (-180 <= west <= 180 and -180 <= east <= 180 and
            -90 <= south <= 90 and -90 <= north <= 90):
            return (west, east, south, north)

    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] get_swath_extent failed: {e}")

    return None


def create_from_swath(lons: np.ndarray, lats: np.ndarray,
                      proj_name: str = 'plate_carree_global',
                      resolution: Optional[float] = None) -> Optional[Any]:
    """
    Create a target AreaDefinition from swath coordinates.

    Args:
        lons: Longitude array from swath
        lats: Latitude array from swath
        proj_name: Target projection name
        resolution: Output resolution in degrees (auto if None)

    Returns:
        AreaDefinition or None
    """
    if lons is None or lats is None:
        return None

    # Get extent from swath
    extent = get_swath_extent(lons, lats)
    if extent is None:
        return None

    west, east, south, north = extent

    # Calculate resolution
    if resolution is None:
        # Estimate from swath dimensions
        lon_span = east - west
        lat_span = north - south
        if lons.ndim == 2:
            lon_res = lon_span / lons.shape[1]
            lat_res = lat_span / lons.shape[0]
        else:
            lon_res = lat_res = 0.01  # Default
        resolution = min(lon_res, lat_res)

    # Calculate dimensions
    width = max(1, int((east - west) / resolution))
    height = max(1, int((north - south) / resolution))

    # Use projection factory to create target area
    target_area = ProjectionFactory.create_from_extent(
        name=f'swath_{proj_name}',
        west=west, east=east, south=south, north=north,
        resolution=resolution,
        proj_type=ProjectionFactory.get_config(proj_name).proj_type if ProjectionFactory.get_config(proj_name) else ProjectionType.PLATE_CARREE,
    )

    if _DEBUG:
        logger.debug(f"[GeoUtils] Created target area from swath: {width}x{height}, extent={extent}")

    return target_area


def is_swath_definition(area) -> bool:
    """
    Check if an area object is a SwathDefinition.

    Args:
        area: Pyresample geometry object

    Returns:
        True if it's a SwathDefinition
    """
    if area is None:
        return False

    area_type = type(area).__name__
    return 'Swath' in area_type


def create_swath_definition(lons: np.ndarray, lats: np.ndarray):
    """
    Create a SwathDefinition from coordinate arrays.

    Args:
        lons: Longitude array
        lats: Latitude array

    Returns:
        SwathDefinition or None
    """
    try:
        geometry = _get_geometry()
        return geometry.SwathDefinition(lons=lons, lats=lats)
    except Exception as e:
        if _DEBUG:
            logger.debug(f"[GeoUtils] Failed to create SwathDefinition: {e}")
        return None
