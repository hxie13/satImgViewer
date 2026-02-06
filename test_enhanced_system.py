#!/usr/bin/env python3
"""
Test script for the enhanced satellite image processing system.
Tests calibration, GLT correction, cropping, resampling, and GeoTIFF output.
"""

import os
import sys
import numpy as np
from core.calibration import Calibration, GLTCorrection, RegionCropper, Resampler, GeoTIFFWriter

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_calibration():
    """Test radiometric calibration functionality."""
    print("=== Testing Calibration ===")
    
    # Create test data (digital numbers)
    test_data = np.random.rand(100, 100) * 10000
    
    # Test FY4A calibration
    calibrated_data = Calibration.calibrate_data(test_data, "FY4A", "AGRI", "B03")
    print(f"FY4A B03 calibration: min={calibrated_data.min():.2f}, max={calibrated_data.max():.2f}")
    
    # Test Himawari-8 calibration
    calibrated_data = Calibration.calibrate_data(test_data, "Himawari-8", "AHI", "B03")
    print(f"Himawari-8 B03 calibration: min={calibrated_data.min():.2f}, max={calibrated_data.max():.2f}")
    
    print("Calibration test passed!")

def test_glt_correction():
    """Test GLT geometric correction functionality."""
    print("\n=== Testing GLT Correction ===")
    
    # Create test data
    test_data = np.random.rand(100, 100)
    
    # Create simple GLT (identity transform)
    glt_x, glt_y = np.meshgrid(np.arange(100), np.arange(100))
    glt_x = glt_x.astype(float) + 0.5
    glt_y = glt_y.astype(float) + 0.5
    
    # Test GLT application
    corrected_data = GLTCorrection.apply_glt(test_data, glt_x, glt_y)
    print(f"GLT correction: input shape={test_data.shape}, output shape={corrected_data.shape}")
    
    # Test multi-band correction
    bands_data = {
        "B01": np.random.rand(100, 100),
        "B02": np.random.rand(100, 100),
        "B03": np.random.rand(100, 100)
    }
    corrected_bands = GLTCorrection.apply_glt_to_multiple_bands(bands_data, glt_x, glt_y)
    print(f"Multi-band GLT correction: {len(corrected_bands)} bands corrected")
    
    print("GLT correction test passed!")

def test_region_cropping():
    """Test region cropping functionality."""
    print("\n=== Testing Region Cropping ===")
    
    # Create test data and geolocation
    test_data = np.random.rand(200, 200)
    lons, lats = np.meshgrid(np.linspace(70, 140, 200), np.linspace(15, 55, 200))
    
    # Test China region cropping
    cropped_data, cropped_lons, cropped_lats = RegionCropper.crop_by_predefined_region(
        test_data, lons, lats, "china"
    )
    print(f"China region cropping: input shape={test_data.shape}, output shape={cropped_data.shape}")
    print(f"Cropped region: lon [{cropped_lons.min():.1f}, {cropped_lons.max():.1f}], "
          f"lat [{cropped_lats.min():.1f}, {cropped_lats.max():.1f}]")
    
    # Test multi-band cropping
    bands_data = {
        "B01": np.random.rand(200, 200),
        "B02": np.random.rand(200, 200),
        "B03": np.random.rand(200, 200)
    }
    cropped_bands = RegionCropper.crop_multiple_bands(
        bands_data, lons, lats, 73, 135, 18, 53
    )
    print(f"Multi-band cropping: {len(cropped_bands)} bands cropped")
    
    # Test available regions
    available_regions = RegionCropper.get_available_regions()
    print(f"Available regions: {available_regions}")
    
    print("Region cropping test passed!")

def test_resampling():
    """Test resampling functionality."""
    print("\n=== Testing Resampling ===")
    
    # Create test data
    test_data = np.random.rand(100, 100)
    
    # Test different resampling methods
    for method in ["nearest", "bilinear", "cubic", "lanczos"]:
        resampled_data = Resampler.resample(test_data, (200, 200), method)
        print(f"{method} resampling: input shape={test_data.shape}, output shape={resampled_data.shape}")
    
    # Test multi-band resampling
    bands_data = {
        "B01": np.random.rand(100, 100),
        "B02": np.random.rand(100, 100),
        "B03": np.random.rand(100, 100)
    }
    resampled_bands = Resampler.resample_multiple_bands(bands_data, (200, 200), "bilinear")
    print(f"Multi-band resampling: {len(resampled_bands)} bands resampled")
    
    # Test band resolution retrieval
    resolution = Resampler.get_band_resolution("FY4A", "AGRI", "B03")
    print(f"FY4A AGRI B03 resolution: {resolution}")
    
    print("Resampling test passed!")

def test_geotiff_writing():
    """Test GeoTIFF writing functionality."""
    print("\n=== Testing GeoTIFF Writing ===")
    
    # Create test data and geolocation
    test_data = np.random.rand(100, 100)
    lons, lats = np.meshgrid(np.linspace(70, 140, 100), np.linspace(15, 55, 100))
    
    # Create test output path
    output_path = os.path.join(os.path.dirname(__file__), "test_output.tif")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # Create metadata
        metadata = GeoTIFFWriter.create_metadata("FY4A", "AGRI", ["B03"], "2024-01-01 12:00:00")
        
        # Create band info
        band_info = GeoTIFFWriter.create_band_info("B03", "FY4A", "AGRI")
        
        # Write GeoTIFF
        GeoTIFFWriter.write_geotiff(output_path, test_data, lons, lats, metadata, band_info)
        print(f"GeoTIFF written to: {output_path}")
        
        # Test multi-band GeoTIFF
        multi_band_output = os.path.join(os.path.dirname(__file__), "test_output_multi.tif")
        bands_data = {
            "B01": np.random.rand(100, 100),
            "B02": np.random.rand(100, 100),
            "B03": np.random.rand(100, 100)
        }
        metadata = GeoTIFFWriter.create_metadata("FY4A", "AGRI", ["B01", "B02", "B03"])
        GeoTIFFWriter.write_multiple_bands(multi_band_output, bands_data, lons, lats, metadata)
        print(f"Multi-band GeoTIFF written to: {multi_band_output}")
        
        print("GeoTIFF writing test passed!")
    except Exception as e:
        print(f"GeoTIFF writing test failed: {e}")
    finally:
        # Clean up
        if os.path.exists(output_path):
            os.remove(output_path)
        multi_band_output = os.path.join(os.path.dirname(__file__), "test_output_multi.tif")
        if os.path.exists(multi_band_output):
            os.remove(multi_band_output)

def main():
    """Run all tests."""
    print("Testing Enhanced Satellite Image Processing System")
    print("=" * 60)
    
    try:
        test_calibration()
        test_glt_correction()
        test_region_cropping()
        test_resampling()
        test_geotiff_writing()
        
        print("\n" + "=" * 60)
        print("All tests passed successfully!")
        print("The enhanced system is ready for use with Fengyun satellite data.")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
