"""Pytest configuration and shared fixtures."""
import pytest
from unittest.mock import Mock, MagicMock
import numpy as np


@pytest.fixture
def mock_satellite_manager():
    """Create a mock SatelliteImageManager for UI testing."""
    manager = Mock()
    manager.is_loaded = False
    manager.time_groups = []
    manager.current_driver_type = None
    return manager


@pytest.fixture
def sample_image_array():
    """Create a sample image array for testing."""
    return np.random.rand(100, 100, 3).astype(np.float32)


@pytest.fixture
def mock_area_definition():
    """Create a mock pyresample AreaDefinition."""
    area_def = Mock()
    area_def.area_extent = (-180, -90, 180, 90)
    area_def.proj_dict = {'proj': 'longlat'}
    area_def.width = 3600
    area_def.height = 1800
    return area_def
