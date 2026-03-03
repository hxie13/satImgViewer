# DEPRECATED — ISatelliteDataProvider
# This interface is superseded by core.drivers.base.BaseSatelliteDriver.
# Retained only for backward compatibility with legacy code that still imports it.
from abc import ABC, abstractmethod
import numpy as np

class ISatelliteDataProvider(ABC):
    """
    DEPRECATED: Legacy satellite data provider interface.

    New drivers should inherit from ``core.drivers.base.BaseSatelliteDriver``
    instead of this class.

    Satellite data provider interface.
    Both Himawari (HSD) and Fengyun (HDF/NC) must implement these methods.
    """
    
    @abstractmethod
    def load_scene(self, file_paths: list):
        """Load file list, build index, do not read specific data."""
        pass

    @abstractmethod
    def get_available_datasets(self) -> list:
        """Return available band/product list (e.g. ['B01', 'B13', 'T05'])."""
        pass

    @abstractmethod
    def get_metadata(self) -> dict:
        """Return common metadata (time, satellite name, resolution)."""
        pass

    @abstractmethod
    def request_image(self, bands: list, size=(1000, 1000)) -> tuple:
        """
        Request image data.
        Args:
            bands: Band list ['B01'] or ['B03', 'B02', 'B01']
            size: Resampling size for preview, optimize performance
        Returns:
            (image_data: np.ndarray, crs: object, extent: tuple)
            image_data must be physically calibrated (Ref/BT) and normalized
        """
        pass
