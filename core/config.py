"""
Satellite Configuration Module

Centralized configuration for band mappings, calibration coefficients,
and satellite-specific settings. Provides standardized access to
satellite data parameters.
"""
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass


class SpectralRegion(Enum):
    """Enumeration of spectral regions."""
    VISIBLE = "visible"
    NEAR_INFRARED = "nir"
    SHORTWAVE_INFRARED = "swir"
    THERMAL_INFRARED = "tir"
    MID_INFRARED = "mir"
    WATER_VAPOR = "wv"
    UNKNOWN = "unknown"


@dataclass
class BandConfig:
    """Configuration for a spectral band."""
    canonical_name: str           # Standard name (e.g., 'VIS006')
    satellite_specific: Dict[str, str]  # {satellite: specific_name}
    wavelength: str              # Wavelength string (e.g., '0.47 μm')
    wavelength_um: float         # Wavelength in micrometers
    spectral_region: SpectralRegion
    resolution: str              # Spatial resolution (e.g., '500M')
    bit_depth: int = 16
    is_thermal: bool = False
    is_visible: bool = False


# =============================================================================
# Standardized Band Catalog
# =============================================================================

# All supported bands across different satellites
BAND_CATALOG: Dict[str, BandConfig] = {
    # Visible Bands
    'VIS006': BandConfig(
        canonical_name='VIS006',
        satellite_specific={
            'FY4A': 'Channel01',
            'FY4B': 'Channel01',
            'H08': 'B01',
            'H09': 'B01',
        },
        wavelength='0.47 μm',
        wavelength_um=0.47,
        spectral_region=SpectralRegion.VISIBLE,
        resolution='500M',
        is_visible=True
    ),
    'VIS008': BandConfig(
        canonical_name='VIS008',
        satellite_specific={
            'FY4A': 'Channel02',
            'FY4B': 'Channel02',
            'H08': 'B02',
            'H09': 'B02',
        },
        wavelength='0.51 μm',
        wavelength_um=0.51,
        spectral_region=SpectralRegion.VISIBLE,
        resolution='500M',
        is_visible=True
    ),
    'RED': BandConfig(
        canonical_name='RED',
        satellite_specific={
            'FY4A': 'Channel03',
            'FY4B': 'Channel03',
            'H08': 'B03',
            'H09': 'B03',
        },
        wavelength='0.64 μm',
        wavelength_um=0.64,
        spectral_region=SpectralRegion.VISIBLE,
        resolution='1000M',
        is_visible=True
    ),
    'NIR016': BandConfig(
        canonical_name='NIR016',
        satellite_specific={
            'FY4A': 'Channel04',
            'FY4B': 'Channel04',
            'H08': 'B04',
            'H09': 'B04',
        },
        wavelength='0.86 μm',
        wavelength_um=0.86,
        spectral_region=SpectralRegion.NEAR_INFRARED,
        resolution='1000M',
        is_visible=True
    ),

    # Shortwave Infrared
    'SWIR16': BandConfig(
        canonical_name='SWIR16',
        satellite_specific={
            'FY4A': 'Channel05',
            'FY4B': 'Channel05',
            'H08': 'B05',
            'H09': 'B05',
        },
        wavelength='1.61 μm',
        wavelength_um=1.61,
        spectral_region=SpectralRegion.SHORTWAVE_INFRARED,
        resolution='2000M'
    ),
    'SWIR22': BandConfig(
        canonical_name='SWIR22',
        satellite_specific={
            'FY4A': 'Channel06',
            'FY4B': 'Channel06',
            'H08': 'B06',
            'H09': 'B06',
        },
        wavelength='2.25 μm',
        wavelength_um=2.25,
        spectral_region=SpectralRegion.SHORTWAVE_INFRARED,
        resolution='4000M'
    ),

    # Mid Infrared / Thermal
    'IR039': BandConfig(
        canonical_name='IR039',
        satellite_specific={
            'FY4A': 'Channel07',
            'FY4B': 'Channel07',
            'H08': 'B07',
            'H09': 'B07',
        },
        wavelength='3.75 μm',
        wavelength_um=3.75,
        spectral_region=SpectralRegion.MID_INFRARED,
        resolution='2000M',
        is_thermal=True
    ),

    # Water Vapor Bands
    'WV062': BandConfig(
        canonical_name='WV062',
        satellite_specific={
            'FY4A': 'Channel08',
            'FY4B': 'Channel08',
            'H08': 'B08',
            'H09': 'B08',
        },
        wavelength='6.20 μm',
        wavelength_um=6.20,
        spectral_region=SpectralRegion.WATER_VAPOR,
        resolution='4000M',
        is_thermal=True
    ),
    'WV070': BandConfig(
        canonical_name='WV070',
        satellite_specific={
            'FY4A': 'Channel09',
            'FY4B': 'Channel09',
            'H08': 'B09',
            'H09': 'B09',
        },
        wavelength='6.90 μm',
        wavelength_um=6.90,
        spectral_region=SpectralRegion.WATER_VAPOR,
        resolution='4000M',
        is_thermal=True
    ),
    'WV073': BandConfig(
        canonical_name='WV073',
        satellite_specific={
            'FY4A': 'Channel10',
            'FY4B': 'Channel10',
            'H08': 'B10',
            'H09': 'B10',
        },
        wavelength='7.30 μm',
        wavelength_um=7.30,
        spectral_region=SpectralRegion.WATER_VAPOR,
        resolution='4000M',
        is_thermal=True
    ),

    # Thermal Infrared Bands
    'IR086': BandConfig(
        canonical_name='IR086',
        satellite_specific={
            'FY4A': 'Channel11',
            'FY4B': 'Channel11',
            'H08': 'B11',
            'H09': 'B11',
        },
        wavelength='8.60 μm',
        wavelength_um=8.60,
        spectral_region=SpectralRegion.THERMAL_INFRARED,
        resolution='4000M',
        is_thermal=True
    ),
    'IR096': BandConfig(
        canonical_name='IR096',
        satellite_specific={
            'FY4A': 'Channel12',
            'FY4B': 'Channel12',
            'H08': 'B12',
            'H09': 'B12',
        },
        wavelength='9.60 μm',
        wavelength_um=9.60,
        spectral_region=SpectralRegion.THERMAL_INFRARED,
        resolution='4000M',
        is_thermal=True
    ),
    'IR105': BandConfig(
        canonical_name='IR105',
        satellite_specific={
            'FY4A': 'Channel13',
            'FY4B': 'Channel13',
            'H08': 'B13',
            'H09': 'B13',
        },
        wavelength='10.4 μm',
        wavelength_um=10.4,
        spectral_region=SpectralRegion.THERMAL_INFRARED,
        resolution='4000M',
        is_thermal=True
    ),
    'IR112': BandConfig(
        canonical_name='IR112',
        satellite_specific={
            'FY4A': 'Channel14',
            'FY4B': 'Channel14',
            'H08': 'B14',
            'H09': 'B14',
        },
        wavelength='11.2 μm',
        wavelength_um=11.2,
        spectral_region=SpectralRegion.THERMAL_INFRARED,
        resolution='4000M',
        is_thermal=True
    ),
    'IR123': BandConfig(
        canonical_name='IR123',
        satellite_specific={
            'FY4A': 'Channel15',
            'FY4B': 'Channel15',
            'H08': 'B15',
            'H09': 'B15',
        },
        wavelength='12.3 μm',
        wavelength_um=12.3,
        spectral_region=SpectralRegion.THERMAL_INFRARED,
        resolution='4000M',
        is_thermal=True
    ),
}


# =============================================================================
# Satellite Configuration
# =============================================================================

SATELLITE_CONFIG: Dict[str, Dict[str, Any]] = {
    'FY4A': {
        'name': 'Fengyun-4A',
        'sensor': 'AGRI',
        'lon_0': 99.5,
        'sweep_axis': 'Y',
        'coverage': {'west': 70, 'east': 140, 'south': -50, 'north': 50},
        'resolution_bands': {
            'VIS': '1000M',
            'NIR': '1000M',
            'SWIR': '2000M',
            'TIR': '4000M',
        },
    },
    'FY4B': {
        'name': 'Fengyun-4B',
        'sensor': 'AGRI',
        'lon_0': 105.0,
        'sweep_axis': 'Y',
        'coverage': {'west': 75, 'east': 135, 'south': -55, 'north': 55},
        'resolution_bands': {
            'VIS': '1000M',
            'NIR': '1000M',
            'SWIR': '2000M',
            'TIR': '4000M',
        },
    },
    'H08': {
        'name': 'Himawari-8',
        'sensor': 'AHI',
        'lon_0': 140.7,
        'sweep_axis': 'Y',
        'coverage': {'west': 80, 'east': 160, 'south': -60, 'north': 60},
        'resolution_bands': {
            'VIS': '500M',
            'NIR': '1000M',
            'SWIR': '2000M',
            'TIR': '2000M',
        },
    },
    'H09': {
        'name': 'Himawari-9',
        'sensor': 'AHI',
        'lon_0': 140.7,
        'sweep_axis': 'Y',
        'coverage': {'west': 80, 'east': 160, 'south': -60, 'north': 60},
        'resolution_bands': {
            'VIS': '500M',
            'NIR': '1000M',
            'SWIR': '2000M',
            'TIR': '2000M',
        },
    },
}


# =============================================================================
# Calibration Configuration
# =============================================================================

# Calibration coefficients (simplified)
CALIBRATION_CONFIG: Dict[str, Dict[str, Dict]] = {
    'FY4A': {
        'AGRI': {
            'VIS006': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'VIS008': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'RED': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'NIR016': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'SWIR16': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'SWIR22': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'IR039': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV062': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV070': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV073': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR086': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR096': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR105': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR112': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR123': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
        }
    },
    'FY4B': {
        'AGRI': {
            # Same as FY4A for now
        }
    },
    'H08': {
        'AHI': {
            'VIS006': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'VIS008': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'RED': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'NIR016': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'SWIR16': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'SWIR22': {'a': 0.0, 'b': 0.000025, 'type': 'reflectance'},
            'IR039': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV062': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV070': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'WV073': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR086': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR096': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR105': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR112': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
            'IR123': {'a': 0.0, 'b': 0.000025, 'type': 'brightness_temp'},
        }
    },
}


# =============================================================================
# L2 Product Configuration
# =============================================================================

L2_PRODUCT_CONFIG: Dict[str, Dict[str, Any]] = {
    'CLM': {
        'name': 'Cloud Mask',
        'satellites': ['FY4B'],
        'resolution': '4000M',
        'unit': 'binary',
    },
    'FOG': {
        'name': 'Fog Detection',
        'satellites': ['FY4B'],
        'resolution': '4000M',
        'unit': 'binary',
    },
    'CWP': {
        'name': 'Cloud Water Path',
        'satellites': ['FY4B'],
        'resolution': '4000M',
        'unit': 'g/m²',
    },
    'CTT': {
        'name': 'Cloud Top Temperature',
        'satellites': ['FY4B'],
        'resolution': '4000M',
        'unit': 'K',
    },
    'CTP': {
        'name': 'Cloud Top Pressure',
        'satellites': ['FY4B'],
        'resolution': '4000M',
        'unit': 'hPa',
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_band_config(canonical_name: str) -> Optional[BandConfig]:
    """Get band configuration by canonical name."""
    return BAND_CATALOG.get(canonical_name)


def get_satellite_config(satellite_id: str) -> Optional[Dict[str, Any]]:
    """Get satellite configuration."""
    return SATELLITE_CONFIG.get(satellite_id.upper())


def map_canonical_to_satellite(canonical_name: str, satellite_id: str) -> str:
    """
    Map canonical band name to satellite-specific name.

    Args:
        canonical_name: Standard band name
        satellite_id: Satellite identifier (e.g., 'FY4A', 'H08')

    Returns:
        Satellite-specific band name
    """
    band_config = get_band_config(canonical_name)
    if band_config is None:
        return canonical_name

    sat_id = satellite_id.upper()
    return band_config.satellite_specific.get(sat_id, canonical_name)


def map_satellite_to_canonical(specific_name: str, satellite_id: str) -> str:
    """
    Map satellite-specific band name to canonical name.

    Args:
        specific_name: Satellite-specific band name
        satellite_id: Satellite identifier

    Returns:
        Canonical band name
    """
    sat_id = satellite_id.upper()

    for canonical, config in BAND_CATALOG.items():
        if config.satellite_specific.get(sat_id) == specific_name:
            return canonical

    # Try channel number pattern for FY4A
    import re
    match = re.match(r'Channel(\d{2})', specific_name, re.IGNORECASE)
    if match:
        channel_map = {
            1: 'VIS006', 2: 'VIS008', 3: 'RED', 4: 'NIR016',
            5: 'SWIR16', 6: 'SWIR22', 7: 'IR039', 8: 'WV062',
            9: 'WV070', 10: 'WV073', 11: 'IR086', 12: 'IR096',
            13: 'IR105', 14: 'IR112', 15: 'IR123',
        }
        num = int(match.group(1))
        return channel_map.get(num, specific_name)

    # Try B## pattern for Himawari
    match = re.match(r'B(\d{2})', specific_name, re.IGNORECASE)
    if match:
        band_map = {
            1: 'VIS006', 2: 'VIS008', 3: 'RED', 4: 'NIR016',
            5: 'SWIR16', 6: 'SWIR22', 7: 'IR039', 8: 'WV062',
            9: 'WV070', 10: 'WV073', 11: 'IR086', 12: 'IR096',
            13: 'IR105', 14: 'IR112', 15: 'IR123',
        }
        num = int(match.group(1))
        return band_map.get(num, specific_name)

    return specific_name


def get_calibration_coeffs(satellite_id: str, sensor: str,
                            canonical_name: str) -> Dict[str, float]:
    """Get calibration coefficients for a band."""
    sat_config = CALIBRATION_CONFIG.get(satellite_id.upper(), {})
    sensor_config = sat_config.get(sensor, {})

    band_config = sensor_config.get(canonical_name, {'a': 0.0, 'b': 0.000025})

    return {
        'a': band_config.get('a', 0.0),
        'b': band_config.get('b', 0.000025),
    }


def get_available_bands_for_satellite(satellite_id: str) -> List[str]:
    """Get list of canonical band names available for a satellite."""
    sat_id = satellite_id.upper()
    available = []

    for canonical, config in BAND_CATALOG.items():
        if sat_id in config.satellite_specific:
            available.append(canonical)

    return available


def get_satellite_coverage(satellite_id: str) -> Optional[Tuple[float, float, float, float]]:
    """Get geographic coverage for a satellite."""
    config = SATELLITE_CONFIG.get(satellite_id.upper())
    if config is None:
        return None

    cov = config.get('coverage', {})
    return (cov.get('west', -180), cov.get('east', 180),
            cov.get('south', -90), cov.get('north', 90))


def get_all_satellites() -> List[str]:
    """Get list of all configured satellite IDs."""
    return list(SATELLITE_CONFIG.keys())


def get_band_display_name(canonical_name: str, satellite_id: Optional[str] = None) -> str:
    """
    Get human-readable display name for a band.

    Args:
        canonical_name: Standard band name
        satellite_id: Optional satellite ID for context

    Returns:
        Display name string
    """
    config = get_band_config(canonical_name)
    if config is None:
        return canonical_name

    wavelength = config.wavelength or ''
    region = config.spectral_region.value.upper() if config.spectral_region else ''

    return f"{canonical_name} ({wavelength}) [{region}]"


# =============================================================================
# Satellite-Specific Band Maps
#
# Single source of truth for satellite-native dataset names.
# Each driver imports from here instead of maintaining its own inline dict.
# Format per band entry: {'name': <native_name>, 'wavelength': <str>, 'resolution': <str>}
#
# Usage:
#   from core.config import get_satellite_band_map, get_thermal_bands
#   bands = get_satellite_band_map('AGRI_L1')  # Returns dict of band configs
#   thermal = get_thermal_bands('MERSI_L1')    # Returns set of thermal band names
# =============================================================================

SATELLITE_BAND_MAPS: Dict[str, Dict[str, Dict]] = {
    # FY-4A / FY-4B  (AGRI sensor, L1 data)
    # Direct FY4Reader exposes channel IDs as 'C01'~'C14' (FY-4A baseline)
    # FY-4B additionally has 'C15' (14.3 μm CO2-slicing band)
    'AGRI_L1': {
        'VIS006': {'name': 'C01', 'wavelength': '0.47 μm', 'resolution': '1000M', 'type': 'visible'},
        'VIS008': {'name': 'C02', 'wavelength': '0.51 μm', 'resolution': '1000M', 'type': 'visible'},
        'RED':    {'name': 'C03', 'wavelength': '0.65 μm', 'resolution': '1000M', 'type': 'visible'},
        'NIR016': {'name': 'C04', 'wavelength': '0.83 μm', 'resolution': '1000M', 'type': 'visible'},
        'SWIR16': {'name': 'C05', 'wavelength': '1.61 μm', 'resolution': '2000M', 'type': 'swir'},
        'SWIR22': {'name': 'C06', 'wavelength': '2.25 μm', 'resolution': '4000M', 'type': 'swir'},
        'IR039':  {'name': 'C07', 'wavelength': '3.75 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR062':  {'name': 'C08', 'wavelength': '6.25 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR072':  {'name': 'C09', 'wavelength': '7.10 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR086':  {'name': 'C10', 'wavelength': '8.50 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR096':  {'name': 'C11', 'wavelength': '9.70 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR105':  {'name': 'C12', 'wavelength': '10.8 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR112':  {'name': 'C13', 'wavelength': '12.0 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR133':  {'name': 'C14', 'wavelength': '13.5 μm', 'resolution': '4000M', 'type': 'thermal'},
        'BT136':  {'name': 'C15', 'wavelength': '14.3 μm', 'resolution': '4000M', 'type': 'thermal'},  # FY-4B only
    },

    # Himawari-8 / Himawari-9  (AHI sensor)
    'AHI': {
        'VIS006': {'name': 'B01', 'wavelength': '0.47 μm', 'resolution': '500M',  'type': 'visible'},
        'VIS008': {'name': 'B02', 'wavelength': '0.51 μm', 'resolution': '500M',  'type': 'visible'},
        'RED':    {'name': 'B03', 'wavelength': '0.64 μm', 'resolution': '1000M', 'type': 'visible'},
        'NIR016': {'name': 'B04', 'wavelength': '0.86 μm', 'resolution': '1000M', 'type': 'visible'},
        'SWIR16': {'name': 'B05', 'wavelength': '1.60 μm', 'resolution': '2000M', 'type': 'swir'},
        'SWIR22': {'name': 'B06', 'wavelength': '2.30 μm', 'resolution': '2000M', 'type': 'swir'},
        'IR039':  {'name': 'B07', 'wavelength': '3.90 μm', 'resolution': '2000M', 'type': 'thermal'},
        'WV062':  {'name': 'B08', 'wavelength': '6.20 μm', 'resolution': '4000M', 'type': 'wv'},
        'WV070':  {'name': 'B09', 'wavelength': '6.90 μm', 'resolution': '4000M', 'type': 'wv'},
        'WV073':  {'name': 'B10', 'wavelength': '7.30 μm', 'resolution': '4000M', 'type': 'wv'},
        'IR086':  {'name': 'B11', 'wavelength': '8.60 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR096':  {'name': 'B12', 'wavelength': '9.60 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR105':  {'name': 'B13', 'wavelength': '10.4 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR112':  {'name': 'B14', 'wavelength': '11.2 μm', 'resolution': '4000M', 'type': 'thermal'},
        'IR123':  {'name': 'B15', 'wavelength': '12.3 μm', 'resolution': '4000M', 'type': 'thermal'},
    },

    # FY-3D  (MERSI-2 sensor, L1 data via direct FY3DReader)
    # Dataset names are normalized to canonical IDs 'B01'~'B25'
    # Band grouping per official MERSI-2 spec:
    #   B01~B04: 250m reflective (RefSB)
    #   B05~B07: 1000m SWIR reflective
    #   B08~B19: 1000m visible/NIR/ocean-color reflective
    #   B20~B25: 1000m thermal emissive (Emissive01~06)
    'MERSI_L1': {
        'B01': {'name': '1',  'wavelength': '0.47 μm', 'resolution': '250M',  'type': 'visible'},
        'B02': {'name': '2',  'wavelength': '0.55 μm', 'resolution': '250M',  'type': 'visible'},
        'B03': {'name': '3',  'wavelength': '0.65 μm', 'resolution': '250M',  'type': 'visible'},
        'B04': {'name': '4',  'wavelength': '0.87 μm', 'resolution': '250M',  'type': 'visible'},
        'B05': {'name': '5',  'wavelength': '1.38 μm', 'resolution': '1000M', 'type': 'swir'},
        'B06': {'name': '6',  'wavelength': '1.64 μm', 'resolution': '1000M', 'type': 'swir'},
        'B07': {'name': '7',  'wavelength': '2.25 μm', 'resolution': '1000M', 'type': 'swir'},
        'B08': {'name': '8',  'wavelength': '0.41 μm', 'resolution': '1000M', 'type': 'ocean'},
        'B09': {'name': '9',  'wavelength': '0.44 μm', 'resolution': '1000M', 'type': 'ocean'},
        'B10': {'name': '10', 'wavelength': '0.49 μm', 'resolution': '1000M', 'type': 'ocean'},
        'B11': {'name': '11', 'wavelength': '0.52 μm', 'resolution': '1000M', 'type': 'ocean'},
        'B12': {'name': '12', 'wavelength': '0.565 μm','resolution': '1000M', 'type': 'ocean'},
        'B13': {'name': '13', 'wavelength': '0.65 μm', 'resolution': '1000M', 'type': 'ocean'},
        'B14': {'name': '14', 'wavelength': '0.685 μm','resolution': '1000M', 'type': 'ocean'},
        'B15': {'name': '15', 'wavelength': '0.765 μm','resolution': '1000M', 'type': 'ocean'},
        'B16': {'name': '16', 'wavelength': '0.865 μm','resolution': '1000M', 'type': 'visible'},
        'B17': {'name': '17', 'wavelength': '0.905 μm','resolution': '1000M', 'type': 'visible'},
        'B18': {'name': '18', 'wavelength': '0.936 μm','resolution': '1000M', 'type': 'visible'},
        'B19': {'name': '19', 'wavelength': '1.030 μm','resolution': '1000M', 'type': 'visible'},
        'B20': {'name': '20', 'wavelength': '3.80 μm', 'resolution': '1000M', 'type': 'thermal'},
        'B21': {'name': '21', 'wavelength': '4.05 μm', 'resolution': '1000M', 'type': 'thermal'},
        'B22': {'name': '22', 'wavelength': '7.20 μm', 'resolution': '1000M', 'type': 'thermal'},
        'B23': {'name': '23', 'wavelength': '8.55 μm', 'resolution': '1000M', 'type': 'thermal'},
        'B24': {'name': '24', 'wavelength': '10.80 μm','resolution': '1000M', 'type': 'thermal'},
        'B25': {'name': '25', 'wavelength': '12.00 μm','resolution': '1000M', 'type': 'thermal'},
    },
}


# Helper: thermal band sets per sensor (used by drivers for BT conversion)
THERMAL_BAND_SETS: Dict[str, set] = {
    'AGRI_L1': {'IR039', 'IR062', 'IR072', 'IR086', 'IR096', 'IR105', 'IR112', 'IR133', 'BT136', 'CO2'},
    'AHI':     {'IR039', 'WV062', 'WV070', 'WV073', 'IR086', 'IR096', 'IR105', 'IR112', 'IR123'},
    'MERSI_L1': {'B20', 'B21', 'B22', 'B23', 'B24', 'B25'},
}


def get_satellite_band_map(sensor_key: str) -> Dict[str, Dict]:
    """Return the satellite-specific band map for a given sensor key."""
    return SATELLITE_BAND_MAPS.get(sensor_key, {})


def get_thermal_bands(sensor_key: str) -> set:
    """Return the set of canonical thermal band names for a sensor."""
    return THERMAL_BAND_SETS.get(sensor_key, set())


# =============================================================================
# Projection Grid Shape Presets
# Used by main_window.py and canvas.py to identify the projection of an image
# by its pixel dimensions, avoiding hardcoded magic numbers in the UI layer.
# =============================================================================

PROJECTION_GRID_SHAPES: dict = {
    # (width, height) -> projection_id
    (3600, 1800): 'plate_carree_global',   # 0.1° global grid
    (360,  180):  'plate_carree_global',   # 1.0° global grid (low-res preview)
    (1240, 700):  'plate_carree_china',    # ~0.06° China region (70–142°E, 15–55°N)
}

# Canonical extent tuples (west, east, south, north) for each preset grid
PROJECTION_GRID_EXTENTS: dict = {
    'plate_carree_global': (-180.0, 180.0, -90.0,  90.0),
    'plate_carree_china':  ( 70.0,  142.0,  15.0,  55.0),
}

