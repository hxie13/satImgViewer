"""Tests for manager render-request entrypoints."""

import numpy as np

from core.drivers import DriverFactory
from core.drivers.base import BaseSatelliteDriver, SatelliteType
from core.manager import SatelliteImageManager
from core.product_requests import RenderRequest
from core.scene import (
    FileRole,
    GeometryDescriptor,
    GeometryType,
    NormalizedScene,
    SourceFileRecord,
    get_analysis_grid_definition,
)


class MockRenderRequestDriver(BaseSatelliteDriver):
    SATELLITE_TYPE = SatelliteType.UNKNOWN

    def identify(self, file_path: str) -> bool:
        return True

    def get_band_mapping(self):
        return {}

    def get_available_bands(self):
        return []

    def load(self, file_paths):
        self._is_loaded = True
        return True

    def load_scene(self, scene):
        self._is_loaded = True
        self.loaded_scene = scene
        return True

    def unload(self):
        self._is_loaded = False

    def request_image(self, params):
        self.last_params = params
        return np.ones((4, 4, 3), dtype=np.float32), {"area": "mock"}

    def get_metadata(self):
        return {}

    def get_satellite_coverage(self):
        return None


def _make_scene() -> NormalizedScene:
    return NormalizedScene(
        scene_id="mock_scene_1",
        driver_type="mock_render_request",
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


def test_manager_process_render_request_uses_request_defaults():
    DriverFactory.register("mock_render_request", MockRenderRequestDriver)
    try:
        manager = SatelliteImageManager()
        assert manager.load_scene(_make_scene()) is True

        request = RenderRequest(
            bands=("VIS006", "IR105"),
            projection="plate_carree_global",
            gamma=1.3,
            output_size=(512, 256),
            quality_profile="export_high",
        )
        image, area = manager.process_render_request(request)

        params = manager.current_driver.last_params
        assert image.shape == (4, 4, 3)
        assert area == {"area": "mock"}
        assert params.bands == ["VIS006", "IR105"]
        assert params.output_proj == "plate_carree_global"
        assert params.output_size == (512, 256)
        assert params.resample_method == "bilinear"
        assert params.quality_profile == "export_high"
    finally:
        DriverFactory.unregister("mock_render_request")


def test_manager_process_image_legacy_api_delegates_to_render_request():
    DriverFactory.register("mock_render_request", MockRenderRequestDriver)
    try:
        manager = SatelliteImageManager()
        assert manager.load_scene(_make_scene()) is True

        manager.process_image(
            bands=["VIS006"],
            gamma=1.0,
            proj_name="geostationary_native",
            size=(320, 160),
            quality_profile="preview_fast",
        )

        params = manager.current_driver.last_params
        assert params.bands == ["VIS006"]
        assert params.output_proj == "geostationary_native"
        assert params.output_size == (320, 160)
        assert params.resample_method == "nearest"
    finally:
        DriverFactory.unregister("mock_render_request")
