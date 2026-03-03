"""
Geometry Package

Coordinate transformation and projection utilities.
"""
from .projections import (
    ProjectionType,
    ProjectionConfig,
    ProjectionFactory,
    PREDEFINED_PROJECTIONS,
    get_geographic_extent,
    create_extent_array_for_imshow,
    get_projection_config,
    create_target_area,
    get_available_projections,
    extract_geographic_extent,
    create_from_swath,
    get_swath_extent,
)

__all__ = [
    'ProjectionType',
    'ProjectionConfig',
    'ProjectionFactory',
    'PREDEFINED_PROJECTIONS',
    'get_geographic_extent',
    'create_extent_array_for_imshow',
    'get_projection_config',
    'create_target_area',
    'get_available_projections',
    'extract_geographic_extent',
    'create_from_swath',
    'get_swath_extent',
]
