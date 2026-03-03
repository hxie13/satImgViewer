"""
Core Package

Satellite image processing core modules.
"""
from .manager import SatelliteImageManager, ProcessingResult
from .drivers import DriverFactory, BaseSatelliteDriver, BasePolarDriver
from .drivers.base import ProcessingParams, SatelliteFileInfo, BandInfo, SatelliteType
from .geometry import ProjectionFactory, ProjectionType, get_geographic_extent
from .config import (get_band_config, get_satellite_config, map_canonical_to_satellite,
                     PROJECTION_GRID_SHAPES, PROJECTION_GRID_EXTENTS,
                     SATELLITE_BAND_MAPS, THERMAL_BAND_SETS,
                     get_satellite_band_map, get_thermal_bands)
from .pipeline import ImageProcessingPipeline, PipelineConfig
from .app_state import AppState
from .exceptions import (
    SatImgError,
    SatDataLoadError, UnsupportedFormatError, ReaderDetectionError,
    ProjectionError, InvalidExtentError, ResamplingError,
    CalibrationError, MissingCoefficientsError,
    ExportError, UnsupportedExportFormatError,
    PipelineError, BandNotFoundError,
)

# Legacy exports for backward compatibility
from .satpy_driver import SatpyDriver
from .interfaces import ISatelliteDataProvider
from .image_proc import ImageProcessor, normalize_percentile, apply_gamma

__all__ = [
    # Manager
    'SatelliteImageManager',
    'ProcessingResult',
    # Drivers
    'DriverFactory',
    'BaseSatelliteDriver',
    'BasePolarDriver',
    'ProcessingParams',
    'SatelliteFileInfo',
    'BandInfo',
    'SatelliteType',
    # Geometry
    'ProjectionFactory',
    'ProjectionType',
    'get_geographic_extent',
    # Config
    'get_band_config',
    'get_satellite_config',
    'map_canonical_to_satellite',
    'PROJECTION_GRID_SHAPES',
    'PROJECTION_GRID_EXTENTS',
    'SATELLITE_BAND_MAPS',
    'THERMAL_BAND_SETS',
    'get_satellite_band_map',
    'get_thermal_bands',
    # Pipeline
    'ImageProcessingPipeline',
    'PipelineConfig',
    # App state
    'AppState',
    # Exceptions
    'SatImgError',
    'SatDataLoadError',
    'UnsupportedFormatError',
    'ReaderDetectionError',
    'ProjectionError',
    'InvalidExtentError',
    'ResamplingError',
    'CalibrationError',
    'MissingCoefficientsError',
    'ExportError',
    'UnsupportedExportFormatError',
    'PipelineError',
    'BandNotFoundError',
    # Legacy
    'SatpyDriver',
    'ISatelliteDataProvider',
    'ImageProcessor',
    'normalize_percentile',
    'apply_gamma',
]
