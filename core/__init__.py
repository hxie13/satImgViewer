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
from .app_state import AppState
from .product_requests import ProductRecipe, RenderRequest, StillExportRequest, VideoExportRequest
from .exceptions import (
    SatImgError,
    SatDataLoadError, UnsupportedFormatError, ReaderDetectionError,
    ProjectionError, InvalidExtentError, ResamplingError,
    CalibrationError, MissingCoefficientsError,
    ExportError, UnsupportedExportFormatError,
    PipelineError, BandNotFoundError,
)

from .image_proc import ImageProcessor, normalize_percentile, apply_gamma
from .ingest import IngestScanner, SceneIngestService, SceneRecognizer
from .scene import (
    AnalysisGridDefinition,
    DatasetDescriptor,
    FileRole,
    GeometryDescriptor,
    GeometryType,
    MeasurementType,
    NormalizedScene,
    SceneCollection,
    SourceFileRecord,
    get_analysis_grid_definition,
)

try:
    from .pipeline import ImageProcessingPipeline, PipelineConfig
except ModuleNotFoundError:  # Optional heavy dependencies (e.g. dask) may be absent in light environments.
    ImageProcessingPipeline = None
    PipelineConfig = None

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
    # App state
    'AppState',
    'ProductRecipe',
    'RenderRequest',
    'StillExportRequest',
    'VideoExportRequest',
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
    # Image processing
    'ImageProcessor',
    'normalize_percentile',
    'apply_gamma',
    # Ingest / Scene
    'IngestScanner',
    'SceneIngestService',
    'SceneRecognizer',
    'AnalysisGridDefinition',
    'DatasetDescriptor',
    'FileRole',
    'GeometryDescriptor',
    'GeometryType',
    'MeasurementType',
    'NormalizedScene',
    'SceneCollection',
    'SourceFileRecord',
    'get_analysis_grid_definition',
]

if ImageProcessingPipeline is not None:
    __all__.extend([
        'ImageProcessingPipeline',
        'PipelineConfig',
    ])
