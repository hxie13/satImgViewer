"""
Smart File Type Recognizer

Directly maps filename patterns to specific satpy readers,
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
    
    @property
    def is_valid(self) -> bool:
        """Check if recognition was successful."""
        return self.confidence > 0.5 and self.reader != "auto"


class FilePatternRule(NamedTuple):
    """Pattern rule for file recognition."""
    pattern: str
    satellite: SatelliteType
    product_level: ProductLevel
    reader: str
    confidence: float


# =============================================================================
# Filename Pattern Database
# Format: (regex_pattern, satellite, product_level, reader, confidence)
# =============================================================================

FILE_PATTERNS: List[FilePatternRule] = [
    # FY-4B AGRI L1 - Full Disk
    (r'FY4B.*AGRI.*L1.*FDI.*\d{14}.*\.HDF', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.95),
    (r'FY-4B.*AGRI.*L1.*FDI.*\d{14}.*\.HDF', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.95),
    # FY-4B AGRI L1 - China region
    (r'FY4B.*AGRI.*L1.*CNR.*\d{14}.*\.HDF', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.95),
    # FY-4B AGRI L2 products
    (r'FY4B.*AGRI.*L2.*CLM.*\.HDF', SatelliteType.FY4B, ProductLevel.L2, 'satpy_cf_nc', 0.90),
    (r'FY4B.*AGRI.*L2.*FOG.*\.HDF', SatelliteType.FY4B, ProductLevel.L2, 'satpy_cf_nc', 0.90),
    (r'FY4B.*AGRI.*L2.*CWP.*\.HDF', SatelliteType.FY4B, ProductLevel.L2, 'satpy_cf_nc', 0.90),
    (r'FY4B.*AGRI.*L2.*CTT.*\.HDF', SatelliteType.FY4B, ProductLevel.L2, 'satpy_cf_nc', 0.90),
    (r'FY4B.*AGRI.*L2.*CTP.*\.HDF', SatelliteType.FY4B, ProductLevel.L2, 'satpy_cf_nc', 0.90),
    
    # FY-4A AGRI L1
    (r'FY4A.*AGRI.*L1.*FDI.*\d{14}.*\.HDF', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.95),
    (r'FY-4A.*AGRI.*L1.*FDI.*\d{14}.*\.HDF', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.95),
    (r'FY4A.*AGRI.*L1.*CNR.*\d{14}.*\.HDF', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.95),
    
    # FY-3D MERSI L1
    (r'FY3D.*MERSI.*L1.*\d{8}.*\d{4}.*\.HDF', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.95),
    (r'FY-3D.*MERSI.*L1.*\d{8}.*\d{4}.*\.HDF', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.95),
    
    # Himawari-8 HSD
    (r'HS_H08_\d{8}_\d{4}.*\.DAT', SatelliteType.H08, ProductLevel.L1, 'ahi_hsd', 0.95),
    (r'HS_H08_\d{8}_\d{4}.*\.DAT\.bz2', SatelliteType.H08, ProductLevel.L1, 'ahi_hsd', 0.95),
    # Himawari-9 HSD
    (r'HS_H09_\d{8}_\d{4}.*\.DAT', SatelliteType.H09, ProductLevel.L1, 'ahi_hsd', 0.95),
    (r'HS_H09_\d{8}_\d{4}.*\.DAT\.bz2', SatelliteType.H09, ProductLevel.L1, 'ahi_hsd', 0.95),
    # Himawari NetCDF
    (r'H08.*\d{8}_\d{4}.*\.nc', SatelliteType.H08, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
    (r'H09.*\d{8}_\d{4}.*\.nc', SatelliteType.H09, ProductLevel.L1, 'ahi_l1b_gridded', 0.90),
]

# Fallback patterns (lower confidence, generic readers)
FALLBACK_PATTERNS: List[FilePatternRule] = [
    (r'FY4B', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.70),
    (r'FY-4B', SatelliteType.FY4B, ProductLevel.L1, 'agri_fy4b', 0.70),
    (r'FY4A', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.70),
    (r'FY-4A', SatelliteType.FY4A, ProductLevel.L1, 'agri_fy4a', 0.70),
    (r'FY3D', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.70),
    (r'FY-3D', SatelliteType.FY3D, ProductLevel.L1, 'mersi2_l1b', 0.70),
    (r'H08', SatelliteType.H08, ProductLevel.L1, 'ahi_hsd', 0.70),
    (r'H09', SatelliteType.H09, ProductLevel.L1, 'ahi_hsd', 0.70),
    (r'HIMAWARI', SatelliteType.H08, ProductLevel.L1, 'ahi_hsd', 0.60),
]


class FileTypeRecognizer:
    """
    Intelligent file type recognizer that maps filenames directly to readers.
    
    This eliminates the trial-and-error reader fallback chain by using
    precise filename pattern matching.
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
                    resolution=self._extract_resolution(filename)
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
                    resolution=self._extract_resolution(filename)
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
            confidence=0.0
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
        
        # Count reader occurrences (exclude auto)
        reader_counts = {}
        for r in results:
            if r.reader != "auto":
                reader_counts[r.reader] = reader_counts.get(r.reader, 0) + 1
        
        if not reader_counts:
            return None
        
        # Return most common
        return max(reader_counts, key=reader_counts.get)
    
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
