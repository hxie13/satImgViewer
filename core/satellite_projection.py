"""
Satellite projection utilities for transforming between geographic coordinates and satellite image coordinates.
Supports Fengyun-4 series satellites with geostationary orbit.
"""
import math
import numpy as np
from numpy import deg2rad, rad2deg, arctan, arcsin, tan, sqrt, cos, sin

# Earth parameters
ea = 6378.137  # 地球的半长轴[km]
eb = 6356.7523  # 地球的短半轴[km]
h = 42164  # 地心到卫星质心的距离[km]

# Satellite-specific parameters
SATELLITE_PARAMS = {
    'FY4A': {
        'λD': deg2rad(104.7),  # 卫星星下点所在经度
        'COFF': {
            "0500M": 10991.5,
            "1000M": 5495.5,
            "2000M": 2747.5,
            "4000M": 1373.5
        },
        'CFAC': {
            "0500M": 81865099,
            "1000M": 40932549,
            "2000M": 20466274,
            "4000M": 10233137
        }
    },
    'FY4B': {
        'λD': deg2rad(104.7),  # 卫星星下点所在经度
        'COFF': {
            "0500M": 10991.5,
            "1000M": 5495.5,
            "2000M": 2747.5,
            "4000M": 1373.5
        },
        'CFAC': {
            "0500M": 81865099,
            "1000M": 40932549,
            "2000M": 20466274,
            "4000M": 10233137
        }
    },
    'Himawari-8': {
        'λD': deg2rad(140.7),  # 卫星星下点所在经度
        'COFF': {
            "0500M": 10991.5,
            "1000M": 5495.5,
            "2000M": 2747.5,
            "4000M": 1373.5
        },
        'CFAC': {
            "0500M": 81865099,
            "1000M": 40932549,
            "2000M": 20466274,
            "4000M": 10233137
        }
    }
}

def latlon2linecolumn(lat, lon, resolution, satellite='FY4A'):
    """
    经纬度转行列
    (lat, lon) → (line, column)
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        resolution: Resolution string {'0500M', '1000M', '2000M', '4000M'}
        satellite: Satellite name {'FY4A', 'FY4B', 'Himawari-8'}
    
    Returns:
        Tuple of (line, column) as integers
    """
    # Get satellite parameters
    params = SATELLITE_PARAMS.get(satellite, SATELLITE_PARAMS['FY4A'])
    λD = params['λD']
    COFF = params['COFF']
    CFAC = params['CFAC']
    LOFF = COFF  # 行偏移
    LFAC = CFAC  # 行比例因子
    
    # Step2.将地理经纬度的角度表示转化为弧度表示
    lat = deg2rad(lat)
    lon = deg2rad(lon)
    
    # Step3.将地理经纬度转化成地心经纬度
    eb2_ea2 = eb ** 2 / ea ** 2
    λe = lon
    φe = arctan(eb2_ea2 * tan(lat))
    
    # Step4.求Re
    cosφe = cos(φe)
    re = eb / sqrt(1 - (1 - eb2_ea2) * cosφe ** 2)
    
    # Step5.求r1,r2,r3
    λe_λD = λe - λD
    r1 = h - re * cosφe * cos(λe_λD)
    r2 = -re * cosφe * sin(λe_λD)
    r3 = re * sin(φe)
    
    # Step6.求rn,x,y
    rn = sqrt(r1 ** 2 + r2 ** 2 + r3 ** 2)
    x = rad2deg(arctan(-r2 / r1))
    y = rad2deg(arcsin(-r3 / rn))
    
    # Step7.求c,l
    column = COFF[resolution] + x * 2 ** -16 * CFAC[resolution]
    line = LOFF[resolution] + y * 2 ** -16 * LFAC[resolution]
    
    return np.rint(line).astype(np.uint16), np.rint(column).astype(np.uint16)

def linecolumn2latlon(line, column, resolution, satellite='FY4A'):
    """
    行列转经纬度
    (line, column) → (lat, lon)
    
    Args:
        line: Line number in satellite image
        column: Column number in satellite image
        resolution: Resolution string {'0500M', '1000M', '2000M', '4000M'}
        satellite: Satellite name {'FY4A', 'FY4B', 'Himawari-8'}
    
    Returns:
        Tuple of (lat, lon) in degrees
    """
    # Get satellite parameters
    params = SATELLITE_PARAMS.get(satellite, SATELLITE_PARAMS['FY4A'])
    λD = params['λD']
    COFF = params['COFF']
    CFAC = params['CFAC']
    LOFF = COFF  # 行偏移
    LFAC = CFAC  # 行比例因子
    
    # Step1.计算x,y
    x = (column - COFF[resolution]) * 2 ** 16 / CFAC[resolution]
    y = (line - LOFF[resolution]) * 2 ** 16 / LFAC[resolution]
    
    # Step2.将x,y转化为弧度
    x_rad = deg2rad(x)
    y_rad = deg2rad(y)
    
    # Step3.计算r1,r2,r3
    r1 = -cos(y_rad) * cos(x_rad)
    r2 = cos(y_rad) * sin(x_rad)
    r3 = -sin(y_rad)
    
    # Step4.计算地心经纬度
    λe = λD + arctan(r2 / r1)
    φe = arcsin(r3 / sqrt(r1 ** 2 + r2 ** 2 + r3 ** 2))
    
    # Step5.将地心经纬度转化为地理经纬度
    eb2_ea2 = eb ** 2 / ea ** 2
    lat = rad2deg(arctan(tan(φe) / eb2_ea2))
    lon = rad2deg(λe)
    
    return lat, lon

def get_satellite_coverage(satellite='FY4A'):
    """
    Get the geographic coverage area for a satellite
    
    Args:
        satellite: Satellite name {'FY4A', 'FY4B', 'Himawari-8'}
    
    Returns:
        Tuple of (west, east, south, north) in degrees
    """
    if satellite in ['FY4A', 'FY4B']:
        # FY4A/B coverage: 70°E to 140°E, 50°S to 50°N
        return 70, 140, -50, 50
    elif satellite == 'Himawari-8':
        # Himawari-8 coverage: 80°E to 160°E, 60°S to 60°N
        return 80, 160, -60, 60
    else:
        # Default coverage
        return 70, 140, -50, 50
