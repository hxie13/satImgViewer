"""
Base Satellite Driver Abstract Class

Defines the interface for all satellite drivers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum
import numpy as np
import logging

logger = logging.getLogger(__name__)


class SatelliteType(Enum):
    """Enumeration of supported satellite types."""
    FENGYUN_3D = "FY3D"
    FENGYUN_4A = "FY4A"
    FENGYUN_4B = "FY4B"
    HIMAWARI_8 = "H08"
    HIMAWARI_9 = "H09"
    UNKNOWN = "UNKNOWN"


class ProductLevel(Enum):
    """Enumeration of product levels."""
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    UNKNOWN = "UNKNOWN"


@dataclass
class SatelliteFileInfo:
    """Information about a satellite data file."""
    file_path: str
    driver_type: Optional[str] = None
    satellite_type: Optional[SatelliteType] = None
    product_level: Optional[ProductLevel] = ProductLevel.UNKNOWN
    timestamp: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """Check if file identification was successful."""
        return self.driver_type is not None and self.confidence > 0.5


@dataclass
class BandInfo:
    """Standardized band information."""
    canonical_name: str      # Standard name (e.g., 'VIS006')
    display_name: str        # Human-readable (e.g., 'Visible Blue (0.47 μm)')
    wavelength: Optional[str] = None  # Wavelength string
    resolution: Optional[str] = None   # Spatial resolution
    bit_depth: int = 16        # Data bit depth
    is_thermal: bool = False    # Thermal infrared band

    @property
    def is_visible(self) -> bool:
        """Check if band is in visible spectrum."""
        return self.wavelength is not None and 'μm' in self.wavelength


@dataclass
class ProcessingParams:
    """Parameters for image processing pipeline."""
    bands: List[str]                    # Target band canonical names
    gamma: float = 1.0                   # Gamma correction
    output_size: Optional[Tuple[int, int]] = None  # (width, height)
    output_proj: str = "geostationary_native"
    calibration: bool = False            # Apply radiometric calibration
    region: str = "global"               # Target region
    resample_method: str = "nearest"     # Resampling method
    quality_profile: str = "default"     # default | preview_fast | export_high

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'bands': self.bands,
            'gamma': self.gamma,
            'output_size': self.output_size,
            'output_proj': self.output_proj,
            'calibration': self.calibration,
            'region': self.region,
            'resample_method': self.resample_method,
            'quality_profile': self.quality_profile,
        }


class BaseSatelliteDriver(ABC):
    """
    Abstract base class for satellite data drivers.

    All satellite drivers must implement these methods to ensure
    consistent interface across different satellite types.
    """

    # Class-level configuration
    SATELLITE_TYPE: SatelliteType = SatelliteType.UNKNOWN
    SUPPORTED_FORMATS: List[str] = []

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize driver with optional configuration.

        Args:
            config: Optional driver configuration dictionary
        """
        self.config = config or {}
        self._scene = None
        self._dataset_map: Dict[str, str] = {}
        self._band_catalog: Dict[str, BandInfo] = {}
        self._is_loaded = False

        # Setup logging
        self._setup_logging()

        # Initialize driver-specific components
        self._init_driver()

    def _setup_logging(self) -> None:
        """Configure logging for this driver."""
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    @staticmethod
    def _configure_dependency_logging() -> None:
        """
        Configure noisy third-party loggers to keep app output clean.
        """
        suppress_loggers = ['pyresample']
        for name in suppress_loggers:
            lg = logging.getLogger(name)
            lg.setLevel(logging.ERROR)
            lg.propagate = False
            lg.handlers = []
            lg.addHandler(logging.NullHandler())

    def _init_driver(self) -> None:
        """Initialize driver-specific resources. Override in subclasses."""
        pass

    @abstractmethod
    def identify(self, file_path: str) -> bool:
        """
        Check if this driver can handle the given file.

        Args:
            file_path: Path to satellite data file

        Returns:
            True if file is compatible with this driver
        """
        pass

    @abstractmethod
    def get_band_mapping(self) -> Dict[str, str]:
        """
        Get mapping from canonical names to satellite-specific names.

        Returns:
            Dict mapping {canonical_name: satellite_specific_name}
        """
        pass

    @abstractmethod
    def get_available_bands(self) -> List[BandInfo]:
        """
        Get list of available bands with standardized information.

        Returns:
            List of BandInfo objects
        """
        pass

    @abstractmethod
    def load(self, file_paths: List[str]) -> bool:
        """
        Load satellite data from file paths.

        Args:
            file_paths: List of paths to satellite data files

        Returns:
            True if loading successful
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """
        Release loaded resources and clear cache.
        """
        pass

    @abstractmethod
    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image data according to processing parameters.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array, area_definition)
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get standardized metadata for loaded scene.

        Returns:
            Dictionary containing metadata
        """
        pass

    @abstractmethod
    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """
        Get geographic coverage (west, east, south, north) in degrees.

        Returns:
            Tuple of (west, east, south, north) or None if unknown
        """
        pass

    @property
    def is_loaded(self) -> bool:
        """Check if data is currently loaded."""
        return self._is_loaded

    @property
    def scene(self):
        """Get underlying scene-like object if a concrete driver exposes one."""
        return self._scene

    @property
    def dataset_map(self) -> Dict[str, str]:
        """Get canonical to satellite-specific name mapping."""
        return self._dataset_map.copy()

    def _map_band_name(self, canonical_name: str) -> str:
        """
        Map canonical band name to satellite-specific name.

        Args:
            canonical_name: Standard band name

        Returns:
            Satellite-specific band name or original if not found
        """
        mapping = self.get_band_mapping()
        return mapping.get(canonical_name, canonical_name)

    def _map_band_names_reverse(self, satellite_name: str) -> str:
        """
        Map satellite-specific name to canonical name.

        Args:
            satellite_name: Satellite-specific band name

        Returns:
            Canonical band name or original if not found
        """
        mapping = self.get_band_mapping()
        for canonical, specific in mapping.items():
            if specific == satellite_name:
                return canonical
        return satellite_name

    def get_band_info(self, canonical_name: str) -> Optional[BandInfo]:
        """
        Get detailed information for a specific band.

        Args:
            canonical_name: Standard band name

        Returns:
            BandInfo object or None if not found
        """
        return self._band_catalog.get(canonical_name)

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """
        Group file paths by timestamp for time-series processing.

        Extracts timestamps from filenames using common satellite naming conventions.

        Args:
            file_paths: List of file paths

        Returns:
            List of file groups, each group represents one time point
            e.g., [[f1_t0.nc, f2_t0.nc], [f1_t1.nc], ...]
        """
        import re
        import os

        groups = {}

        for path in sorted(file_paths):
            basename = os.path.basename(path)

            # Try multiple timestamp patterns
            timestamp = None

            # Pattern 1: Himawari HSD - YYYYMMDD_HHMM (e.g., 20230101_0300)
            match = re.search(r'(\d{8}_\d{4})', basename)
            if match:
                timestamp = match.group(1)
            else:
                # Pattern 2: Generic - YYYYMMDDHHMM or YYYYMMDD_HHMMSS
                match = re.search(r'(\d{8}[_-]?\d{6})', basename)
                if match:
                    timestamp = match.group(1)
                else:
                    # Pattern 3: FY4A/FY4A standard format
                    match = re.search(r'(\d{12,14})', basename)
                    if match:
                        timestamp = match.group(1)

            # Use timestamp as key, or basename if no pattern found
            key = timestamp if timestamp else basename

            if key not in groups:
                groups[key] = []
            groups[key].append(path)

        # Sort by timestamp key and return as list of groups
        sorted_keys = sorted(groups.keys())
        return [groups[k] for k in sorted_keys]

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure resources are released."""
        self.unload()
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(satellite={self.SATELLITE_TYPE.value})"
