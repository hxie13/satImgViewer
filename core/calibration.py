"""
Radiometric calibration utilities for satellite imagery.
Supports calibration of Fengyun and Himawari satellite data.
"""
import numpy as np
import h5py
import os
import datetime
from typing import Dict, Optional, Tuple, Union, List

class Calibration:
    """
    Radiometric calibration class for satellite imagery.
    Handles conversion from digital numbers to physical units.
    """
    
    # Calibration coefficients for different satellites and sensors
    CALIBRATION_COEFFICIENTS = {
        'FY4A': {
            'AGRI': {
                'B01': {'a': 0.0, 'b': 0.000025},
                'B02': {'a': 0.0, 'b': 0.000025},
                'B03': {'a': 0.0, 'b': 0.000025},
                'B04': {'a': 0.0, 'b': 0.000025},
                'B05': {'a': 0.0, 'b': 0.000025},
                'B06': {'a': -0.1, 'b': 0.000025},
                'B07': {'a': 0.0, 'b': 0.000025},
                'B08': {'a': 0.0, 'b': 0.000025},
                'B09': {'a': 0.0, 'b': 0.000025},
                'B10': {'a': 0.0, 'b': 0.000025},
                'B11': {'a': 0.0, 'b': 0.000025},
                'B12': {'a': 0.0, 'b': 0.000025},
                'B13': {'a': 0.0, 'b': 0.000025},
                'B14': {'a': 0.0, 'b': 0.000025},
                'B15': {'a': 0.0, 'b': 0.000025}
            }
        },
        'FY4B': {
            'AGRI': {
                'B01': {'a': 0.0, 'b': 0.000025},
                'B02': {'a': 0.0, 'b': 0.000025},
                'B03': {'a': 0.0, 'b': 0.000025},
                'B04': {'a': 0.0, 'b': 0.000025},
                'B05': {'a': 0.0, 'b': 0.000025},
                'B06': {'a': -0.1, 'b': 0.000025},
                'B07': {'a': 0.0, 'b': 0.000025},
                'B08': {'a': 0.0, 'b': 0.000025},
                'B09': {'a': 0.0, 'b': 0.000025},
                'B10': {'a': 0.0, 'b': 0.000025},
                'B11': {'a': 0.0, 'b': 0.000025},
                'B12': {'a': 0.0, 'b': 0.000025},
                'B13': {'a': 0.0, 'b': 0.000025},
                'B14': {'a': 0.0, 'b': 0.000025},
                'B15': {'a': 0.0, 'b': 0.000025}
            }
        },
        'Himawari-8': {
            'AHI': {
                'B01': {'a': 0.0, 'b': 0.000025},
                'B02': {'a': 0.0, 'b': 0.000025},
                'B03': {'a': 0.0, 'b': 0.000025},
                'B04': {'a': 0.0, 'b': 0.000025},
                'B05': {'a': 0.0, 'b': 0.000025},
                'B06': {'a': 0.0, 'b': 0.000025},
                'B07': {'a': 0.0, 'b': 0.000025},
                'B08': {'a': 0.0, 'b': 0.000025},
                'B09': {'a': 0.0, 'b': 0.000025},
                'B10': {'a': 0.0, 'b': 0.000025},
                'B11': {'a': 0.0, 'b': 0.000025},
                'B12': {'a': 0.0, 'b': 0.000025},
                'B13': {'a': 0.0, 'b': 0.000025},
                'B14': {'a': 0.0, 'b': 0.000025},
                'B15': {'a': 0.0, 'b': 0.000025}
            }
        }
    }
    
    # Thermal infrared bands that require brightness temperature conversion
    THERMAL_BANDS = {
        'FY4A': ['B06', 'B07', 'B08', 'B09', 'B10', 'B11', 'B12', 'B13', 'B14', 'B15'],
        'FY4B': ['B06', 'B07', 'B08', 'B09', 'B10', 'B11', 'B12', 'B13', 'B14', 'B15'],
        'Himawari-8': ['B07', 'B08', 'B09', 'B10', 'B11', 'B12', 'B13', 'B14', 'B15']
    }
    
    @staticmethod
    def get_calibration_coefficients(satellite: str, sensor: str, band: str) -> Dict[str, float]:
        """
        Get calibration coefficients for a specific satellite, sensor, and band.
        
        Args:
            satellite: Satellite name (e.g., 'FY4A', 'FY4B', 'Himawari-8')
            sensor: Sensor name (e.g., 'AGRI', 'AHI')
            band: Band name (e.g., 'B01', 'B02')
            
        Returns:
            Dictionary with 'a' and 'b' coefficients
        """
        try:
            return Calibration.CALIBRATION_COEFFICIENTS[satellite][sensor][band]
        except KeyError:
            # Return default coefficients if specific ones not found
            return {'a': 0.0, 'b': 0.000025}
    
    @staticmethod
    def is_thermal_band(satellite: str, band: str) -> bool:
        """
        Check if a band is a thermal infrared band.
        
        Args:
            satellite: Satellite name
            band: Band name
            
        Returns:
            True if the band is thermal infrared
        """
        try:
            return band in Calibration.THERMAL_BANDS[satellite]
        except KeyError:
            return False
    
    @staticmethod
    def calibrate_radiance(data: np.ndarray, a: float, b: float) -> np.ndarray:
        """
        Calibrate digital numbers to radiance.
        
        Args:
            data: Digital numbers array
            a: Offset coefficient
            b: Slope coefficient
            
        Returns:
            Radiance array
        """
        return a + b * data
    
    @staticmethod
    def calibrate_reflectance(data: np.ndarray, a: float, b: float, solar_zenith: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Calibrate digital numbers to reflectance.
        
        Args:
            data: Digital numbers array
            a: Offset coefficient
            b: Slope coefficient
            solar_zenith: Solar zenith angle in radians (optional)
            
        Returns:
            Reflectance array (0-1)
        """
        radiance = Calibration.calibrate_radiance(data, a, b)
        
        # Apply solar zenith correction if provided
        if solar_zenith is not None:
            cos_sza = np.cos(solar_zenith)
            cos_sza[cos_sza < 0.05] = 0.05  # Avoid division by zero
            radiance /= cos_sza
        
        # Convert to reflectance (simplified)
        reflectance = radiance * np.pi / 1367.0  # Solar constant ~1367 W/m²
        return np.clip(reflectance, 0, 1)
    
    @staticmethod
    def calibrate_brightness_temperature(data: np.ndarray, a: float, b: float, band: str) -> np.ndarray:
        """
        Calibrate digital numbers to brightness temperature.
        
        Args:
            data: Digital numbers array
            a: Offset coefficient
            b: Slope coefficient
            band: Band name
            
        Returns:
            Brightness temperature array in Kelvin
        """
        radiance = Calibration.calibrate_radiance(data, a, b)
        
        # Convert radiance to brightness temperature using Planck's law
        # Simplified using band-specific coefficients
        band_bt_coeffs = {
            'B06': {'K1': 774.89, 'K2': 1321.08},
            'B07': {'K1': 480.89, 'K2': 1201.14},
            'B08': {'K1': 373.15, 'K2': 1167.79},
            'B09': {'K1': 290.73, 'K2': 1128.86},
            'B10': {'K1': 229.73, 'K2': 1089.77},
            'B11': {'K1': 180.89, 'K2': 1046.47},
            'B12': {'K1': 142.89, 'K2': 1003.17},
            'B13': {'K1': 113.89, 'K2': 962.93},
            'B14': {'K1': 91.89, 'K2': 926.71},
            'B15': {'K1': 74.89, 'K2': 894.51}
        }
        
        coeffs = band_bt_coeffs.get(band, {'K1': 100.0, 'K2': 1000.0})
        K1, K2 = coeffs['K1'], coeffs['K2']
        
        # Avoid division by zero
        radiance[radiance <= 0] = 1e-6
        
        # Planck's law inversion
        bt = K2 / np.log((K1 / radiance) + 1)
        return bt
    
    @staticmethod
    def calibrate_data(data: np.ndarray, satellite: str, sensor: str, band: str, 
                      solar_zenith: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Calibrate data based on satellite, sensor, and band type.
        
        Args:
            data: Digital numbers array
            satellite: Satellite name
            sensor: Sensor name
            band: Band name
            solar_zenith: Solar zenith angle in radians (optional)
            
        Returns:
            Calibrated data array
        """
        coeffs = Calibration.get_calibration_coefficients(satellite, sensor, band)
        a, b = coeffs['a'], coeffs['b']
        
        if Calibration.is_thermal_band(satellite, band):
            # Thermal bands: convert to brightness temperature
            return Calibration.calibrate_brightness_temperature(data, a, b, band)
        else:
            # Reflective bands: convert to reflectance
            return Calibration.calibrate_reflectance(data, a, b, solar_zenith)
    
    @staticmethod
    def get_satellite_from_filename(filename: str) -> str:
        """
        Determine satellite from filename.
        
        Args:
            filename: Filename to analyze
            
        Returns:
            Satellite name
        """
        filename_upper = filename.upper()
        
        if 'FY4A' in filename_upper:
            return 'FY4A'
        elif 'FY4B' in filename_upper:
            return 'FY4B'
        elif 'H08' in filename_upper or 'HIMAWARI' in filename_upper:
            return 'Himawari-8'
        else:
            return 'FY4A'  # Default
    
    @staticmethod
    def get_sensor_from_satellite(satellite: str) -> str:
        """
        Get sensor name from satellite.
        
        Args:
            satellite: Satellite name
            
        Returns:
            Sensor name
        """
        sensor_map = {
            'FY4A': 'AGRI',
            'FY4B': 'AGRI',
            'Himawari-8': 'AHI'
        }
        return sensor_map.get(satellite, 'AGRI')

class GLTCorrection:
    """
    Geometric correction using GLT (Geolocation Lookup Table).
    Enhanced implementation for Fengyun satellites.
    """
    
    @staticmethod
    def create_glt(lons: np.ndarray, lats: np.ndarray, 
                  output_shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create GLT arrays from longitude and latitude arrays.
        
        Args:
            lons: Longitude array
            lats: Latitude array
            output_shape: Output shape (height, width)
            
        Returns:
            Tuple of (GLT_x, GLT_y) arrays
        """
        height, width = output_shape
        
        # Create regular grid
        lon_min, lon_max = lons.min(), lons.max()
        lat_min, lat_max = lats.min(), lats.max()
        
        # Create output grid
        lon_grid, lat_grid = np.meshgrid(
            np.linspace(lon_min, lon_max, width),
            np.linspace(lat_min, lat_max, height)
        )
        
        # Vectorized nearest neighbor lookup (more efficient)
        glt_x = np.zeros(output_shape, dtype=np.float32)
        glt_y = np.zeros(output_shape, dtype=np.float32)
        
        # Reshape lons and lats for broadcasting
        lons_2d = lons.reshape(-1, 1, 1)
        lats_2d = lats.reshape(-1, 1, 1)
        
        # Calculate distance for each grid point
        for i in range(height):
            for j in range(width):
                lon = lon_grid[i, j]
                lat = lat_grid[i, j]
                
                # Calculate distance to all pixels
                distance = np.sqrt((lons - lon)**2 + (lats - lat)**2)
                min_idx = np.unravel_index(np.argmin(distance), lons.shape)
                
                glt_y[i, j] = min_idx[0] + 0.5  # +0.5 for center of pixel
                glt_x[i, j] = min_idx[1] + 0.5
        
        return glt_x, glt_y
    
    @staticmethod
    def apply_glt(data: np.ndarray, glt_x: np.ndarray, glt_y: np.ndarray) -> np.ndarray:
        """
        Apply GLT to data.
        
        Args:
            data: Input data array
            glt_x: GLT x array
            glt_y: GLT y array
            
        Returns:
            Geometrically corrected data
        """
        height, width = glt_x.shape
        output = np.zeros((height, width), dtype=data.dtype)
        
        # Clamp coordinates to valid range
        glt_x_clamped = np.clip(glt_x, 0, data.shape[1] - 1)
        glt_y_clamped = np.clip(glt_y, 0, data.shape[0] - 1)
        
        # Vectorized bilinear interpolation (more efficient)
        x0 = np.floor(glt_x_clamped).astype(int)
        x1 = np.minimum(x0 + 1, data.shape[1] - 1)
        y0 = np.floor(glt_y_clamped).astype(int)
        y1 = np.minimum(y0 + 1, data.shape[0] - 1)
        
        wx = glt_x_clamped - x0
        wy = glt_y_clamped - y0
        
        # Get values at the four surrounding points
        v00 = data[y0, x0]
        v01 = data[y0, x1]
        v10 = data[y1, x0]
        v11 = data[y1, x1]
        
        # Bilinear interpolation
        output = (
            v00 * (1 - wx) * (1 - wy) +
            v01 * wx * (1 - wy) +
            v10 * (1 - wx) * wy +
            v11 * wx * wy
        )
        
        return output
    
    @staticmethod
    def apply_glt_to_multiple_bands(bands_data: Dict[str, np.ndarray], 
                                   glt_x: np.ndarray, glt_y: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Apply GLT to multiple bands.
        
        Args:
            bands_data: Dictionary of band names to data arrays
            glt_x: GLT x array
            glt_y: GLT y array
            
        Returns:
            Dictionary of band names to corrected data arrays
        """
        corrected_bands = {}
        
        for band_name, data in bands_data.items():
            corrected_bands[band_name] = GLTCorrection.apply_glt(data, glt_x, glt_y)
        
        return corrected_bands
    
    @staticmethod
    def get_glt_from_satellite_parameters(satellite: str, resolution: str, 
                                         output_shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get GLT from satellite parameters.
        
        Args:
            satellite: Satellite name
            resolution: Resolution string
            output_shape: Output shape
            
        Returns:
            Tuple of (GLT_x, GLT_y) arrays
        """
        # Import here to avoid circular imports
        from .satellite_projection import latlon2linecolumn
        
        height, width = output_shape
        
        # Create regular grid
        if satellite in ['FY4A', 'FY4B']:
            # China region
            lon_min, lon_max = 73.0, 135.0
            lat_min, lat_max = 18.0, 53.0
        else:
            # Global
            lon_min, lon_max = -180.0, 180.0
            lat_min, lat_max = -90.0, 90.0
        
        # Create output grid
        lon_grid, lat_grid = np.meshgrid(
            np.linspace(lon_min, lon_max, width),
            np.linspace(lat_min, lat_max, height)
        )
        
        # Create GLT arrays
        glt_x = np.zeros(output_shape, dtype=np.float32)
        glt_y = np.zeros(output_shape, dtype=np.float32)
        
        # Fill GLT arrays
        for i in range(height):
            for j in range(width):
                lat = lat_grid[i, j]
                lon = lon_grid[i, j]
                
                # Convert lat/lon to line/column
                line, column = latlon2linecolumn(lat, lon, resolution, satellite)
                
                glt_y[i, j] = line + 0.5
                glt_x[i, j] = column + 0.5
        
        return glt_x, glt_y

class RegionCropper:
    """
    Crop regions from satellite imagery based on geographic coordinates.
    Enhanced implementation with predefined regions and batch processing.
    """
    
    # Predefined regions
    PREDEFINED_REGIONS = {
        'china': {
            'name': 'China',
            'min_lon': 73.0,
            'max_lon': 135.0,
            'min_lat': 18.0,
            'max_lat': 53.0
        },
        'east_asia': {
            'name': 'East Asia',
            'min_lon': 70.0,
            'max_lon': 150.0,
            'min_lat': 0.0,
            'max_lat': 60.0
        },
        'southeast_asia': {
            'name': 'Southeast Asia',
            'min_lon': 90.0,
            'max_lon': 140.0,
            'min_lat': -10.0,
            'max_lat': 25.0
        },
        'global': {
            'name': 'Global',
            'min_lon': -180.0,
            'max_lon': 180.0,
            'min_lat': -90.0,
            'max_lat': 90.0
        }
    }
    
    @staticmethod
    def crop_by_geographic_extent(data: np.ndarray, lons: np.ndarray, lats: np.ndarray, 
                                 min_lon: float, max_lon: float, 
                                 min_lat: float, max_lat: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Crop data by geographic extent.
        
        Args:
            data: Input data array
            lons: Longitude array
            lats: Latitude array
            min_lon: Minimum longitude
            max_lon: Maximum longitude
            min_lat: Minimum latitude
            max_lat: Maximum latitude
            
        Returns:
            Tuple of (cropped_data, cropped_lons, cropped_lats)
        """
        # Create mask for region of interest
        mask = (
            (lons >= min_lon) & (lons <= max_lon) &
            (lats >= min_lat) & (lats <= max_lat)
        )
        
        # Find bounding box
        rows, cols = np.where(mask)
        if len(rows) == 0:
            return data, lons, lats  # No data in region
        
        row_min, row_max = rows.min(), rows.max()
        col_min, col_max = cols.min(), cols.max()
        
        # Crop data
        cropped_data = data[row_min:row_max+1, col_min:col_max+1]
        cropped_lons = lons[row_min:row_max+1, col_min:col_max+1]
        cropped_lats = lats[row_min:row_max+1, col_min:col_max+1]
        
        return cropped_data, cropped_lons, cropped_lats
    
    @staticmethod
    def crop_by_predefined_region(data: np.ndarray, lons: np.ndarray, lats: np.ndarray, 
                                 region_name: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Crop data by predefined region name.
        
        Args:
            data: Input data array
            lons: Longitude array
            lats: Latitude array
            region_name: Predefined region name
            
        Returns:
            Tuple of (cropped_data, cropped_lons, cropped_lats)
        """
        if region_name not in RegionCropper.PREDEFINED_REGIONS:
            region_name = 'china'  # Default to China
        
        region = RegionCropper.PREDEFINED_REGIONS[region_name]
        return RegionCropper.crop_by_geographic_extent(
            data, lons, lats,
            region['min_lon'], region['max_lon'],
            region['min_lat'], region['max_lat']
        )
    
    @staticmethod
    def crop_multiple_bands(bands_data: Dict[str, np.ndarray], lons: np.ndarray, lats: np.ndarray, 
                          min_lon: float, max_lon: float, 
                          min_lat: float, max_lat: float) -> Dict[str, np.ndarray]:
        """
        Crop multiple bands by geographic extent.
        
        Args:
            bands_data: Dictionary of band names to data arrays
            lons: Longitude array
            lats: Latitude array
            min_lon: Minimum longitude
            max_lon: Maximum longitude
            min_lat: Minimum latitude
            max_lat: Maximum latitude
            
        Returns:
            Dictionary of band names to cropped data arrays
        """
        # Crop first band to get the mask
        first_band = next(iter(bands_data.values()))
        _, cropped_lons, cropped_lats = RegionCropper.crop_by_geographic_extent(
            first_band, lons, lats, min_lon, max_lon, min_lat, max_lat
        )
        
        # Create mask for region of interest
        mask = (
            (lons >= min_lon) & (lons <= max_lon) &
            (lats >= min_lat) & (lats <= max_lat)
        )
        
        # Find bounding box
        rows, cols = np.where(mask)
        if len(rows) == 0:
            return bands_data  # No data in region
        
        row_min, row_max = rows.min(), rows.max()
        col_min, col_max = cols.min(), cols.max()
        
        # Crop all bands
        cropped_bands = {}
        for band_name, data in bands_data.items():
            cropped_bands[band_name] = data[row_min:row_max+1, col_min:col_max+1]
        
        return cropped_bands
    
    @staticmethod
    def get_china_extent() -> Dict[str, float]:
        """
        Get geographic extent of China.
        
        Returns:
            Dictionary with min_lon, max_lon, min_lat, max_lat
        """
        return RegionCropper.PREDEFINED_REGIONS['china']
    
    @staticmethod
    def get_global_extent() -> Dict[str, float]:
        """
        Get global geographic extent.
        
        Returns:
            Dictionary with min_lon, max_lon, min_lat, max_lat
        """
        return RegionCropper.PREDEFINED_REGIONS['global']
    
    @staticmethod
    def get_available_regions() -> List[str]:
        """
        Get list of available predefined regions.
        
        Returns:
            List of region names
        """
        return list(RegionCropper.PREDEFINED_REGIONS.keys())
    
    @staticmethod
    def get_region_info(region_name: str) -> Dict[str, Union[str, float]]:
        """
        Get information about a predefined region.
        
        Args:
            region_name: Region name
            
        Returns:
            Dictionary with region information
        """
        if region_name not in RegionCropper.PREDEFINED_REGIONS:
            return RegionCropper.PREDEFINED_REGIONS['china']
        return RegionCropper.PREDEFINED_REGIONS[region_name]

class Resampler:
    """
    Resampling utilities for satellite imagery.
    Supports different resampling methods and spatial resolutions.
    """
    
    # Supported resampling methods
    RESAMPLING_METHODS = {
        'nearest': 'Nearest Neighbor',
        'bilinear': 'Bilinear Interpolation',
        'cubic': 'Cubic Interpolation',
        'lanczos': 'Lanczos Interpolation'
    }
    
    # Spatial resolutions for different satellites
    SPATIAL_RESOLUTIONS = {
        'FY4A': {
            'AGRI': {
                'B01': '1000M',
                'B02': '1000M',
                'B03': '1000M',
                'B04': '1000M',
                'B05': '2000M',
                'B06': '4000M',
                'B07': '4000M',
                'B08': '4000M',
                'B09': '4000M',
                'B10': '4000M',
                'B11': '4000M',
                'B12': '4000M',
                'B13': '4000M',
                'B14': '4000M',
                'B15': '4000M'
            }
        },
        'FY4B': {
            'AGRI': {
                'B01': '1000M',
                'B02': '1000M',
                'B03': '1000M',
                'B04': '1000M',
                'B05': '2000M',
                'B06': '4000M',
                'B07': '4000M',
                'B08': '4000M',
                'B09': '4000M',
                'B10': '4000M',
                'B11': '4000M',
                'B12': '4000M',
                'B13': '4000M',
                'B14': '4000M',
                'B15': '4000M'
            }
        },
        'Himawari-8': {
            'AHI': {
                'B01': '0500M',
                'B02': '0500M',
                'B03': '1000M',
                'B04': '1000M',
                'B05': '2000M',
                'B06': '2000M',
                'B07': '2000M',
                'B08': '4000M',
                'B09': '4000M',
                'B10': '4000M',
                'B11': '4000M',
                'B12': '4000M',
                'B13': '4000M',
                'B14': '4000M',
                'B15': '4000M'
            }
        }
    }
    
    @staticmethod
    def resample(data: np.ndarray, output_shape: Tuple[int, int], 
                method: str = 'bilinear') -> np.ndarray:
        """
        Resample data to specified shape.
        
        Args:
            data: Input data array
            output_shape: Output shape (height, width)
            method: Resampling method
            
        Returns:
            Resampled data array
        """
        import cv2
        
        # Map method names to OpenCV interpolation flags
        method_map = {
            'nearest': cv2.INTER_NEAREST,
            'bilinear': cv2.INTER_LINEAR,
            'cubic': cv2.INTER_CUBIC,
            'lanczos': cv2.INTER_LANCZOS4
        }
        
        interpolation = method_map.get(method, cv2.INTER_LINEAR)
        
        # Resample using OpenCV
        if data.ndim == 3:
            # For RGB data
            resampled = cv2.resize(data, (output_shape[1], output_shape[0]), 
                                 interpolation=interpolation)
        else:
            # For single band data
            resampled = cv2.resize(data, (output_shape[1], output_shape[0]), 
                                 interpolation=interpolation)
        
        return resampled
    
    @staticmethod
    def resample_multiple_bands(bands_data: Dict[str, np.ndarray], 
                              output_shape: Tuple[int, int], 
                              method: str = 'bilinear') -> Dict[str, np.ndarray]:
        """
        Resample multiple bands to specified shape.
        
        Args:
            bands_data: Dictionary of band names to data arrays
            output_shape: Output shape (height, width)
            method: Resampling method
            
        Returns:
            Dictionary of band names to resampled data arrays
        """
        resampled_bands = {}
        
        for band_name, data in bands_data.items():
            resampled_bands[band_name] = Resampler.resample(data, output_shape, method)
        
        return resampled_bands
    
    @staticmethod
    def get_band_resolution(satellite: str, sensor: str, band: str) -> str:
        """
        Get the native resolution for a specific band.
        
        Args:
            satellite: Satellite name
            sensor: Sensor name
            band: Band name
            
        Returns:
            Resolution string
        """
        try:
            return Resampler.SPATIAL_RESOLUTIONS[satellite][sensor][band]
        except KeyError:
            return '1000M'  # Default resolution
    
    @staticmethod
    def get_resolution_shape(resolution: str) -> Tuple[int, int]:
        """
        Get the approximate shape for a given resolution.
        
        Args:
            resolution: Resolution string
            
        Returns:
            Tuple of (height, width)
        """
        resolution_map = {
            '0500M': (8192, 8192),  # Approximate
            '1000M': (4096, 4096),
            '2000M': (2048, 2048),
            '4000M': (1024, 1024)
        }
        
        return resolution_map.get(resolution, (4096, 4096))
    
    @staticmethod
    def get_available_methods() -> List[str]:
        """
        Get list of available resampling methods.
        
        Returns:
            List of method names
        """
        return list(Resampler.RESAMPLING_METHODS.keys())
    
    @staticmethod
    def get_method_name(method: str) -> str:
        """
        Get the display name for a resampling method.
        
        Args:
            method: Method name
            
        Returns:
            Display name
        """
        return Resampler.RESAMPLING_METHODS.get(method, 'Bilinear Interpolation')

class GeoTIFFWriter:
    """
    GeoTIFF writing utilities for satellite imagery.
    Supports proper metadata and band information.
    """
    
    @staticmethod
    def write_geotiff(output_path: str, data: np.ndarray, lons: np.ndarray, lats: np.ndarray, 
                     metadata: Optional[Dict] = None, band_info: Optional[Dict] = None):
        """
        Write data to GeoTIFF format with georeferencing.
        
        Args:
            output_path: Output file path
            data: Input data array
            lons: Longitude array
            lats: Latitude array
            metadata: Additional metadata
            band_info: Band information
        """
        from osgeo import gdal, osr
        import numpy as np
        
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Get image dimensions
        if len(data.shape) == 2:
            height, width = data.shape
            bands = 1
        else:
            bands, height, width = data.shape
        
        # Create GeoTIFF driver
        driver = gdal.GetDriverByName('GTiff')
        
        # Create dataset
        out_ds = driver.Create(output_path, width, height, bands, gdal.GDT_Float32)
        
        # Set geotransform
        # Calculate pixel size
        x_res = (lons.max() - lons.min()) / width
        y_res = (lats.max() - lats.min()) / height
        
        # Upper left corner coordinates
        geotransform = (
            lons.min(), x_res, 0,
            lats.max(), 0, -y_res
        )
        
        out_ds.SetGeoTransform(geotransform)
        
        # Set projection
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)  # WGS84
        out_ds.SetProjection(srs.ExportToWkt())
        
        # Write data
        if bands == 1:
            out_ds.GetRasterBand(1).WriteArray(data)
            if band_info:
                out_ds.GetRasterBand(1).SetDescription(band_info.get('name', 'Band 1'))
                for key, value in band_info.items():
                    if key != 'name':
                        out_ds.GetRasterBand(1).SetMetadataItem(key, str(value))
        else:
            for i in range(bands):
                out_ds.GetRasterBand(i+1).WriteArray(data[i])
                if band_info and i < len(band_info):
                    band_meta = band_info[i]
                    out_ds.GetRasterBand(i+1).SetDescription(band_meta.get('name', f'Band {i+1}'))
                    for key, value in band_meta.items():
                        if key != 'name':
                            out_ds.GetRasterBand(i+1).SetMetadataItem(key, str(value))
        
        # Set metadata
        if metadata:
            for key, value in metadata.items():
                out_ds.SetMetadataItem(key, str(value))
        
        # Close dataset
        out_ds = None
    
    @staticmethod
    def write_multiple_bands(output_path: str, bands_data: Dict[str, np.ndarray], 
                            lons: np.ndarray, lats: np.ndarray, 
                            metadata: Optional[Dict] = None):
        """
        Write multiple bands to GeoTIFF format.
        
        Args:
            output_path: Output file path
            bands_data: Dictionary of band names to data arrays
            lons: Longitude array
            lats: Latitude array
            metadata: Additional metadata
        """
        from osgeo import gdal, osr
        import numpy as np
        
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Get image dimensions
        first_band = next(iter(bands_data.values()))
        height, width = first_band.shape
        bands = len(bands_data)
        
        # Create GeoTIFF driver
        driver = gdal.GetDriverByName('GTiff')
        
        # Create dataset
        out_ds = driver.Create(output_path, width, height, bands, gdal.GDT_Float32)
        
        # Set geotransform
        # Calculate pixel size
        x_res = (lons.max() - lons.min()) / width
        y_res = (lats.max() - lats.min()) / height
        
        # Upper left corner coordinates
        geotransform = (
            lons.min(), x_res, 0,
            lats.max(), 0, -y_res
        )
        
        out_ds.SetGeoTransform(geotransform)
        
        # Set projection
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)  # WGS84
        out_ds.SetProjection(srs.ExportToWkt())
        
        # Write bands
        band_index = 1
        for band_name, data in bands_data.items():
            out_ds.GetRasterBand(band_index).WriteArray(data)
            out_ds.GetRasterBand(band_index).SetDescription(band_name)
            band_index += 1
        
        # Set metadata
        if metadata:
            for key, value in metadata.items():
                out_ds.SetMetadataItem(key, str(value))
        
        # Close dataset
        out_ds = None
    
    @staticmethod
    def create_metadata(satellite: str, sensor: str, bands: List[str], 
                       acquisition_time: Optional[str] = None) -> Dict:
        """
        Create standard metadata for satellite imagery.
        
        Args:
            satellite: Satellite name
            sensor: Sensor name
            bands: List of band names
            acquisition_time: Acquisition time
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'satellite': satellite,
            'sensor': sensor,
            'bands': ','.join(bands),
            'creation_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'software': 'satImgViewer'
        }
        
        if acquisition_time:
            metadata['acquisition_time'] = acquisition_time
        
        return metadata
    
    @staticmethod
    def create_band_info(band_name: str, satellite: str, sensor: str) -> Dict:
        """
        Create band-specific information.
        
        Args:
            band_name: Band name
            satellite: Satellite name
            sensor: Sensor name
            
        Returns:
            Band information dictionary
        """
        # Band information mapping
        band_info_map = {
            'FY4A': {
                'AGRI': {
                    'B01': {'name': 'Visible Blue', 'wavelength': '0.47 μm', 'resolution': '1000m'},
                    'B02': {'name': 'Visible Green', 'wavelength': '0.51 μm', 'resolution': '1000m'},
                    'B03': {'name': 'Visible Red', 'wavelength': '0.65 μm', 'resolution': '1000m'},
                    'B04': {'name': 'Near Infrared', 'wavelength': '0.83 μm', 'resolution': '1000m'},
                    'B05': {'name': 'Short Wave Infrared', 'wavelength': '1.61 μm', 'resolution': '2000m'},
                    'B06': {'name': 'Mid Infrared', 'wavelength': '2.25 μm', 'resolution': '4000m'},
                    'B07': {'name': 'Thermal Infrared', 'wavelength': '3.75 μm', 'resolution': '4000m'},
                    'B08': {'name': 'Thermal Infrared', 'wavelength': '6.25 μm', 'resolution': '4000m'},
                    'B09': {'name': 'Thermal Infrared', 'wavelength': '7.10 μm', 'resolution': '4000m'},
                    'B10': {'name': 'Water Vapor', 'wavelength': '8.50 μm', 'resolution': '4000m'},
                    'B11': {'name': 'Thermal Infrared', 'wavelength': '10.8 μm', 'resolution': '4000m'},
                    'B12': {'name': 'Thermal Infrared', 'wavelength': '12.0 μm', 'resolution': '4000m'},
                    'B13': {'name': 'Thermal Infrared', 'wavelength': '13.5 μm', 'resolution': '4000m'},
                    'B14': {'name': 'CO2', 'wavelength': '14.3 μm', 'resolution': '4000m'},
                    'B15': {'name': 'Thermal Infrared', 'wavelength': '14.8 μm', 'resolution': '4000m'}
                }
            },
            'Himawari-8': {
                'AHI': {
                    'B01': {'name': 'Visible Blue', 'wavelength': '0.47 μm', 'resolution': '500m'},
                    'B02': {'name': 'Visible Green', 'wavelength': '0.51 μm', 'resolution': '500m'},
                    'B03': {'name': 'Visible Red', 'wavelength': '0.64 μm', 'resolution': '1000m'},
                    'B04': {'name': 'Near Infrared', 'wavelength': '0.86 μm', 'resolution': '1000m'},
                    'B05': {'name': 'Short Wave Infrared', 'wavelength': '1.60 μm', 'resolution': '2000m'},
                    'B06': {'name': 'Mid Infrared', 'wavelength': '2.30 μm', 'resolution': '2000m'},
                    'B07': {'name': 'Thermal Infrared', 'wavelength': '3.90 μm', 'resolution': '2000m'},
                    'B08': {'name': 'Water Vapor', 'wavelength': '6.20 μm', 'resolution': '4000m'},
                    'B09': {'name': 'Water Vapor', 'wavelength': '6.90 μm', 'resolution': '4000m'},
                    'B10': {'name': 'Water Vapor', 'wavelength': '7.30 μm', 'resolution': '4000m'},
                    'B11': {'name': 'Thermal Infrared', 'wavelength': '8.60 μm', 'resolution': '4000m'},
                    'B12': {'name': 'Thermal Infrared', 'wavelength': '9.60 μm', 'resolution': '4000m'},
                    'B13': {'name': 'Thermal Infrared', 'wavelength': '10.4 μm', 'resolution': '4000m'},
                    'B14': {'name': 'Thermal Infrared', 'wavelength': '11.2 μm', 'resolution': '4000m'},
                    'B15': {'name': 'Thermal Infrared', 'wavelength': '12.3 μm', 'resolution': '4000m'}
                }
            }
        }
        
        try:
            return band_info_map[satellite][sensor][band_name]
        except KeyError:
            return {'name': band_name, 'wavelength': 'N/A', 'resolution': 'N/A'}
