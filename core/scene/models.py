"""
Unified scene and spatial grid models.

These models decouple ingest-time scene normalization from the driver loading
pipeline. They represent "what a scene is" before any heavy pixel data is read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.geometry.projections import PREDEFINED_PROJECTIONS


class FileRole(str, Enum):
    """Role of a source file inside a normalized scene."""

    PRIMARY = "primary"
    AUXILIARY = "auxiliary"


class GeometryType(str, Enum):
    """Native geometry type of a scene."""

    GEOSTATIONARY_GRID = "geostationary_grid"
    LATLON_GRID = "latlon_grid"
    SWATH = "swath"
    UNKNOWN = "unknown"


class MeasurementType(str, Enum):
    """Measurement type for a normalized dataset entry."""

    REFLECTANCE = "reflectance"
    BRIGHTNESS_TEMPERATURE = "brightness_temperature"
    MASK = "mask"
    PRODUCT = "product"
    UNKNOWN = "unknown"


@dataclass
class AnalysisGridDefinition:
    """Common target grid reference shared by normalized scenes."""

    grid_id: str
    projection_id: str
    description: str
    width: int
    height: int
    extent: Tuple[float, float, float, float]  # west, east, south, north
    resample_method: str = "bilinear"


@dataclass
class SourceFileRecord:
    """Standardized metadata for a single discovered input file."""

    path: str
    file_name: str
    size_bytes: Optional[int] = None
    satellite_family: Optional[str] = None
    satellite_platform: Optional[str] = None
    sensor: Optional[str] = None
    product_level: Optional[str] = None
    product_code: Optional[str] = None
    nominal_time: Optional[str] = None
    file_format: Optional[str] = None
    driver_type: Optional[str] = None
    reader_hint: Optional[str] = None
    confidence: float = 0.0
    role: FileRole = FileRole.PRIMARY
    auxiliary_role: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetDescriptor:
    """Normalized dataset/band metadata without carrying pixel arrays."""

    dataset_id: str
    canonical_name: str
    native_name: str
    display_name: str
    measurement_type: MeasurementType
    resolution: Optional[str] = None
    wavelength: Optional[str] = None
    is_thermal: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeometryDescriptor:
    """Normalized description of a scene's native geometry."""

    geometry_type: GeometryType
    projection_id: str
    width: Optional[int] = None
    height: Optional[int] = None
    area_extent: Optional[Tuple[float, float, float, float]] = None
    extent_units: Optional[str] = None
    has_geolocation: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedScene:
    """
    Unified analysis object for downstream loading, visualization, and fusion.

    This is intentionally metadata-first: it describes the scene and its
    baseline grid target before any heavy raster data is processed.
    """

    scene_id: str
    driver_type: Optional[str]
    reader_type: Optional[str]
    satellite_family: Optional[str]
    satellite_platform: Optional[str]
    sensor: Optional[str]
    product_level: Optional[str]
    product_code: Optional[str]
    nominal_time: Optional[str]
    files: List[SourceFileRecord]
    datasets: List[DatasetDescriptor]
    native_geometry: GeometryDescriptor
    analysis_grid: AnalysisGridDefinition
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def file_paths(self) -> List[str]:
        """Return file paths with primary files ordered before auxiliary files."""
        ordered = sorted(
            self.files,
            key=lambda item: (item.role != FileRole.PRIMARY, item.file_name.lower()),
        )
        return [record.path for record in ordered]

    @property
    def primary_files(self) -> List[SourceFileRecord]:
        """Return all primary files in the scene."""
        return [record for record in self.files if record.role == FileRole.PRIMARY]

    @property
    def auxiliary_files(self) -> List[SourceFileRecord]:
        """Return all auxiliary files in the scene."""
        return [record for record in self.files if record.role == FileRole.AUXILIARY]


@dataclass
class SceneCollection:
    """Batch result from directory/file ingest and normalization."""

    root_path: Optional[str]
    discovered_files: List[SourceFileRecord]
    scenes: List[NormalizedScene]
    warnings: List[str] = field(default_factory=list)
    unmatched_files: List[SourceFileRecord] = field(default_factory=list)


def get_analysis_grid_definition(grid_id: str = "plate_carree_global") -> AnalysisGridDefinition:
    """Build a shared target grid definition from existing projection presets."""
    projection = PREDEFINED_PROJECTIONS[grid_id]
    west, south, east, north = projection.area_extent
    return AnalysisGridDefinition(
        grid_id=grid_id,
        projection_id=grid_id,
        description=projection.description,
        width=projection.width,
        height=projection.height,
        extent=(west, east, south, north),
        resample_method=projection.resample_method,
    )
