"""
Driver Factory Module

Provides factory for creating satellite drivers based on file detection.
Centralized driver management for extensibility.
"""
import re
import threading
from typing import Dict, List, Optional, Type
import logging

from .base import BaseSatelliteDriver, SatelliteFileInfo
from .polar_base import BasePolarDriver
from .fengyun import FengYunDriver
from .fengyun3d import FengYun3DDriver
from .himawari import HimawariDriver
from ..file_recognizer import get_recommended_format

logger = logging.getLogger(__name__)


class DriverFactory:
    """
    Factory for creating appropriate satellite drivers based on file analysis.
    Supports lazy loading and driver caching.
    """

    # Registry of available drivers
    _registry: Dict[str, Type[BaseSatelliteDriver]] = {
        'fengyun': FengYunDriver,
        'fengyun3d': FengYun3DDriver,
        'himawari': HimawariDriver,
    }

    # Thread safety for concurrent registration from plugins or tests
    _lock: threading.RLock = threading.RLock()

    # File patterns for quick identification
    _patterns = {
        'fengyun': [
            r'FY4[AB]', r'FY-4[AB]', r'AGRI', r'L2', r'\d{8}_\d{4}_F'
        ],
        'fengyun3d': [
            r'FY3D', r'MERSI', r'FY-3D', r'_MERSI_',
        ],
        'himawari': [
            r'HIMAWARI', r'H08', r'H09', r'AHI', r'HSD', r'_S0\d{4}_'
        ],
    }

    @classmethod
    def register(cls, name: str, driver_class: Type[BaseSatelliteDriver]) -> None:
        """
        Register a new driver class.

        Args:
            name: Unique identifier for the driver
            driver_class: Driver class inheriting from BaseSatelliteDriver
        """
        if not issubclass(driver_class, BaseSatelliteDriver):
            raise TypeError(f"{driver_class} must inherit from BaseSatelliteDriver")
        with cls._lock:
            cls._registry[name] = driver_class
        logger.info(f"Registered driver: {name} -> {driver_class.__name__}")

    @classmethod
    def unregister(cls, name: str) -> None:
        """Remove a driver from the registry."""
        with cls._lock:
            cls._registry.pop(name, None)

    @classmethod
    def get_registry(cls) -> Dict[str, Type[BaseSatelliteDriver]]:
        """Get copy of current driver registry."""
        with cls._lock:
            return cls._registry.copy()

    @classmethod
    def identify_files(cls, file_paths: List[str]) -> List[SatelliteFileInfo]:
        """
        Analyze file list and identify satellite types.

        Args:
            file_paths: List of file paths to analyze

        Returns:
            List of SatelliteFileInfo objects with identification results
        """
        results = []

        for file_path in file_paths:
            info = SatelliteFileInfo(file_path=file_path)

            # Check each driver type
            for driver_name, patterns in cls._patterns.items():
                for pattern in patterns:
                    if re.search(pattern, file_path, re.IGNORECASE):
                        info.driver_type = driver_name
                        info.confidence = min(info.confidence + 0.3, 1.0)
                        break

            # Try to extract timestamp
            timestamp_match = cls._extract_timestamp(file_path)
            if timestamp_match:
                info.timestamp = timestamp_match

            # Detect product level
            info.product_level = cls._detect_product_level(file_path)

            results.append(info)

        return results

    @classmethod
    def _extract_timestamp(cls, file_path: str) -> Optional[str]:
        """Extract timestamp from filename."""
        filename = cls._get_basename(file_path)

        # Himawari HSD pattern: HS_H08_20230101_0300_B01_R10_S0101.DAT
        hsd_match = re.search(r'(\d{8}_\d{4})', filename)
        if hsd_match:
            return hsd_match.group(1)

        # Generic pattern: YYYYMMDD_HHMM or YYYYMMDDHHMMSS
        generic_match = re.search(r'(\d{8}[_-]?\d{4,6})', filename)
        if generic_match:
            return generic_match.group(1)

        return None

    @staticmethod
    def _detect_product_level(file_path: str) -> str:
        """Detect product level from filename."""
        filename = file_path.upper()

        if 'L2' in filename or '_L2_' in filename:
            return 'L2'
        elif 'L1' in filename or '_L1_' in filename:
            return 'L1'
        elif 'AGRI' in filename:
            return 'L1'  # AGRI is typically L1 data
        elif 'GEO' in filename or 'ATMOSPHERE' in filename:
            return 'L2'  # Geolocation/Atmosphere products
        else:
            return 'UNKNOWN'

    @staticmethod
    def _get_basename(file_path: str) -> str:
        """Get basename without extension."""
        import os
        return os.path.basename(file_path)

    @classmethod
    def create_driver(cls, driver_type: str, **kwargs) -> BaseSatelliteDriver:
        """
        Create a driver instance for the specified satellite type.

        Args:
            driver_type: Type identifier ('fengyun' or 'himawari')
            **kwargs: Additional arguments passed to driver constructor

        Returns:
            Instance of appropriate satellite driver

        Raises:
            ValueError: If driver type is not registered
        """
        if driver_type not in cls._registry:
            available = list(cls._registry.keys())
            raise ValueError(
                f"Unknown driver type: {driver_type}. "
                f"Available types: {available}"
            )

        driver_class = cls._registry[driver_type]
        logger.info(f"Creating driver: {driver_type} -> {driver_class.__name__}")

        return driver_class(**kwargs)

    @classmethod
    def create_from_files(
        cls,
        file_paths: List[str],
        auto_detect: bool = True,
        preferred_format: Optional[str] = None,
    ) -> BaseSatelliteDriver:
        """
        Create appropriate driver by analyzing files.

        Args:
            file_paths: List of file paths
            auto_detect: If True, automatically identify satellite type
            preferred_format: Optional direct format identifier from FileTypeRecognizer

        Returns:
            Configured driver instance

        Raises:
            ValueError: Cannot determine satellite type
        """
        if not file_paths:
            raise ValueError("No file paths provided")

        fmt = preferred_format

        if fmt and fmt != "auto":
            # Use smart file recognizer result
            logger.info(f"Using FileTypeRecognizer recommendation: {fmt}")
            
            # Determine driver type from reader name
            driver_type = cls._reader_to_driver_type(fmt)
            if driver_type is None:
                driver_type = cls._infer_driver_type_from_generic_reader(file_paths, fmt)
            if driver_type:
                return cls.create_driver(driver_type)
        
        if auto_detect:
            file_info_list = cls.identify_files(file_paths)

            # Group by driver type and find dominant type
            type_counts: Dict[str, int] = {}
            for info in file_info_list:
                if info.driver_type:
                    type_counts[info.driver_type] = type_counts.get(info.driver_type, 0) + 1

            if not type_counts:
                raise ValueError(
                    "Cannot determine satellite type from files. "
                    "Please specify driver_type explicitly."
                )

            # Use most common type
            driver_type = max(type_counts, key=type_counts.get)
            logger.info(f"Auto-detected satellite type: {driver_type} "
                        f"(found {type_counts[driver_type]} files)")

            return cls.create_driver(driver_type)
        else:
            # Use first file's detected type
            file_info = cls.identify_files([file_paths[0]])[0]
            if not file_info.driver_type:
                raise ValueError("Cannot determine satellite type")
            return cls.create_driver(file_info.driver_type)
    
    @classmethod
    def _reader_to_driver_type(cls, reader_name: str) -> Optional[str]:
        """
        Map format identifier to driver type.

        Args:
            reader_name: Format identifier returned by FileTypeRecognizer
                         (e.g., 'fy4_agri_l1', 'himawari_l1b_nc').

        Returns:
            Driver type key or None if not directly mapped
        """
        reader_map = {
            # Native direct-I/O identifiers.
            'fy4_agri_l1': 'fengyun',
            'fy4_l2_nc': 'fengyun',
            'fy3d_mersi_l1': 'fengyun3d',
            'himawari_l1b_nc': 'himawari',
        }
        return reader_map.get(reader_name)

    @classmethod
    def _infer_driver_type_from_generic_reader(cls, file_paths: List[str], reader_name: str) -> Optional[str]:
        """
        Infer driver type from filename patterns when reader_name is not in the direct map.

        Args:
            file_paths: Input data file list
            reader_name: Format identifier that was not directly mapped

        Returns:
            Driver type key or None
        """
        if not file_paths:
            return None

        joined = " ".join(file_paths).upper()
        if any(token in joined for token in ('FY4', 'FY-4', 'FY_4', 'AGRI')):
            return 'fengyun'
        if any(token in joined for token in ('H08', 'H09', 'HIMAWARI', 'AHI')):
            return 'himawari'
        if any(token in joined for token in ('FY3', 'FY-3', 'MERSI')):
            return 'fengyun3d'
        return None
    
    @classmethod
    def create_with_smart_recognition(cls, file_paths: List[str]) -> BaseSatelliteDriver:
        """
        Create driver using smart file type recognition.
        
        This method uses FileTypeRecognizer to directly map filenames to readers,
        eliminating the trial-and-error fallback chain.
        
        Args:
            file_paths: List of file paths
            
        Returns:
            Configured driver instance with preferred reader hint
        """
        if not file_paths:
            raise ValueError("No file paths provided")
        
        # Use smart recognizer
        recommended_format = get_recommended_format(file_paths)
        
        if recommended_format:
            logger.info(f"[SmartRecognition] Direct format match: {recommended_format}")
            return cls.create_from_files(file_paths, preferred_format=recommended_format)
        else:
            logger.warning("[SmartRecognition] No direct match, falling back to auto-detection")
            return cls.create_from_files(file_paths, auto_detect=True)

    @classmethod
    def get_available_drivers(cls) -> List[str]:
        """Get list of available driver type names."""
        return list(cls._registry.keys())

    @classmethod
    def get_driver_info(cls, driver_type: str) -> Optional[Dict]:
        """Get information about a specific driver type."""
        if driver_type not in cls._registry:
            return None

        driver_class = cls._registry[driver_type]
        return {
            'name': driver_type,
            'class': driver_class.__name__,
            'module': driver_class.__module__,
            'patterns': cls._patterns.get(driver_type, []),
        }
