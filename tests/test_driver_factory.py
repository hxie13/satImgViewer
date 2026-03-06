"""Tests for DriverFactory and driver identification."""
import pytest
from core.drivers import DriverFactory
from core.drivers.base import SatelliteType
from core.file_recognizer import FileTypeRecognizer, SatelliteType as RecognizerSatelliteType, ProductLevel


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

    def test_create_from_files_with_fy4_l2_format_routes_to_fengyun(self):
        """Direct FY4 L2 format hint should route to FengYun driver."""
        files = [
            '/data/FY4B-_AGRI--_N_DISK_1047E_L2-_CLM-_MULT_NOM_20250721034500_20250721035959_4000M_V0001.NC'
        ]
        driver = DriverFactory.create_from_files(files, preferred_format='fy4_l2_nc')
        assert driver.__class__.__name__ == 'FengYunDriver'

    def test_create_from_files_with_himawari_format_routes_to_himawari(self):
        """Direct Himawari format hint should route to Himawari driver."""
        files = ['/data/H08_L2_CLM_20250721_0345.nc']
        driver = DriverFactory.create_from_files(files, preferred_format='himawari_l1b_nc')
        assert driver.__class__.__name__ == 'HimawariDriver'


class TestFileTypeRecognizer:
    def test_recognize_fy4b_legacy_name_l1(self):
        """Legacy FY4B naming should map directly to fy4_agri_l1."""
        recognizer = FileTypeRecognizer()
        path = '/data/FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20250721034500_20250721035959_4000M_V0001.HDF'

        result = recognizer.recognize(path)

        assert result.reader == 'fy4_agri_l1'
        assert result.satellite_type == RecognizerSatelliteType.FY4B
        assert result.product_level == ProductLevel.L1
        assert result.sensor == 'AGRI'
        assert result.product in ('FDI', 'DISK')
        assert result.region == 'FULL_DISK'
        assert result.file_format == 'HDF'
        assert result.timestamp == '20250721034500'
        assert result.resolution == '4000M'

    def test_recognize_fy4b_l2_cf_reader(self):
        """FY4B L2 naming should map directly to fy4_l2_nc."""
        recognizer = FileTypeRecognizer()
        path = '/data/FY4B-_AGRI--_N_DISK_1047E_L2-_CLM-_MULT_NOM_20250721034500_20250721035959_4000M_V0001.NC'

        result = recognizer.recognize(path)

        assert result.reader == 'fy4_l2_nc'
        assert result.product_level == ProductLevel.L2
        assert result.product == 'CLM'
        assert result.file_format == 'NC'

    def test_consensus_prefers_weighted_confidence(self):
        """Consensus should prefer high-confidence specific match over unknowns."""
        recognizer = FileTypeRecognizer()
        files = [
            '/data/FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_20250721034500_20250721035959_4000M_V0001.HDF',
            '/data/unknown_file_xxx.bin',
            '/data/random.tmp',
        ]

        assert recognizer.get_consensus_reader(files) == 'fy4_agri_l1'
