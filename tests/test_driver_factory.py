"""Tests for DriverFactory and driver identification."""
import pytest
from core.drivers import DriverFactory
from core.drivers.base import SatelliteType


class TestDriverFactory:
    """Test cases for DriverFactory."""
    
    def test_identify_fengyun4_files(self):
        """Test identification of FY4A/FY4B files."""
        test_files = [
            '/data/FY4A_AGRI_20230101_0300_1000M.HDF',
            '/data/FY-4B_20230101_0300.FLDK.nc',
        ]
        results = DriverFactory.identify_files(test_files)
        
        assert len(results) == 2
        assert all(r.driver_type == 'fengyun' for r in results)
        assert all(r.confidence > 0 for r in results)
    
    def test_identify_fy3d_files(self):
        """Test identification of FY3D MERSI files."""
        test_files = [
            '/data/FY3D_MERSI_GBAL_L1_20230101_0300_1000M_MS.HDF',
        ]
        results = DriverFactory.identify_files(test_files)
        
        assert len(results) == 1
        assert results[0].driver_type == 'fengyun3d'
    
    def test_identify_himawari_files(self):
        """Test identification of Himawari files."""
        test_files = [
            '/data/HS_H08_20230101_0300_B01_R10_S0101.DAT',
        ]
        results = DriverFactory.identify_files(test_files)
        
        assert len(results) == 1
        assert results[0].driver_type == 'himawari'
    
    def test_create_driver(self):
        """Test driver instantiation."""
        driver = DriverFactory.create_driver('fengyun')
        assert driver.SATELLITE_TYPE in [SatelliteType.FENGYUN_4A, SatelliteType.FENGYUN_4B]
    
    def test_create_unknown_driver_raises(self):
        """Test that unknown driver type raises ValueError."""
        with pytest.raises(ValueError, match='Unknown driver type'):
            DriverFactory.create_driver('unknown_driver')
    
    def test_register_new_driver(self):
        """Test dynamic driver registration."""
        from core.drivers.base import BaseSatelliteDriver
        
        class MockDriver(BaseSatelliteDriver):
            SATELLITE_TYPE = SatelliteType.UNKNOWN
            
            def identify(self, file_path: str) -> bool:
                return True
            def get_band_mapping(self):
                return {}
            def get_available_bands(self):
                return []
            def load(self, file_paths):
                return True
            def unload(self):
                pass
            def request_image(self, params):
                return None, None
            def get_metadata(self):
                return {}
            def get_satellite_coverage(self):
                return None
        
        DriverFactory.register('mock', MockDriver)
        assert 'mock' in DriverFactory.get_available_drivers()
        
        # Cleanup
        DriverFactory.unregister('mock')
