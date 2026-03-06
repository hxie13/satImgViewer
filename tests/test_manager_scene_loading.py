"""Tests for manager scene-driven loading."""
from core.drivers import DriverFactory
from core.drivers.base import BaseSatelliteDriver, SatelliteType
from core.manager import SatelliteImageManager
from core.scene import (
    FileRole,
    GeometryDescriptor,
    GeometryType,
    NormalizedScene,
    SourceFileRecord,
    get_analysis_grid_definition,
)


class MockSceneDriver(BaseSatelliteDriver):
    SATELLITE_TYPE = SatelliteType.UNKNOWN

    def identify(self, file_path: str) -> bool:
        return True

    def get_band_mapping(self):
        return {}

    def get_available_bands(self):
        return []

    def load(self, file_paths):
        self._is_loaded = True
        self.loaded_paths = list(file_paths)
        return True

    def load_scene(self, scene):
        self._is_loaded = True
        self.loaded_scene = scene
        self.loaded_paths = scene.file_paths
        return True

    def unload(self):
        self._is_loaded = False

    def request_image(self, params):
        return None, None

    def get_metadata(self):
        return {}

    def get_satellite_coverage(self):
        return None


def test_manager_load_scene_uses_normalized_scene_entrypoint():
    DriverFactory.register("mock_scene", MockSceneDriver)
    try:
        manager = SatelliteImageManager()
        scene = NormalizedScene(
            scene_id="mock_scene_1",
            driver_type="mock_scene",
            reader_type="mock_reader",
            satellite_family="TEST",
            satellite_platform="TESTSAT",
            sensor="TESTSENSOR",
            product_level="L1",
            product_code="TEST",
            nominal_time="2026-03-06 12:00:00",
            files=[
                SourceFileRecord(
                    path="/data/test_scene.nc",
                    file_name="test_scene.nc",
                    role=FileRole.PRIMARY,
                )
            ],
            datasets=[],
            native_geometry=GeometryDescriptor(
                geometry_type=GeometryType.LATLON_GRID,
                projection_id="plate_carree_native",
            ),
            analysis_grid=get_analysis_grid_definition("plate_carree_global"),
        )

        ok = manager.load_scene(scene)

        assert ok is True
        assert manager.current_scene is scene
        assert manager.current_driver_type == "mock_scene"
        assert manager.current_driver.loaded_scene is scene
        assert manager.time_groups == [scene.file_paths]
    finally:
        DriverFactory.unregister("mock_scene")
