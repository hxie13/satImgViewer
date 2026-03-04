"""
Smart File Type Recognizer

Directly maps filename patterns to format identifiers used by the driver factory,
eliminating the need for trial-and-error fallback chain.
"""
import re
from typing import Dict, List, Optional, NamedTuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SatelliteType(Enum):
    """Supported satellite types."""
    FY4A = "FY4A"
    FY4B = "FY4B"
    FY3D = "FY3D"
    H08 = "H08"
    H09 = "H09"
    UNKNOWN = "UNKNOWN"


class ProductLevel(Enum):
    """Product level enumeration."""
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    UNKNOWN = "UNKNOWN"


@dataclass
class FileRecognitionResult:
    """Result of file type recognition."""
    file_path: str
    satellite_type: SatelliteType
    product_level: ProductLevel
    reader: str  # Direct reader recommendation
    confidence: float  # 0.0 - 1.0
    timestamp: Optional[str] = None
    resolution: Optional[str] = None  # e.g., "4000M", "1000M"
    sensor: Optional[str] = None
    product: Optional[str] = None
    region: Optional[str] = None
    file_format: Optional[str] = None
    
    @property
    def is_valid(self) -> bool:
        """Check if recognition was successful."""
        return self.confidence > 0.5 and self.reader != "auto"


@dataclass(frozen=True)
class FilePatternRule:
    """Pattern rule for file recognition."""
    pattern: str
    satellite: SatelliteType
    product_level: ProductLevel
    reader: str
    confidence: float


# =============================================================================
# Filename Pattern Database
# Format: FilePatternRule(regex_pattern, satellite, product_level, reader, confidence)
# =============================================================================

FILE_PATTERNS: List[FilePatternRule] = [
    # FY-4B AGRI L1 (historical naming variants)
    FilePatternRule(r'FY[-_]?4B.*AGRI.*L1.*(FDI|DISK|FDK|CNR).*\.((HDF5?)|(NC))$', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.97),
    FilePatternRule(r'FY[-_]?4B.*AGRI.*L1.*\d{14}.*\.((HDF5?)|(NC))$', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.95),
    # FY-4B AGRI L2 products (mostly CF-like)
    FilePatternRule(r'FY[-_]?4B.*AGRI.*L2.*(CLM|FOG|CWP|CTT|CTP|ACHA|ACSF|SST|LST).*\.(HDF5?|NC)$', SatelliteType.FY4B, ProductLevel.L2, 'generic_nc', 0.93),

    # FY-4A AGRI L1
    FilePatternRule(r'FY[-_]?4A.*AGRI.*L1.*(FDI|DISK|FDK|CNR).*\.((HDF5?)|(NC))$', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.97),
    FilePatternRule(r'FY[-_]?4A.*AGRI.*L1.*\d{14}.*\.((HDF5?)|(NC))$', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.95),

    # FY-3D MERSI L1
    FilePatternRule(r'FY[-_]?3D.*MERSI.*L1.*\d{8}[_-]?\d{4}.*\.(HDF5?|H5)$', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.96),

    # Himawari NetCDF formats (various naming conventions)
    # Note: HSD binary (.dat/.bz2) format is not supported
    # Standard gridded format: H08_20230101_0300_xxx.nc
    FilePatternRule(r'H08_\d{8}_\d{4}.*\.nc', SatelliteType.H08, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
    FilePatternRule(r'H09_\d{8}_\d{4}.*\.nc', SatelliteType.H09, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
    # Alternative format: AHI_H08_20230101_0300.nc
    FilePatternRule(r'AHI_H08_\d{8}_\d{4}.*\.nc', SatelliteType.H08, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
    FilePatternRule(r'AHI_H09_\d{8}_\d{4}.*\.nc', SatelliteType.H09, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
    # Himawari L2 NetCDF products
    FilePatternRule(r'H08.*L2.*\.nc', SatelliteType.H08, ProductLevel.L2, 'generic_nc', 0.85),
    FilePatternRule(r'H09.*L2.*\.nc', SatelliteType.H09, ProductLevel.L2, 'generic_nc', 0.85),
    FilePatternRule(r'AHI.*L2.*\.nc', SatelliteType.H08, ProductLevel.L2, 'generic_nc', 0.85),
]

# Fallback patterns (lower confidence, generic readers)
FALLBACK_PATTERNS: List[FilePatternRule] = [
    FilePatternRule(r'FY4B', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.70),
    FilePatternRule(r'FY-4B', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.70),
    FilePatternRule(r'FY_4B', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.70),
    FilePatternRule(r'FY4A', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.70),
    FilePatternRule(r'FY-4A', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.70),
    FilePatternRule(r'FY_4A', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.70),
    FilePatternRule(r'FY3D', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.70),
    FilePatternRule(r'FY-3D', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.70),
    FilePatternRule(r'FY_3D', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.70),
    FilePatternRule(r'H08', SatelliteType.H08, ProductLevel.L1, 'ahi_l1b_gridded', 0.70),
    FilePatternRule(r'H09', SatelliteType.H09, ProductLevel.L1, 'ahi_l1b_gridded', 0.70),
    FilePatternRule(r'HIMAWARI', SatelliteType.H08, ProductLevel.L1, 'ahi_l1b_gridded', 0.60),
    # Fallback for NetCDF files
    FilePatternRule(r'\.nc$', SatelliteType.UNKNOWN, ProductLevel.L1, 'ahi_l1b_gridded', 0.50),
]


class FileTypeRecognizer:
    """
    Intelligent file type recognizer that maps filenames directly to format identifiers.

    Uses precise filename pattern matching to identify satellite data format,
    allowing the driver factory to select the correct driver without guessing.
    """
    
    def __init__(self):
        self._compile_patterns()
        self._cache: Dict[str, FileRecognitionResult] = {}
    
    def _compile_patterns(self):
        """Compile regex patterns for performance."""
        self._compiled_patterns = [
            (re.compile(rule.pattern, re.IGNORECASE), rule)
            for rule in FILE_PATTERNS
        ]
        self._compiled_fallbacks = [
            (re.compile(rule.pattern, re.IGNORECASE), rule)
            for rule in FALLBACK_PATTERNS
        ]
    
    def recognize(self, file_path: str, use_cache: bool = True) -> FileRecognitionResult:
        """
        Recognize file type and return direct reader recommendation.
        
        Args:
            file_path: Path to the file
            use_cache: Whether to use caching
            
        Returns:
            FileRecognitionResult with reader recommendation
        """
        # Check cache
        if use_cache and file_path in self._cache:
            return self._cache[file_path]
        
        filename = file_path.split('/')[-1].split('\\')[-1]
        
        # Try high-confidence patterns first
        for pattern, rule in self._compiled_patterns:
            if pattern.search(filename):
                result = FileRecognitionResult(
                    file_path=file_path,
                    satellite_type=rule.satellite,
                    product_level=rule.product_level,
                    reader=rule.reader,
                    confidence=rule.confidence,
                    timestamp=self._extract_timestamp(filename),
                    resolution=self._extract_resolution(filename),
                    sensor=self._extract_sensor(filename),
                    product=self._extract_product(filename),
                    region=self._extract_region(filename),
                    file_format=self._extract_file_format(filename),
                )
                if use_cache:
                    self._cache[file_path] = result
                return result
        
        # Try fallback patterns
        for pattern, rule in self._compiled_fallbacks:
            if pattern.search(filename):
                result = FileRecognitionResult(
                    file_path=file_path,
                    satellite_type=rule.satellite,
                    product_level=rule.product_level,
                    reader=rule.reader,
                    confidence=rule.confidence,
                    timestamp=self._extract_timestamp(filename),
                    resolution=self._extract_resolution(filename),
                    sensor=self._extract_sensor(filename),
                    product=self._extract_product(filename),
                    region=self._extract_region(filename),
                    file_format=self._extract_file_format(filename),
                )
                if use_cache:
                    self._cache[file_path] = result
                return result
        
        # No match found - return auto-detection
        result = FileRecognitionResult(
            file_path=file_path,
            satellite_type=SatelliteType.UNKNOWN,
            product_level=ProductLevel.UNKNOWN,
            reader="auto",  # Fallback to auto-detection
            confidence=0.0,
            timestamp=self._extract_timestamp(filename),
            resolution=self._extract_resolution(filename),
            sensor=self._extract_sensor(filename),
            product=self._extract_product(filename),
            region=self._extract_region(filename),
            file_format=self._extract_file_format(filename),
        )
        if use_cache:
            self._cache[file_path] = result
        return result
    
    def recognize_batch(self, file_paths: List[str]) -> List[FileRecognitionResult]:
        """
        Recognize multiple files and return consensus recommendation.
        
        Args:
            file_paths: List of file paths
            
        Returns:
            List of recognition results
        """
        results = [self.recognize(fp) for fp in file_paths]
        
        # Log summary
        readers = {}
        for r in results:
            readers[r.reader] = readers.get(r.reader, 0) + 1
        
        if len(readers) == 1:
            reader = list(readers.keys())[0]
            logger.info(f"[Recognizer] All {len(results)} files match reader: {reader}")
        else:
            logger.info(f"[Recognizer] Mixed readers detected: {readers}")
        
        return results
    
    def get_consensus_reader(self, file_paths: List[str]) -> Optional[str]:
        """
        Get the most common reader recommendation for a batch of files.
        
        Args:
            file_paths: List of file paths
            
        Returns:
            Most common reader, or None if no consensus
        """
        results = self.recognize_batch(file_paths)
        
        # Weighted score by confidence, with count as tie-breaker.
        reader_scores: Dict[str, float] = {}
        reader_counts: Dict[str, int] = {}
        for r in results:
            if r.reader != "auto" and r.confidence > 0.0:
                reader_scores[r.reader] = reader_scores.get(r.reader, 0.0) + r.confidence
                reader_counts[r.reader] = reader_counts.get(r.reader, 0) + 1

        if not reader_scores:
            return None

        # Return highest weighted score, then highest count.
        ranked = sorted(
            reader_scores.keys(),
            key=lambda k: (reader_scores[k], reader_counts.get(k, 0)),
            reverse=True
        )
        return ranked[0]
    
    @staticmethod
    def _extract_timestamp(filename: str) -> Optional[str]:
        """Extract timestamp from filename."""
        # FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20250721034500_...
        match = re.search(r'(\d{14})', filename)  # YYYYMMDDHHMMSS
        if match:
            return match.group(1)
        
        # Himawari: HS_H08_20230101_0300_B01...
        match = re.search(r'(\d{8}_\d{4})', filename)
        if match:
            return match.group(1)
        
        # FY3D: FY3D_MERSI_20230101_0300...
        match = re.search(r'(\d{8})[_-]?(\d{4})', filename)
        if match:
            return f"{match.group(1)}_{match.group(2)}"
        
        return None
    
    @staticmethod
    def _extract_resolution(filename: str) -> Optional[str]:
        """Extract resolution from filename."""
        # Look for patterns like 4000M, 1000M, etc.
        match = re.search(r'(\d{3,4}M)', filename.upper())
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_sensor(filename: str) -> Optional[str]:
        """Extract sensor name from filename."""
        name = filename.upper()
        for sensor in ("AGRI", "MERSI", "AHI"):
            if sensor in name:
                return sensor
        if "H08" in name or "H09" in name or "HIMAWARI" in name:
            return "AHI"
        return None

    @staticmethod
    def _extract_product(filename: str) -> Optional[str]:
        """Extract product code from filename."""
        name = filename.upper()
        # Prioritize specific L2 product identifiers before generic region tokens.
        high_priority = ("CLM", "FOG", "CWP", "CTT", "CTP", "ACHA", "ACSF", "SST", "LST")
        for token in high_priority:
            if re.search(rf'(^|[_-]){token}([_-]|$)', name):
                return token
        fallback_tokens = ("FDI", "CNR", "DISK")
        for token in fallback_tokens:
            if token in name:
                return token
        return None

    @staticmethod
    def _extract_region(filename: str) -> Optional[str]:
        """Extract rough coverage region from filename markers."""
        name = filename.upper()
        if "GBAL" in name:
            return "GLOBAL"
        if "DISK" in name or "FDI" in name or "FDK" in name:
            return "FULL_DISK"
        if "CNR" in name:
            return "CHINA"
        return None

    @staticmethod
    def _extract_file_format(filename: str) -> Optional[str]:
        """Extract file format by filename suffix."""
        name = filename.upper()
        if name.endswith(".DAT.BZ2"):
            return "DAT.BZ2"
        if name.endswith(".HDF5"):
            return "HDF5"
        if name.endswith(".HDF"):
            return "HDF"
        if name.endswith(".H5"):
            return "H5"
        if name.endswith(".NC"):
            return "NC"
        if name.endswith(".DAT"):
            return "DAT"
        return None
    
    def clear_cache(self):
        """Clear the recognition cache."""
        self._cache.clear()


# Global recognizer instance
_recognizer = FileTypeRecognizer()


def recognize_file(file_path: str) -> FileRecognitionResult:
    """Convenience function to recognize a single file."""
    return _recognizer.recognize(file_path)


def recognize_files(file_paths: List[str]) -> List[FileRecognitionResult]:
    """Convenience function to recognize multiple files."""
    return _recognizer.recognize_batch(file_paths)


def get_recommended_reader(file_paths: List[str]) -> Optional[str]:
    """Get the recommended reader for a list of files."""
    return _recognizer.get_consensus_reader(file_paths)
