"""
FY3D MERSI Satellite Driver

Implementation for Fengyun-3D (FY3D) satellite MERSI L1 data support.
Supports MERSI-2 (Medium Resolution Spectral Imager) data in HDF5 format.

Filename pattern: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_1000M_MS.HDF
GEO file pattern: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_GEO1K_MS.HDF
"""
import os
import re
import glob
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

import numpy as np

from .base import (
    BaseSatelliteDriver,
    SatelliteType,
    ProductLevel,
    BandInfo,
    ProcessingParams,
)
from .polar_base import BasePolarDriver

from core.config import get_satellite_band_map, get_thermal_bands  # noqa: E402

logger = logging.getLogger(__name__)


# =============================================================================
# Band Mapping Configuration  (sourced from core.config — single source of truth)
# =============================================================================

MERSI_L1_BANDS: Dict[str, Dict[str, Any]] = get_satellite_band_map('MERSI_L1')
THERMAL_BANDS: set = get_thermal_bands('MERSI_L1')

# FY3D satellite coverage (global coverage with sun-synchronous orbit)
SATELLITE_COVERAGE = {
    SatelliteType.FENGYUN_3D: (-180, 180, -90, 90),  # Global
}


class FengYun3DDriver(BasePolarDriver):
    """
    Driver for Fengyun-3D (FY3D) satellite MERSI sensor.

    Supports:
    - FY3D MERSI-2 L1 data in HDF5 format
    - 20 spectral bands (4 at 250m, 15 at 1000m, 1 at 4000m)
    - Global coverage (sun-synchronous satellite)
    - Swath-to-grid resampling via pyresample
    """

    SATELLITE_TYPE: SatelliteType = SatelliteType.FENGYUN_3D
    SUPPORTED_FORMATS = ['.hdf', '.h5', '.nc', '.HDF', '.H5']

    def __init__(self, config: Optional[Dict] = None):
        """Initialize FY3D MERSI driver."""
        super().__init__(config)
        self._satpy = None
        self._current_level = ProductLevel.L1
        self._dataset_names: List[str] = []
        self._loaded_reader: Optional[str] = None   # cache for dataset-map reuse
        self._geo_file_path: Optional[str] = None
        self._primary_file_path: Optional[str] = None
        self._swath_lons: Optional[np.ndarray] = None
        self._swath_lats: Optional[np.ndarray] = None
        self._is_swath: bool = False

    def _init_driver(self) -> None:
        """Initialize driver-specific resources."""
        pass

    def identify(self, file_path: str) -> bool:
        """
        Check if file is compatible with FY3D MERSI driver.

        Args:
            file_path: Path to satellite data file

        Returns:
            True if file is FY3D MERSI data
        """
        filename = os.path.basename(file_path).upper()

        # Primary pattern: FY3D_MERSI_GBAL_L1
        if 'FY3D' in filename and 'MERSI' in filename:
            return True

        # Fallback: Check for HDF5 files with MERSI in name
        if 'MERSI' in filename:
            return True

        return False

    def get_band_mapping(self) -> Dict[str, str]:
        """
        Get mapping from canonical names to satellite-specific dataset names.

        Returns:
            Dict mapping {canonical_name: satellite_specific_name}
        """
        return {canonical: info['name'] for canonical, info in MERSI_L1_BANDS.items()}

    def get_available_bands(self) -> List[BandInfo]:
        """
        Get list of available bands with standardized information.

        Returns:
            List of BandInfo objects for all configured bands
        """
        bands = []
        for canonical, info in MERSI_L1_BANDS.items():
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=f"{canonical} ({info['wavelength']} - {info['type']})",
                wavelength=info['wavelength'],
                resolution=info['resolution'],
                is_thermal=canonical in THERMAL_BANDS
            )
            bands.append(band_info)
        return bands

    def load(self, file_paths: List[str]) -> bool:
        """
        Load FY3D MERSI satellite data from file paths.

        Args:
            file_paths: List of paths to HDF5 data files

        Returns:
            True if loading successful
        """
        if not file_paths:
            logger.error("No file paths provided")
            return False

        try:
            # Configure logging BEFORE importing satpy
            if self._satpy is None:
                self._configure_satpy_logging()
                import satpy as _satpy_module
                self._satpy = _satpy_module

            # Filter out physically broken HDF/H5 files (e.g., truncated EOF).
            valid_file_paths = self._filter_readable_input_files(file_paths)
            if not valid_file_paths:
                logger.error("[FY3D] No readable files left after validation")
                return False

            # Detect reader for FY3D MERSI data
            reader_name = self._detect_reader(valid_file_paths)
            logger.info(f"Detected reader: {reader_name}")

            # Determine primary file
            primary_file = self._select_primary_file(valid_file_paths)
            if primary_file is None:
                logger.error("No valid FY3D MERSI files found")
                return False

            # Save primary file path for later geolocation lookups
            self._primary_file_path = primary_file

            logger.info(f"Loading primary file: {os.path.basename(primary_file)}")

            # Build the filenames list: include all provided files plus any GEO file found
            scene_filenames = list(valid_file_paths)
            geo_file = self._find_geo_file(primary_file)
            if geo_file and geo_file not in scene_filenames:
                scene_filenames.append(geo_file)
                logger.info(f"[FY3D] Including GEO file in scene: {os.path.basename(geo_file)}")
            elif not geo_file:
                logger.warning("[FY3D] GEO file not found in directory — geolocation may be unavailable")

            # Try to create scene with detected reader
            scene = None
            used_reader = None

            # Try FY3D MERSI specific readers in order
            reader_candidates = self._get_reader_candidates()

            for reader in reader_candidates:
                try:
                    logger.info(f"Trying reader: {reader}")
                    scene = self._satpy.Scene(
                        reader=reader,
                        filenames=scene_filenames
                    )

                    # Check if we got data
                    available = scene.available_dataset_names()
                    if available:
                        used_reader = reader
                        logger.info(f"Success with reader: {reader}, found {len(available)} datasets")
                        break
                except Exception as e:
                    logger.warning(f"Reader {reader} failed: {e}")
                    continue

            if scene is None or not scene.available_dataset_names():
                # Last resort: try auto-detection
                logger.info("Trying auto-detection...")
                try:
                    scene = self._satpy.Scene(filenames=scene_filenames)
                    used_reader = 'auto'
                except Exception as e:
                    logger.error(f"Auto-detection failed: {e}")
                    return False

            self._scene = scene
            self._dataset_names = scene.available_dataset_names()

            # Build dataset map only when reader changes — band structure is
            # identical across all frames of the same satellite/reader.
            if used_reader != self._loaded_reader:
                self._build_dataset_map()
                self._loaded_reader = used_reader

            self._is_loaded = True
            logger.info(f"Successfully loaded FY3D MERSI data with reader: {used_reader}")
            logger.info(f"[FY3D] Total available datasets: {len(self._dataset_names)}")
            logger.info(f"[FY3D] All datasets: {self._dataset_names}")

            return True

        except Exception as e:
            logger.error(f"Failed to load FY3D MERSI files: {e}")
            import traceback
            traceback.print_exc()
            self._is_loaded = False
            return False

    def _filter_readable_input_files(self, file_paths: List[str]) -> List[str]:
        """
        Remove physically unreadable HDF/H5 files before SatPy scene creation.

        This avoids one truncated file blocking the whole frame load.
        """
        valid: List[str] = []
        invalid: List[str] = []
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext not in {'.hdf', '.h5'}:
                valid.append(path)
                continue
            try:
                import h5py  # local import keeps optional dependency behavior
                with h5py.File(path, 'r'):
                    pass
                valid.append(path)
            except Exception as exc:
                invalid.append(path)
                logger.warning(f"[FY3D] Skip unreadable file: {os.path.basename(path)} ({exc})")

        if invalid:
            logger.warning(
                f"[FY3D] Filtered {len(invalid)} unreadable file(s); "
                f"{len(valid)} file(s) remain for loading"
            )
        return valid

    def _detect_reader(self, file_paths: List[str]) -> str:
        """
        Detect appropriate SatPy reader for files.

        Args:
            file_paths: List of file paths

        Returns:
            Reader name string
        """
        for path in file_paths:
            filename = os.path.basename(path).upper()

            # Check for specific reader patterns
            if 'MERSI' in filename and 'L1' in filename:
                if self._check_reader_available('mersi2_l1b'):
                    return 'mersi2_l1b'
                if self._check_reader_available('mersi_l1b'):
                    return 'mersi_l1b'

        # Default to MERSI-2 L1B if available
        if self._check_reader_available('mersi2_l1b'):
            return 'mersi2_l1b'
        if self._check_reader_available('mersi_l1b'):
            return 'mersi_l1b'

        return 'generic_image'

    def _check_reader_available(self, reader_name: str) -> bool:
        """
        Check if a satpy reader is available.

        Args:
            reader_name: Name of the reader to check

        Returns:
            True if reader is available
        """
        try:
            if self._satpy is None:
                self._configure_satpy_logging()
                import satpy as _satpy_module
                self._satpy = _satpy_module

            available_readers = self._satpy.available_readers()
            return reader_name in available_readers
        except Exception:
            return False

    def _get_reader_candidates(self) -> List[str]:
        """
        Get list of reader candidates in order of preference.

        Returns:
            List of reader names to try
        """
        candidates = []

        # Check for FY3D MERSI specific readers
        if self._check_reader_available('mersi2_l1b'):
            candidates.append('mersi2_l1b')
        if self._check_reader_available('mersi_l1b'):
            candidates.append('mersi_l1b')

        # Add generic readers as fallbacks
        candidates.extend([
            'generic_image',
            'hdfeos_l1b',
            'hdfeos_l2',
        ])

        return candidates

    def _select_primary_file(self, file_paths: List[str]) -> Optional[str]:
        """
        Select the primary file from a list.

        Prefers:
        1. HDF5 files with 'MERSI' in name
        2. First valid file

        Args:
            file_paths: List of file paths

        Returns:
            Path to primary file or None
        """
        for path in file_paths:
            filename = os.path.basename(path).upper()
            ext = os.path.splitext(filename)[1].upper()

            # Prefer HDF5 files with MERSI
            if ext in ['.HDF', '.H5'] and 'MERSI' in filename:
                return path

        # Fallback: return first file with valid extension
        for path in file_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.hdf', '.h5', '.nc']:
                return path

        return file_paths[0] if file_paths else None

    def _build_dataset_map(self) -> None:
        """
        Build mapping from canonical names to dataset names.

        Populates _dataset_map and _band_catalog based on available data.
        """
        if self._scene is None:
            return

        self._dataset_map = {}
        self._band_catalog = {}

        available = self._scene.available_dataset_names()
        logger.info(f"[FY3D] Available datasets from SatPy: {available}")

        # Create mapping from available datasets
        for dataset in available:
            # Try to extract band number from dataset name
            canonical = self._canonical_from_dataset(dataset, available)
            self._dataset_map[canonical] = dataset

            # Also create reverse mapping for direct lookup
            if dataset not in self._dataset_map.values():
                self._dataset_map[dataset] = dataset

            # Build band catalog entry
            band_info = BandInfo(
                canonical_name=canonical,
                display_name=dataset,
                wavelength=None,
                resolution=None
            )
            self._band_catalog[canonical] = band_info

        logger.info(f"[FY3D] Dataset map: {self._dataset_map}")

    def _canonical_from_dataset(self, dataset_name: str, available: List[str]) -> str:
        """
        Convert dataset name to canonical name.

        Handles various dataset naming patterns from SatPy readers.

        Args:
            dataset_name: Satpy dataset name
            available: List of available dataset names

        Returns:
            Canonical band name (e.g., 'B01') or original name
        """
        import re
        orig_name = dataset_name
        dataset_name_upper = dataset_name.upper()

        logger.debug(f"[FY3D] Converting dataset to canonical: {dataset_name}")

        # --- Fast path: Satpy mersi2_l1b returns pure integer strings '1'~'25' ---
        _stripped = dataset_name.strip()
        if re.match(r'^\d{1,2}$', _stripped):
            num = int(_stripped)
            if 1 <= num <= 25:
                canonical = f'B{num:02d}'
                logger.debug(f"[FY3D] Integer string fast path: {orig_name} -> {canonical}")
                return canonical

        # Comprehensive patterns for FY3D MERSI naming conventions
        # Note: EV_1000_Emissive01~06 map to B20~B25 (offset +19)
        patterns = [
            # Standard FY3D MERSI naming patterns
            # EV_250_RefSB01 -> B01
            (r'EV_250[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'EV_250M[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'250M[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            # EV_1000_RefSB05 -> B05
            (r'EV_1000[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'EV_1000M[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'1000M[_-]RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            # EV_1000_Emissive01 -> B20 (Emissive01=B20 ... Emissive06=B25, offset +19)
            (r'EV_1000[_-]Emissive(\d{2})', lambda m: f'B{int(m.group(1))+19:02d}'),
            (r'EV_1000M[_-]Emissive(\d{2})', lambda m: f'B{int(m.group(1))+19:02d}'),
            (r'1000M[_-]Emissive(\d{2})', lambda m: f'B{int(m.group(1))+19:02d}'),
            # Direct RefSB pattern: RefSB01 -> B01
            (r'RefSB(\d{2})', lambda m: f'B{m.group(1)}'),
            # Direct Emissive pattern: Emissive01 -> B20
            (r'Emissive(\d{2})', lambda m: f'B{int(m.group(1))+19:02d}'),
            # Suffix number: _B01 or _01 -> B01
            (r'_B?(\d{2})$', lambda m: f'B{m.group(1)}'),
            # Prefix number: B01_... or 01_... -> B01
            (r'^B?(\d{2})[_-]', lambda m: f'B{m.group(1)}'),
            # Standalone number in name -> B{num}
            (r'\b(\d{2})\b', lambda m: f'B{m.group(1)}'),
            # Common SatPy naming patterns
            (r'band(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'BAND(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'ch(\d{2})', lambda m: f'B{m.group(1)}'),
            (r'CH(\d{2})', lambda m: f'B{m.group(1)}'),
        ]

        # Try each pattern
        for pattern, mapper in patterns:
            match = re.search(pattern, dataset_name, re.IGNORECASE)
            if match:
                canonical = mapper(match)
                # Validate format (B01-B25)
                if re.match(r'^B\d{2}$', canonical):
                    logger.debug(f"[FY3D] Pattern match: {orig_name} -> {canonical}")
                    return canonical

        # Special case: Check if dataset name is already a canonical format
        if re.match(r'^B\d{2}$', dataset_name):
            logger.debug(f"[FY3D] Already canonical: {dataset_name}")
            return dataset_name

        # Fallback: Try to extract any number and convert to BXX format
        number_match = re.search(r'(\d{1,2})', dataset_name)
        if number_match:
            num = int(number_match.group(1))
            if 1 <= num <= 25:  # FY3D MERSI-2 has 25 bands (B01-B25)
                canonical = f'B{num:02d}'
                logger.debug(f"[FY3D] Number extraction: {orig_name} -> {canonical}")
                return canonical

        # Return as-is if no match
        logger.debug(f"[FY3D] No pattern match for: {orig_name}")
        return dataset_name

    def load_files(self, file_paths: List[str], **kwargs) -> bool:
        """
        Implement BasePolarDriver.load_files() abstract method.

        Delegates to load() so the driver satisfies both the base-class contract
        (BaseSatelliteDriver.load) and the polar-orbit contract
        (BasePolarDriver.load_files).
        """
        return self.load(file_paths)

    def unload(self) -> None:
        """Release loaded resources."""
        if self._scene is not None:
            try:
                self._scene = None
            except Exception:
                pass

        self._dataset_map.clear()
        self._band_catalog.clear()
        self._dataset_names.clear()
        self._primary_file_path = None
        self._swath_lons = None
        self._swath_lats = None
        self._geo_file_path = None
        self._is_loaded = False
        logger.info("FY3D MERSI driver resources released")

    # ==========================================================================
    # Swath and Geolocation Handling
    # ==========================================================================

    def _get_geolocation(self, dataset_name: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Get longitude/latitude coordinates for the dataset.

        Tries multiple methods in order:
        1. From SatPy scene area definition
        2. From pre-loaded GEO file
        3. From HDF5 file directly

        Args:
            dataset_name: Name of the dataset

        Returns:
            Tuple of (lons, lats) arrays, or (None, None) if not available
        """
        logger.info(f"[FY3D] Getting geolocation for: {dataset_name}")

        # Method 1: Try from scene area definition
        lons, lats = self._get_geolocation_from_scene(dataset_name)
        if lons is not None and lats is not None:
            logger.info(f"[FY3D] Got geolocation from scene: lons={lons.shape}, lats={lats.shape}")
            self._swath_lons = lons
            self._swath_lats = lats
            return lons, lats

        # Method 2: Try from pre-loaded GEO file
        lons, lats = self._get_geolocation_from_geo_file()
        if lons is not None and lats is not None:
            logger.info(f"[FY3D] Got geolocation from GEO file: lons={lons.shape}, lats={lats.shape}")
            self._swath_lons = lons
            self._swath_lats = lats
            return lons, lats

        # Method 3: Try extracting directly from HDF5
        lons, lats = self._extract_geolocation_from_hdf()
        if lons is not None and lats is not None:
            logger.info(f"[FY3D] Got geolocation from HDF5: lons={lons.shape}, lats={lats.shape}")
            self._swath_lons = lons
            self._swath_lats = lats
            return lons, lats

        logger.warning(f"[FY3D] Could not get geolocation for {dataset_name}")
        return None, None

    def _get_geolocation_from_scene(self, dataset_name: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Try to get geolocation from SatPy scene.

        Args:
            dataset_name: Name of the dataset

        Returns:
            Tuple of (lons, lats) or (None, None)
        """
        if self._scene is None:
            logger.debug("[FY3D] No scene available for geolocation extraction")
            return None, None

        try:
            logger.debug(f"[FY3D] Attempting to get geolocation from scene for dataset: {dataset_name}")

            # Strategy 1: Try to get area from specific dataset
            if dataset_name in self._scene:
                logger.debug(f"[FY3D] Dataset {dataset_name} found in scene")
                data = self._scene[dataset_name]
                
                # Check for area in dataset attributes
                area = data.attrs.get('area')
                if area is not None:
                    logger.debug(f"[FY3D] Found area definition in dataset attributes: {type(area).__name__}")
                    
                    # Check if it's an AreaDefinition with get_lonlats
                    if hasattr(area, 'get_lonlats'):
                        try:
                            lons, lats = area.get_lonlats()
                            if lons is not None and lats is not None:
                                logger.info(f"[FY3D] Got geolocation from dataset area: shape={lons.shape}")
                                return lons, lats
                        except Exception as e:
                            logger.debug(f"[FY3D] get_lonlats failed: {e}")

                    # Check if it's a SwathDefinition with lons/lats attributes
                    if hasattr(area, 'lons') and hasattr(area, 'lats'):
                        try:
                            lons = np.array(area.lons)
                            lats = np.array(area.lats)
                            if lons.size > 0 and lats.size > 0:
                                logger.info(f"[FY3D] Got geolocation from SwathDefinition: shape={lons.shape}")
                                return lons, lats
                        except Exception as e:
                            logger.debug(f"[FY3D] SwathDefinition conversion failed: {e}")

            # Strategy 2: Try scene-level get_lonlats
            if hasattr(self._scene, 'get_lonlats'):
                logger.debug(f"[FY3D] Trying scene-level get_lonlats for {dataset_name}")
                try:
                    lons, lats = self._scene.get_lonlats(dataset_name)
                    if lons is not None and lats is not None:
                        logger.info(f"[FY3D] Got geolocation from scene: shape={lons.shape}")
                        return lons, lats
                except Exception as e:
                    logger.debug(f"[FY3D] Scene get_lonlats failed: {e}")

            # Strategy 3: Try to get area from any available dataset
            logger.debug("[FY3D] Trying to get geolocation from any available dataset")
            for ds_name in list(self._scene.keys())[:5]:  # Try first 5 datasets
                try:
                    data = self._scene[ds_name]
                    area = data.attrs.get('area')
                    if area is not None:
                        if hasattr(area, 'get_lonlats'):
                            lons, lats = area.get_lonlats()
                            if lons is not None and lats is not None:
                                logger.info(f"[FY3D] Got geolocation from dataset {ds_name}: shape={lons.shape}")
                                return lons, lats
                        elif hasattr(area, 'lons') and hasattr(area, 'lats'):
                            lons = np.array(area.lons)
                            lats = np.array(area.lats)
                            if lons.size > 0 and lats.size > 0:
                                logger.info(f"[FY3D] Got geolocation from SwathDefinition in {ds_name}: shape={lons.shape}")
                                return lons, lats
                except Exception as e:
                    logger.debug(f"[FY3D] Failed to get geolocation from {ds_name}: {e}")

        except Exception as e:
            logger.warning(f"[FY3D] Could not get geolocation from scene: {e}")
            import traceback
            traceback.print_exc()

        logger.debug("[FY3D] No geolocation found in scene")
        return None, None

    def _find_geo_file(self, primary_file: str) -> Optional[str]:
        """
        Find corresponding GEO file for the L1 data file.

        GEO file naming patterns:
        - L1: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_1000M_MS.HDF
        - GEO: FY3D_MERSI_GBAL_L1_YYYYMMDD_HHMM_GEO1K_MS.HDF

        Args:
            primary_file: Path to the primary L1 file

        Returns:
            Path to GEO file or None if not found
        """
        dir_name = os.path.dirname(primary_file)
        base_name = os.path.basename(primary_file)
        base_name_upper = base_name.upper()

        logger.info(f"[FY3D] Searching for GEO file for: {base_name}")

        # Extract timestamp pattern: YYYYMMDD_HHMM
        ts_match = re.search(r'(\d{8})[_-](\d{4})', base_name)
        timestamp = None
        if ts_match:
            timestamp = f"{ts_match.group(1)}_{ts_match.group(2)}"
            logger.debug(f"[FY3D] Extracted timestamp: {timestamp}")

        # Build comprehensive patterns for GEO file
        geo_patterns = []
        
        # Pattern 1: Replace resolution with GEO
        resolutions = ['_1000M_', '_250M_', '_4000M_', '_1KM_', '_250M_']
        for res in resolutions:
            if res in base_name_upper:
                geo_pattern = base_name.replace(res, '_GEO_')
                geo_patterns.append(geo_pattern)
                logger.debug(f"[FY3D] Added GEO pattern: {geo_pattern}")

        # Pattern 2: Replace _MS with _GEO
        if '_MS' in base_name_upper:
            geo_pattern = base_name.replace('_MS', '_GEO')
            geo_patterns.append(geo_pattern)
            logger.debug(f"[FY3D] Added GEO pattern: {geo_pattern}")

        # Pattern 3: Replace .HDF with _GEO.HDF
        geo_patterns.extend([
            base_name.replace('.HDF', '_GEO.HDF'),
            base_name.replace('.hdf', '_GEO.hdf'),
            base_name.replace('.H5', '_GEO.H5'),
            base_name.replace('.h5', '_GEO.h5'),
        ])

        # Pattern 4: Generic patterns with timestamp
        if timestamp:
            geo_patterns.extend([
                f"FY3D_MERSI_GBAL_L1_{timestamp}_GEO1K_MS.HDF",
                f"FY3D_MERSI_GBAL_L1_{timestamp}_GEO.HDF",
                f"FY3D_MERSI_{timestamp}_GEO.HDF",
                f"FY3D*{timestamp}*GEO*.HDF",
            ])

        # Pattern 5: Common GEO file naming variations
        geo_patterns.extend([
            base_name.replace('L1_', 'L1_GEO_'),
            base_name.replace('L1B_', 'L1B_GEO_'),
        ])

        # Remove duplicates
        geo_patterns = list(set(geo_patterns))
        logger.debug(f"[FY3D] Generated {len(geo_patterns)} GEO file patterns")

        # Check each pattern
        for pattern in geo_patterns:
            geo_path = os.path.join(dir_name, pattern)
            if os.path.exists(geo_path):
                logger.info(f"[FY3D] Found GEO file: {pattern}")
                return geo_path

        # Also try extensive glob patterns for maximum flexibility
        glob_patterns = []
        if timestamp:
            glob_patterns.extend([
                os.path.join(dir_name, f"*MERSI*{timestamp}*GEO*.*"),
                os.path.join(dir_name, f"*FY3D*{timestamp}*GEO*.*"),
                os.path.join(dir_name, f"*GEO*{timestamp}*.*"),
            ])
        
        # Generic GEO patterns
        glob_patterns.extend([
            os.path.join(dir_name, f"*GEO*.HDF"),
            os.path.join(dir_name, f"*GEO*.hdf"),
            os.path.join(dir_name, f"*GEO*.H5"),
            os.path.join(dir_name, f"*GEO*.h5"),
            os.path.join(dir_name, f"*GEO*MS*.*"),
            os.path.join(dir_name, f"*MERSI*GEO*.*"),
        ])

        # Remove duplicates
        glob_patterns = list(set(glob_patterns))
        logger.debug(f"[FY3D] Generated {len(glob_patterns)} GEO glob patterns")

        # Check glob patterns
        for pattern in glob_patterns:
            matches = glob.glob(pattern)
            if matches:
                # Sort by modification time (most recent first)
                matches.sort(key=os.path.getmtime, reverse=True)
                geo_path = matches[0]
                logger.info(f"[FY3D] Found GEO file via glob: {geo_path}")
                return geo_path

        logger.warning(f"[FY3D] No GEO file found for {base_name}")
        # List all files in directory for debugging
        try:
            files = os.listdir(dir_name)
            geo_files = [f for f in files if 'GEO' in f.upper()]
            if geo_files:
                logger.debug(f"[FY3D] GEO-related files in directory: {geo_files}")
            else:
                logger.debug(f"[FY3D] No GEO files found in directory: {dir_name}")
        except Exception as e:
            logger.debug(f"[FY3D] Error listing directory: {e}")
        
        return None

    def _load_geo_file(self, geo_file: str) -> bool:
        """
        Load geolocation data from GEO file.

        Args:
            geo_file: Path to GEO file

        Returns:
            True if successfully loaded
        """
        try:
            import h5py

            with h5py.File(geo_file, 'r') as f:
                # Try common geolocation dataset names
                lon_names = ['longitude', 'Longitude', 'lon', 'Lon', 'Longitude_Ease', 'location/lon']
                lat_names = ['latitude', 'Latitude', 'lat', 'Lat', 'Latitude_Ease', 'location/lat']

                lons = None
                lats = None

                for lon_name in lon_names:
                    if lon_name in f:
                        lons = np.array(f[lon_name])
                        logger.info(f"[FY3D] Loaded longitude from: {lon_name}")
                        break

                for lat_name in lat_names:
                    if lat_name in f:
                        lats = np.array(f[lat_name])
                        logger.info(f"[FY3D] Loaded latitude from: {lat_name}")
                        break

                if lons is not None and lats is not None:
                    # Validate shapes match
                    if lons.shape == lats.shape:
                        self._swath_lons = lons.astype(np.float64)
                        self._swath_lats = lats.astype(np.float64)
                        self._geo_file_path = geo_file
                        logger.info(f"[FY3D] GEO data loaded: shape={lons.shape}")
                        return True
                    else:
                        logger.error(f"[FY3D] Longitude/latitude shape mismatch: {lons.shape} vs {lats.shape}")
                else:
                    # List available datasets for debugging
                    def visit_items(name, obj):
                        if isinstance(obj, h5py.Dataset) and ('lon' in name.lower() or 'lat' in name.lower()):
                            logger.debug(f"[FY3D] Available geolocation: {name} {obj.shape}")

                    try:
                        f.visititems(visit_items)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"[FY3D] Failed to load GEO file {geo_file}: {e}")

        return False

    def _get_geolocation_from_geo_file(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Get geolocation from pre-loaded GEO file.

        Returns:
            Tuple of (lons, lats) or (None, None)
        """
        if self._swath_lons is not None and self._swath_lats is not None:
            return self._swath_lons, self._swath_lats
        return None, None

    def _extract_geolocation_from_hdf(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Extract geolocation directly from HDF5 file.

        Used when GEO file is not available.

        Returns:
            Tuple of (lons, lats) or (None, None)
        """
        if self._scene is None or not self._dataset_names:
            logger.debug("[FY3D] No scene or datasets available for geolocation extraction")
            return None, None

        try:
            import h5py

            # Use the saved primary file path
            file_path = self._primary_file_path
            if file_path is None:
                logger.warning("[FY3D] No primary file path saved — cannot extract geolocation from HDF")
                return None, None

            if not os.path.exists(file_path):
                logger.warning(f"[FY3D] File does not exist: {file_path}")
                return None, None

            logger.info(f"[FY3D] Extracting geolocation from HDF5: {os.path.basename(file_path)}")

            with h5py.File(file_path, 'r') as f:
                # Comprehensive list of potential geolocation paths
                geo_paths = [
                    # Common top-level paths
                    'Geolocation',
                    'Navigation',
                    'Geolocation_Data',
                    'Geo',
                    'LonLat',
                    'Location',
                    'Geodetic',
                    'GEO',
                    'NAV',
                    
                    # Nested paths
                    '/Geolocation',
                    '/Navigation',
                    '/Geolocation_Data',
                    '/Geo',
                    '/LonLat',
                    '/Location',
                    '/Geodetic',
                    '/GEO',
                    '/NAV',
                    
                    # Data subdirectories
                    'Data/Geolocation',
                    'Data/Navigation',
                    'Data/Geo',
                    'Data/LonLat',
                    'Data/Location',
                    'Data/Geodetic',
                    
                    # FY3D specific paths
                    'Geolocation/Longitude',
                    'Geolocation/Latitude',
                    'Navigation/Longitude',
                    'Navigation/Latitude',
                    'Geolocation_Data/Longitude',
                    'Geolocation_Data/Latitude',
                    
                    # Direct access to common geolocation datasets
                    'Longitude',
                    'Latitude',
                    'longitude',
                    'latitude',
                    'lon',
                    'lat',
                    'Lon',
                    'Lat',
                ]

                # Comprehensive list of longitude and latitude dataset names
                lon_names = ['Longitude', 'longitude', 'lon', 'Lon', 'LON', 'Longitude_Ease', 'Longitude_Image']
                lat_names = ['Latitude', 'latitude', 'lat', 'Lat', 'LAT', 'Latitude_Ease', 'Latitude_Image']

                # First pass: try direct paths
                logger.debug(f"[FY3D] Checking {len(geo_paths)} potential geolocation paths")
                for path in geo_paths:
                    if path in f:
                        logger.debug(f"[FY3D] Found path: {path}")
                        # Check if this is a dataset (direct geolocation)
                        if isinstance(f[path], h5py.Dataset):
                            # Check if it's longitude or latitude
                            path_upper = path.upper()
                            if 'LON' in path_upper:
                                # Try to find corresponding latitude
                                for lat_name in lat_names:
                                    lat_path = path.replace(path.split('/')[-1], lat_name)
                                    if lat_path in f:
                                        lons = np.array(f[path])
                                        lats = np.array(f[lat_path])
                                        if lons.shape == lats.shape:
                                            logger.info(f"[FY3D] Found geolocation at {path} and {lat_path}")
                                            return lons.astype(np.float64), lats.astype(np.float64)
                            elif 'LAT' in path_upper:
                                # Try to find corresponding longitude
                                for lon_name in lon_names:
                                    lon_path = path.replace(path.split('/')[-1], lon_name)
                                    if lon_path in f:
                                        lats = np.array(f[path])
                                        lons = np.array(f[lon_path])
                                        if lons.shape == lats.shape:
                                            logger.info(f"[FY3D] Found geolocation at {lon_path} and {path}")
                                            return lons.astype(np.float64), lats.astype(np.float64)
                        else:
                            # It's a group, check for lon/lat datasets inside
                            grp = f[path]
                            for lon_name in lon_names:
                                if lon_name in grp:
                                    lons = np.array(grp[lon_name])
                                    for lat_name in lat_names:
                                        if lat_name in grp:
                                            lats = np.array(grp[lat_name])
                                            if lons.shape == lats.shape:
                                                logger.info(f"[FY3D] Found geolocation at {path}/{lon_name}")
                                                return lons.astype(np.float64), lats.astype(np.float64)

                # Second pass: recursive search for any geolocation datasets
                logger.debug("[FY3D] Performing recursive search for geolocation datasets")
                found_lon = None
                found_lat = None
                
                def find_geo_datasets(name, obj):
                    nonlocal found_lon, found_lat
                    if isinstance(obj, h5py.Dataset):
                        name_upper = name.upper()
                        if any(lon in name_upper for lon in ['LON', 'LONGITUDE']) and found_lon is None:
                            found_lon = (name, obj)
                            logger.debug(f"[FY3D] Found potential longitude: {name}")
                        elif any(lat in name_upper for lat in ['LAT', 'LATITUDE']) and found_lat is None:
                            found_lat = (name, obj)
                            logger.debug(f"[FY3D] Found potential latitude: {name}")

                f.visititems(find_geo_datasets)

                if found_lon and found_lat:
                    lon_path, lon_ds = found_lon
                    lat_path, lat_ds = found_lat
                    lons = np.array(lon_ds)
                    lats = np.array(lat_ds)
                    if lons.shape == lats.shape:
                        logger.info(f"[FY3D] Found geolocation via recursive search: {lon_path} and {lat_path}")
                        return lons.astype(np.float64), lats.astype(np.float64)

                # List all datasets for debugging
                logger.debug("[FY3D] Listing all datasets for debugging:")
                def list_datasets(name, obj):
                    if isinstance(obj, h5py.Dataset):
                        if any(keyword in name.lower() for keyword in ['lon', 'lat', 'geo', 'nav']):
                            logger.debug(f"[FY3D] Dataset: {name} (shape: {obj.shape})")

                f.visititems(list_datasets)

        except Exception as e:
            logger.warning(f"[FY3D] Could not extract geolocation from HDF5: {e}")
            import traceback
            traceback.print_exc()

        logger.warning("[FY3D] No geolocation found in HDF5 file")
        return None, None

    def _check_and_handle_swath(self, dataset_name: str) -> Tuple[bool, Any]:
        """
        Check if data is swath-based and create appropriate area definition.

        Args:
            dataset_name: Name of the dataset

        Returns:
            Tuple of (is_swath, area_definition)
        """
        if self._scene is None:
            return False, None

        # Check if dataset has area definition
        if dataset_name in self._scene:
            area = self._scene[dataset_name].attrs.get('area')
            if area is not None:
                # Check area type
                area_type = type(area).__name__
                if 'Swath' in area_type:
                    logger.info(f"[FY3D] Detected SwathDefinition: {area_type}")
                    self._is_swath = True
                    # Get geolocation from SwathDefinition
                    if hasattr(area, 'lons') and hasattr(area, 'lats'):
                        self._swath_lons = np.array(area.lons)
                        self._swath_lats = np.array(area.lats)
                    return True, area

                # AreaDefinition exists - not a pure swath
                logger.debug(f"[FY3D] Found AreaDefinition: {area_type}")
                return False, area

        # No area definition - check if we have geolocation
        lons, lats = self._get_geolocation(dataset_name)
        if lons is not None and lats is not None:
            logger.info(f"[FY3D] Creating SwathDefinition from geolocation")
            self._is_swath = True
            from pyresample.geometry import SwathDefinition
            swath_def = SwathDefinition(lons, lats)
            return True, swath_def

        logger.warning(f"[FY3D] No area or geolocation found for {dataset_name}")
        return False, None

    def _fit_geolocation_to_data_shape(
        self,
        lons: np.ndarray,
        lats: np.ndarray,
        data_shape: Tuple[int, int],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Match geolocation grid shape to band data shape.

        FY3D GEO files may provide lon/lat at a different resolution than the
        currently requested band (e.g. 1km GEO with 250m reflective bands). We
        resample lon/lat with nearest-neighbor indexing so pyresample receives
        arrays that are shape-compatible with source data.
        """
        if lons.ndim != 2 or lats.ndim != 2:
            raise ValueError(
                f"Geolocation must be 2D arrays, got lons={lons.shape}, lats={lats.shape}"
            )

        target_h, target_w = int(data_shape[0]), int(data_shape[1])
        if lons.shape == (target_h, target_w):
            return lons, lats

        src_h, src_w = lons.shape
        if src_h <= 1 or src_w <= 1 or target_h <= 1 or target_w <= 1:
            raise ValueError(
                f"Invalid geolocation resize dimensions: src={lons.shape}, target={(target_h, target_w)}"
            )

        row_idx = np.linspace(0, src_h - 1, target_h).astype(np.int64)
        col_idx = np.linspace(0, src_w - 1, target_w).astype(np.int64)
        lons_fit = lons[np.ix_(row_idx, col_idx)]
        lats_fit = lats[np.ix_(row_idx, col_idx)]

        logger.info(
            f"[FY3D] Resized geolocation grid: {lons.shape} -> {lons_fit.shape} "
            f"for data shape {(target_h, target_w)}"
        )
        return lons_fit, lats_fit

    def _resample_swath_to_grid(self, data: np.ndarray,
                                 target_area) -> Optional[np.ndarray]:
        """
        Resample swath data to target grid using pyresample.

        Args:
            data: Input swath data array
            target_area: Target Pyresample AreaDefinition

        Returns:
            Resampled data array on target grid, or None if resampling failed.
        """
        if self._swath_lons is None or self._swath_lats is None:
            logger.error("[FY3D] Cannot resample: no geolocation available")
            return None

        try:
            from pyresample.geometry import SwathDefinition
            from pyresample.kd_tree import resample_nearest

            # Ensure geolocation grid is shape-compatible with current band.
            lons_fit, lats_fit = self._fit_geolocation_to_data_shape(
                np.asarray(self._swath_lons, dtype=np.float64),
                np.asarray(self._swath_lats, dtype=np.float64),
                data.shape[:2],
            )

            # Create swath definition
            swath_def = SwathDefinition(lons_fit, lats_fit)

            # Get valid data mask
            valid_mask = np.isfinite(data) & np.isfinite(lons_fit) & np.isfinite(lats_fit)
            if not np.any(valid_mask):
                logger.warning("[FY3D] No valid data in swath")
                return None

            valid_ratio = float(np.sum(valid_mask)) / float(valid_mask.size)
            if valid_ratio < 0.01:
                logger.warning(f"[FY3D] Too few valid swath samples ({valid_ratio:.2%})")
                return None

            # Mask invalid source samples for stable nearest-neighbor behaviour.
            data_masked = np.ma.array(data.astype(np.float32), mask=~valid_mask)

            # Estimate radius_of_influence from target grid spacing.
            roi = 5000.0
            try:
                proj_name = getattr(target_area, 'proj_dict', {}).get('proj')
                if proj_name in ('longlat', 'latlong', 'eqc'):
                    west, south, east, north = target_area.area_extent
                    h, w = target_area.shape
                    dx_deg = abs((east - west) / max(1, w))
                    dy_deg = abs((north - south) / max(1, h))
                    pixel_m = max(dx_deg, dy_deg) * 111_320.0
                    roi = max(2000.0, pixel_m * 2.5)
            except Exception:
                roi = 5000.0

            # Resample with appropriate parameters
            logger.info(f"[FY3D] Resampling swath to grid: {data.shape} -> {target_area.shape}")
            logger.info(f"[FY3D] Using radius of influence: {roi} meters")

            resampled = resample_nearest(
                swath_def,
                data_masked,
                target_area,
                radius_of_influence=roi,
                fill_value=np.nan,
                nprocs=1,  # Keep deterministic/stable in GUI worker threads.
            )

            # Ensure ndarray (some pyresample versions return masked arrays).
            resampled = np.asarray(np.ma.filled(resampled, np.nan), dtype=np.float32)

            # Calculate resampling statistics
            valid_resampled = np.isfinite(resampled)
            coverage_ratio = np.sum(valid_resampled) / valid_resampled.size
            logger.info(f"[FY3D] Resampled data shape: {resampled.shape}")
            logger.info(f"[FY3D] Resampling coverage: {coverage_ratio:.2%} of target grid")

            if coverage_ratio < 0.01:
                logger.warning("[FY3D] Resampling coverage too low")
                return None

            return resampled

        except ImportError as e:
            logger.error(f"[FY3D] pyresample not available: {e}")
            return None
        except Exception as e:
            logger.error(f"[FY3D] Resampling failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==========================================================================
    # Image Generation
    # ==========================================================================

    def request_image(self, params: ProcessingParams) -> Tuple[np.ndarray, Any]:
        """
        Generate image from loaded scene.

        Handles both geostationary (AreaDefinition) and polar-orbiting (Swath) data.

        Args:
            params: Processing parameters

        Returns:
            Tuple of (image_array, area_definition)
        """
        if not self._is_loaded or self._scene is None:
            raise ValueError("No scene loaded")

        try:
            # Reset swath state
            self._is_swath = False
            self._swath_lons = None
            self._swath_lats = None

            # Map canonical band names to dataset names
            datasets = []
            for band in params.bands:
                clean_band = self._extract_canonical_from_display(band)
                ds_name = self._resolve_dataset_name(clean_band)
                if ds_name:
                    datasets.append(ds_name)

            logger.info(f"[FY3D] Requested bands: {params.bands}")
            logger.info(f"[FY3D] Dataset names: {datasets}")

            if not datasets:
                logger.error("[FY3D] No valid datasets found")
                raise ValueError("Could not resolve any band names to datasets")

            # Load datasets — thermal bands use Satpy calibration='brightness_temperature'
            # so the reader returns physically meaningful BT (K) instead of raw DN.
            from core.config import get_thermal_bands
            thermal_canonical = get_thermal_bands('MERSI_L1')  # {'B20','B21',...,'B25'}

            def _is_thermal(ds_name: str) -> bool:
                canon = self._canonical_from_dataset(ds_name, datasets)
                return canon in thermal_canonical

            thermal_ds = [ds for ds in datasets if _is_thermal(ds)]
            reflective_ds = [ds for ds in datasets if ds not in thermal_ds]

            logger.info(f"[FY3D] Reflective datasets: {reflective_ds}")
            logger.info(f"[FY3D] Thermal datasets: {thermal_ds}")

            if reflective_ds:
                self._scene.load(reflective_ds, calibration='reflectance')
            if thermal_ds:
                try:
                    self._scene.load(thermal_ds, calibration='brightness_temperature')
                except Exception as e:
                    logger.warning(f"[FY3D] BT calibration failed ({e}), loading with default calibration")
                    self._scene.load(thermal_ds)

            # Get area definition and check for swath
            area_def = None
            primary_ds = datasets[0]

            # Try to find and load GEO file if geolocation not yet available
            if self._swath_lons is None and self._primary_file_path:
                geo_file = self._find_geo_file(self._primary_file_path)
                if geo_file:
                    self._load_geo_file(geo_file)

            # Check for swath data
            is_swath, area_def = self._check_and_handle_swath(primary_ds)

            if is_swath:
                logger.info(f"[FY3D] Processing swath data with shape: {self._swath_lons.shape if self._swath_lons is not None else 'unknown'}")

            # Import projection factory
            from core.geometry import ProjectionFactory

            # Get target area for geographic projections
            target_area = None
            effective_proj = params.output_proj

            # Polar-orbit (swath) data ALWAYS needs resampling to a regular grid.
            # geostationary_native projection is meaningless for swath data — fall back
            # to a custom plate_carree grid derived from the actual swath extent.
            if is_swath:
                needs_resampling = True
                if effective_proj == 'geostationary_native':
                    effective_proj = None  # trigger custom-extent fallback below
            else:
                # Even if SatPy returns AreaDefinition, we still honor requested
                # non-native projection for consistent alignment with basemap.
                needs_resampling = params.output_proj != 'geostationary_native'

            if needs_resampling:
                custom_width = None
                custom_height = None
                if params.output_size:
                    custom_width = int(params.output_size[0])
                    custom_height = int(params.output_size[1])
                if effective_proj is not None:
                    target_area = ProjectionFactory.create_target_area(
                        effective_proj,
                        custom_width=custom_width,
                        custom_height=custom_height,
                        source_area=area_def
                    )
                if target_area is None:
                    # Create a pyresample AreaDefinition from the actual swath extent.
                    # NOTE: ProjectionFactory.create_from_extent() returns ProjectionConfig,
                    # not an AreaDefinition, so we build one directly here.
                    if self._swath_lons is not None:
                        lons_valid = self._swath_lons[np.isfinite(self._swath_lons)]
                        lats_valid = self._swath_lats[np.isfinite(self._swath_lats)]
                        if len(lons_valid) > 0:
                            west = float(np.min(lons_valid))
                            east = float(np.max(lons_valid))
                            south = float(np.min(lats_valid))
                            north = float(np.max(lats_valid))
                            from pyresample import geometry as _geom
                            _proj_dict = {'proj': 'longlat', 'datum': 'WGS84'}
                            if custom_width is not None and custom_height is not None:
                                _width = custom_width
                                _height = custom_height
                            else:
                                _width = max(1, int((east - west) / 0.01))
                                _height = max(1, int((north - south) / 0.01))
                            target_area = _geom.AreaDefinition(
                                area_id='fy3d_swath_grid',
                                description='FY3D swath resampled at 0.01 deg',
                                proj_id='longlat',
                                projection=_proj_dict,
                                width=_width,
                                height=_height,
                                area_extent=(west, south, east, north),
                            )
                logger.info(f"[FY3D] Target area: {target_area}")

            # Non-swath path: use SatPy native resampling when projection conversion
            # is requested and target area is available.
            scene_for_read = self._scene
            if not is_swath and target_area is not None:
                try:
                    scene_for_read = self._scene.resample(
                        target_area,
                        resampler=params.resample_method
                    )
                    area_def = target_area
                    logger.info("[FY3D] Resampled scene via SatPy for non-swath data")
                except Exception as e:
                    logger.warning(f"[FY3D] SatPy scene resample failed, using source area: {e}")
                    scene_for_read = self._scene

            # Load band data
            band_data = {}
            swath_resample_failed = False
            for ds_name in datasets:
                try:
                    data = scene_for_read[ds_name]
                    arr = data.values.astype(np.float32)

                    logger.info(f"[FY3D] Raw band {ds_name}: shape={arr.shape}, dtype={arr.dtype}")

                    # Handle thermal bands (convert to brightness temperature if needed)
                    canonical = self._canonical_from_dataset(ds_name, datasets)
                    if canonical in THERMAL_BANDS:
                        arr = self._convert_to_brightness_temp(ds_name, arr)

                    # Resample swath data if needed
                    if is_swath and needs_resampling and target_area is not None:
                        arr_resampled = self._resample_swath_to_grid(arr, target_area)
                        if arr_resampled is None:
                            swath_resample_failed = True
                            logger.error(
                                f"[FY3D] Swath resampling failed for {ds_name}; "
                                "keeping original swath array"
                            )
                        else:
                            arr = arr_resampled

                    band_data[ds_name] = arr
                    logger.info(f"[FY3D] Band {ds_name}: shape={arr.shape}, min={np.nanmin(arr):.4f}, max={np.nanmax(arr):.4f}")
                except Exception as e:
                    logger.error(f"[FY3D] Failed to load {ds_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    band_data[ds_name] = np.zeros((1000, 1000), dtype=np.float32)

            # Normalize and composite
            if len(datasets) == 3:
                img = self._process_rgb_composite(datasets, band_data, params.gamma)
            elif len(datasets) == 1:
                img = self._process_single_band(datasets[0], band_data, params.gamma)
            else:
                # Use first 3 bands for RGB if available
                rgb_bands = [d for d in datasets if d in band_data][:3]
                if len(rgb_bands) >= 3:
                    img = self._process_rgb_composite(rgb_bands, band_data, params.gamma)
                else:
                    img = self._process_single_band(datasets[0], band_data, params.gamma)

            # Only advertise target geolocation when swath resampling actually succeeded.
            if is_swath and needs_resampling and target_area is not None and not swath_resample_failed:
                area_def = target_area
            elif is_swath and swath_resample_failed:
                logger.warning(
                    "[FY3D] Returning image without georeferenced target area because "
                    "swath resampling failed"
                )
                area_def = None
            elif needs_resampling and target_area is not None:
                area_def = target_area

            return img, area_def

        except Exception as e:
            logger.error(f"[FY3D] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _convert_to_brightness_temp(self, dataset_name: str, data: np.ndarray) -> np.ndarray:
        """
        Return brightness temperature array.

        When Satpy loaded the dataset with calibration='brightness_temperature',
        the values are already in Kelvin (~200-330 K for MERSI-2 thermal bands).
        In that case we just pass the array through unchanged.

        Falls back to a Stefan-Boltzmann approximation only when values look like
        raw DN (very large numbers or outside the physical BT range).

        Args:
            dataset_name: Satpy dataset name (for logging)
            data: Data array from Satpy (should be BT in K if loaded correctly)

        Returns:
            Brightness temperature array in Kelvin
        """
        try:
            arr_min = float(np.nanmin(data))
            arr_max = float(np.nanmax(data))

            # Physical BT range for Earth scenes: ~170 K (cold cloud tops) to ~340 K
            BT_MIN, BT_MAX = 170.0, 340.0

            if BT_MIN <= arr_min and arr_max <= BT_MAX:
                # Values already look like BT in Kelvin — Satpy calibration worked
                logger.debug(
                    f"[FY3D] BT pass-through for {dataset_name}: "
                    f"min={arr_min:.1f} K, max={arr_max:.1f} K"
                )
                return data.astype(np.float32)

            # Fallback: values are not in the expected BT range (raw DN or radiance).
            # Log a warning and apply a linear rescale to the nominal BT window.
            logger.warning(
                f"[FY3D] {dataset_name} values outside BT range "
                f"({arr_min:.2f}~{arr_max:.2f}); applying linear rescale fallback"
            )
            if arr_max > arr_min:
                normalized = (data - arr_min) / (arr_max - arr_min)
                return (normalized * (BT_MAX - BT_MIN) + BT_MIN).astype(np.float32)
            return np.full_like(data, 250.0, dtype=np.float32)

        except Exception as e:
            logger.warning(f"[FY3D] BT conversion failed for {dataset_name}: {e}")
            return data

    def _align_bands(self, band_data: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        Align bands of different resolutions to a common grid.

        For FY3D MERSI:
        - Bands B01-B04: 250m resolution
        - Bands B05-B19: 1000m resolution
        - Band B20: 4000m resolution

        Args:
            band_data: Dictionary of band data arrays with potentially different resolutions

        Returns:
            Dictionary of aligned band data arrays
        """
        if not band_data:
            return band_data

        logger.info(f"[FY3D] Aligning {len(band_data)} bands with different resolutions")

        # Determine target resolution based on available bands
        # Prefer higher resolution (smaller pixels) if available
        shapes = [arr.shape for arr in band_data.values()]
        max_res_shape = max(shapes, key=lambda s: s[0] * s[1])  # Largest shape = highest resolution
        logger.info(f"[FY3D] Target resolution shape: {max_res_shape}")

        aligned_bands = {}
        from scipy.ndimage import zoom

        for band_name, arr in band_data.items():
            if arr.shape == max_res_shape:
                # Already at target resolution
                aligned_bands[band_name] = arr
                logger.debug(f"[FY3D] Band {band_name} already at target resolution: {arr.shape}")
            else:
                # Calculate zoom factors
                zoom_factor = (max_res_shape[0] / arr.shape[0], max_res_shape[1] / arr.shape[1])
                logger.debug(f"[FY3D] Zooming band {band_name} by factors: {zoom_factor}")

                # Apply zoom with appropriate interpolation
                # For reflective bands, use bilinear interpolation
                # For thermal bands, use nearest neighbor to preserve radiometric integrity
                canonical = self._canonical_from_dataset(band_name, list(band_data.keys()))
                if canonical in THERMAL_BANDS:
                    # Thermal bands: use nearest neighbor
                    aligned = zoom(arr, zoom_factor, order=0)
                    logger.debug(f"[FY3D] Used nearest neighbor interpolation for thermal band {canonical}")
                else:
                    # Reflective bands: use bilinear interpolation
                    aligned = zoom(arr, zoom_factor, order=1)
                    logger.debug(f"[FY3D] Used bilinear interpolation for reflective band {canonical}")

                aligned_bands[band_name] = aligned
                logger.info(f"[FY3D] Aligned band {band_name}: {arr.shape} -> {aligned.shape}")

        return aligned_bands

    def _process_rgb_composite(self, datasets: List[str],
                               band_data: Dict[str, np.ndarray],
                               gamma: float) -> np.ndarray:
        """
        Process RGB composite from three bands.

        Args:
            datasets: List of 3 dataset names (R, G, B)
            band_data: Dictionary of band data arrays
            gamma: Gamma correction value

        Returns:
            RGB image array
        """
        # Get band data
        r = band_data.get(datasets[0], np.zeros((1000, 1000)))
        g = band_data.get(datasets[1], np.zeros((1000, 1000)))
        b = band_data.get(datasets[2], np.zeros((1000, 1000)))

        # Align bands to common resolution
        aligned_data = self._align_bands({datasets[0]: r, datasets[1]: g, datasets[2]: b})
        r = aligned_data.get(datasets[0], r)
        g = aligned_data.get(datasets[1], g)
        b = aligned_data.get(datasets[2], b)

        logger.info(f"[FY3D] RGB bands aligned to shape: R={r.shape}, G={g.shape}, B={b.shape}")

        # Normalize each band using percentile
        normalized_bands = []
        for arr, name in [(r, 'R'), (g, 'G'), (b, 'B')]:
            p2, p98 = np.nanpercentile(arr, (2, 98))
            if p98 > p2:
                norm = np.clip((arr - p2) / (p98 - p2), 0, 1)
                logger.debug(f"[FY3D] Normalized {name} band: min={p2:.4f}, max={p98:.4f}")
            else:
                norm = np.zeros_like(arr)
                logger.warning(f"[FY3D] Could not normalize {name} band: min={p2}, max={p98}")
            normalized_bands.append(norm)

        r, g, b = normalized_bands

        # Stack as RGB
        img = np.stack([r, g, b], axis=-1)
        logger.info(f"[FY3D] Created RGB composite with shape: {img.shape}")

        # Apply gamma correction
        if gamma != 1.0:
            img = np.power(np.clip(img, 0, 1), 1.0 / gamma)
            logger.debug(f"[FY3D] Applied gamma correction: {gamma}")

        # Handle NaN
        img = np.nan_to_num(img, nan=0.0)
        logger.debug(f"[FY3D] Handled NaN values in RGB composite")

        return img

    def _process_single_band(self, dataset_name: str,
                             band_data: Dict[str, np.ndarray],
                             gamma: float) -> np.ndarray:
        """
        Process single band as grayscale image.

        Args:
            dataset_name: Dataset name
            band_data: Dictionary of band data arrays
            gamma: Gamma correction value

        Returns:
            Grayscale image array
        """
        arr = band_data.get(dataset_name, np.zeros((1000, 1000)))
        logger.info(f"[FY3D] Processing single band: {dataset_name}, shape={arr.shape}")

        # Check if this is a thermal band and ensure it's properly scaled
        canonical = self._canonical_from_dataset(dataset_name, [dataset_name])
        if canonical in THERMAL_BANDS:
            logger.debug(f"[FY3D] Processing thermal band: {canonical}")
            # Thermal bands are already converted to brightness temperature in request_image
            # For visualization, we should use a different normalization range
            # Typical BT range for FY3D MERSI: ~200K-320K
            min_val = np.nanmin(arr)
            max_val = np.nanmax(arr)
            logger.debug(f"[FY3D] Thermal band range: {min_val:.1f}K - {max_val:.1f}K")
            
            # Use fixed range for better visualization
            if max_val > min_val:
                # Normalize to typical thermal range
                norm = np.clip((arr - 200) / (320 - 200), 0, 1)
                logger.debug(f"[FY3D] Normalized thermal band using fixed range [200, 320]K")
            else:
                norm = np.zeros_like(arr)
        else:
            # Reflective bands: use percentile normalization
            logger.debug(f"[FY3D] Processing reflective band: {canonical}")
            p2, p98 = np.nanpercentile(arr, (2, 98))
            if p98 > p2:
                norm = np.clip((arr - p2) / (p98 - p2), 0, 1)
                logger.debug(f"[FY3D] Normalized using percentiles: p2={p2:.4f}, p98={p98:.4f}")
            else:
                norm = np.zeros_like(arr)
                logger.warning(f"[FY3D] Could not normalize band {dataset_name}: min={np.nanmin(arr):.4f}, max={np.nanmax(arr):.4f}")

        # Apply gamma correction
        if gamma != 1.0:
            norm = np.power(norm, 1.0 / gamma)
            logger.debug(f"[FY3D] Applied gamma correction: {gamma}")

        # Create RGB from grayscale
        img = np.stack([norm] * 3, axis=-1)
        img = np.nan_to_num(img, nan=0.0)
        logger.info(f"[FY3D] Created single band image: shape={img.shape}")

        return img

    def _resolve_dataset_name(self, band_name: str) -> Optional[str]:
        """
        Resolve a band name to an actual dataset name in the scene.

        Uses multiple strategies to find the dataset:
        1. Direct match
        2. Dataset map lookup
        3. Pattern matching with multiple formats
        4. Case-insensitive substring search

        Args:
            band_name: The band name to resolve (can be canonical B01 or display name)

        Returns:
            The actual dataset name or None
        """
        if self._scene is None:
            return None

        available = self._scene.available_dataset_names()
        logger.info(f"[FY3D] Resolving band name: '{band_name}'")
        logger.info(f"[FY3D] Available datasets ({len(available)}): {available}")

        # Extract canonical name from display name if needed
        canonical = self._extract_canonical_from_display(band_name)
        if canonical != band_name:
            logger.debug(f"[FY3D] Extracted canonical: '{canonical}' from '{band_name}'")

        # Strategy 1: Direct match (case-insensitive)
        band_name_upper = band_name.upper()
        for ds in available:
            if ds.upper() == band_name_upper:
                logger.debug(f"[FY3D] Direct match: '{band_name}' -> '{ds}'")
                return ds

        # Strategy 2: Dataset map lookup
        if canonical in self._dataset_map:
            ds_name = self._dataset_map[canonical]
            if ds_name in available:
                logger.debug(f"[FY3D] Dataset map hit: '{canonical}' -> '{ds_name}'")
                return ds_name

        # Strategy 3: Extract band number and try multiple patterns
        import re
        match = re.match(r'^B(\d{2})$', canonical, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            logger.debug(f"[FY3D] Extracted band number: {num}")

            # Build comprehensive pattern list
            # For Satpy mersi2_l1b, datasets are named as integer strings '1'~'25'
            # so always try those first.
            patterns = [f'{num}', f'{num:02d}']

            # Standard FY3D MERSI HDF5 naming (fallback for direct HDF5 access)
            if num <= 4:  # 250m reflective bands
                patterns.extend([
                    f'EV_250_RefSB{num:02d}',
                    f'EV_250M_RefSB{num:02d}',
                    f'250M_RefSB{num:02d}',
                ])
            elif num <= 19:  # 1000m reflective bands (visible/NIR/ocean-color/SWIR)
                ref_idx = num  # B05~B19 stored as EV_1000_RefSB05~19
                patterns.extend([
                    f'EV_1000_RefSB{ref_idx:02d}',
                    f'EV_1000M_RefSB{ref_idx:02d}',
                    f'1000M_RefSB{ref_idx:02d}',
                ])
            elif num <= 25:  # 1000m thermal emissive bands B20~B25 -> Emissive01~06
                em_idx = num - 19  # B20->01, B25->06
                patterns.extend([
                    f'EV_1000_Emissive{em_idx:02d}',
                    f'EV_1000M_Emissive{em_idx:02d}',
                    f'1000M_Emissive{em_idx:02d}',
                ])

            # Generic patterns
            patterns.extend([
                f'B{num:02d}',
                f'_B{num:02d}',
                f'Band{num:02d}',
                f'band{num:02d}',
            ])

            for pattern in patterns:
                pattern_upper = pattern.upper()
                for ds in available:
                    if ds.upper() == pattern_upper:
                        logger.debug(f"[FY3D] Pattern match: '{pattern}' -> '{ds}'")
                        return ds

        # Strategy 4: Substring/contains search (case-insensitive)
        for ds in available:
            ds_upper = ds.upper()
            # Check various match conditions
            if (band_name_upper in ds_upper or
                canonical.upper() in ds_upper or
                ds_upper in band_name_upper or
                ds_upper in canonical.upper()):
                # Make sure it's a reasonable match (not just matching a single digit)
                logger.debug(f"[FY3D] Contains match: '{band_name}' -> '{ds}'")
                return ds

        # Fallback: Log warning and return first available dataset
        logger.warning(f"[FY3D] Could not resolve band name '{band_name}'")
        logger.warning(f"[FY3D] Available datasets: {available}")
        if available:
            # Return first available dataset as fallback for debugging
            return available[0]
        return None

    def _extract_canonical_from_display(self, display_name: str) -> str:
        """
        Extract canonical band name from display name.

        Args:
            display_name: Display name (e.g., 'B13 (12.0 μm - thermal)')

        Returns:
            Canonical band name (e.g., 'B13')
        """
        import re
        match = re.match(r'^(B\d{2})', display_name.strip(), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return display_name

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get standardized metadata for loaded scene.

        Returns:
            Dictionary containing metadata
        """
        if self._scene is None:
            return {}

        try:
            start_time = self._scene.start_time
            platform = self._scene.attrs.get('platform_name', 'FY3D')
            sensor = self._scene.attrs.get('sensor', 'MERSI-2')
        except Exception as e:
            logger.warning(f"[FY3D] Failed to get scene metadata: {e}")
            start_time = None
            platform = 'FY3D'
            sensor = 'MERSI-2'

        return {
            'satellite': platform,
            'sensor': sensor,
            'satellite_type': 'FY3D',
            'product_level': self._current_level.value if self._current_level else 'L1',
            'start_time': start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else "N/A",
            'n_bands': len(self._dataset_map),
            'is_loaded': self._is_loaded,
            'coverage': self.get_satellite_coverage(),
        }

    def get_satellite_coverage(self) -> Optional[Tuple[float, float, float, float]]:
        """
        Get geographic coverage for FY3D satellite.

        For FY3D (polar-orbiting), returns the actual swath coverage if geolocation is available,
        otherwise returns global coverage as fallback.

        Returns:
            Tuple of (west, east, south, north) in degrees
        """
        # If we have geolocation data, use actual swath extent
        if self._swath_lons is not None and self._swath_lats is not None:
            try:
                # Get valid longitude/latitude values
                lons_valid = self._swath_lons[np.isfinite(self._swath_lons)]
                lats_valid = self._swath_lats[np.isfinite(self._swath_lats)]
                
                if len(lons_valid) > 0 and len(lats_valid) > 0:
                    # Calculate actual swath extent
                    west = float(np.min(lons_valid))
                    east = float(np.max(lons_valid))
                    south = float(np.min(lats_valid))
                    north = float(np.max(lats_valid))
                    
                    # Add small buffer to ensure full coverage
                    buffer = 0.5  # 0.5 degrees buffer
                    west = max(west - buffer, -180)
                    east = min(east + buffer, 180)
                    south = max(south - buffer, -90)
                    north = min(north + buffer, 90)
                    
                    logger.info(f"[FY3D] Using actual swath coverage: {west:.2f}, {east:.2f}, {south:.2f}, {north:.2f}")
                    return (west, east, south, north)
            except Exception as e:
                logger.warning(f"[FY3D] Failed to calculate actual coverage: {e}")
        
        # Fallback to global coverage if no geolocation data
        logger.debug("[FY3D] Using fallback global coverage")
        return SATELLITE_COVERAGE.get(self.SATELLITE_TYPE, (-180, 180, -90, 90))

    def get_time_series_groups(self, file_paths: List[str]) -> List[List[str]]:
        """
        Group file paths by timestamp for time-series processing.

        Args:
            file_paths: List of file paths

        Returns:
            List of file groups, each representing one time point
        """
        import re
        groups: Dict[str, List[str]] = {}

        for path in sorted(file_paths):
            filename = os.path.basename(path)

            # Extract timestamp: YYYYMMDD_HHMM from pattern
            # Example: FY3D_MERSI_GBAL_L1_20260209_0615_1000M_MS.HDF
            match = re.search(r'(\d{8})[_-](\d{4})', filename)
            if match:
                ts = f"{match.group(1)}_{match.group(2)}"
            else:
                ts = filename

            if ts not in groups:
                groups[ts] = []
            groups[ts].append(path)

        return list(groups.values())

    @property
    def satellite_variant(self) -> str:
        """Get the satellite variant."""
        return "FY3D"

    def __repr__(self) -> str:
        return f"FengYun3DDriver(satellite=FY3D, sensor=MERSI, level=L1, bands={len(self._dataset_map)})"
