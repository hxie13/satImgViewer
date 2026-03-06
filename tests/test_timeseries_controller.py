"""Tests for scene-aware time-series controller loading."""

import os
from types import SimpleNamespace

import pytest

if os.environ.get("SATIMGVIEWER_ENABLE_QT_TESTS") != "1":
    pytest.skip(
        "Qt controller tests are disabled in this environment; set SATIMGVIEWER_ENABLE_QT_TESTS=1 to enable.",
        allow_module_level=True,
    )

from PyQt6.QtCore import QObject, pyqtSignal

from core.app_state import AppState
from core.scene import (
    FileRole,
    GeometryDescriptor,
    GeometryType,
    NormalizedScene,
    SourceFileRecord,
    get_analysis_grid_definition,
)
import ui.controllers.timeseries_controller as timeseries_module


def _make_scene(scene_id: str, path: str) -> NormalizedScene:
    return NormalizedScene(
        scene_id=scene_id,
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
                path=path,
                file_name=path.split("/")[-1],
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


class FakeFrameLoaderWorker(QObject):
    """Synchronous test double for FrameLoaderWorker."""

    frame_loaded = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    created = []

    def __init__(self, manager, files=None, pinned_driver_type=None, scene=None):
        super().__init__()
        self.manager = manager
        self.files = list(files) if files else []
        self.pinned_driver_type = pinned_driver_type
        self.scene = scene
        self.started = False
        self.cancelled = False
        self.wait_ms = None
        self.__class__.created.append(self)

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started and not self.cancelled

    def cancel(self):
        self.cancelled = True

    def wait(self, wait_ms):
        self.wait_ms = wait_ms
        return True


def test_set_scenes_stores_normalized_frames_and_loads_scene_worker(monkeypatch):
    FakeFrameLoaderWorker.created.clear()
    monkeypatch.setattr(timeseries_module, "FrameLoaderWorker", FakeFrameLoaderWorker)

    state = AppState()
    manager = SimpleNamespace(current_driver=None, current_driver_type="mock_scene")
    controller = timeseries_module.TimeSeriesController(manager, state)
    scene = _make_scene("scene_1", "/data/scene_1.nc")

    controller.set_scenes([scene])

    assert state.normalized_scenes == [scene]
    assert state.file_groups == [scene.file_paths]

    started = controller.load_frame(0)

    assert started is True
    worker = FakeFrameLoaderWorker.created[-1]
    assert worker.scene is scene
    assert worker.files == scene.file_paths

    worker.frame_loaded.emit(scene.nominal_time)
    assert state.current_frame_index == 0
    assert controller._pinned_driver_type == "mock_scene"

    worker.finished.emit()
    assert controller._frame_worker is None


def test_set_file_groups_clears_normalized_scenes(monkeypatch):
    monkeypatch.setattr(timeseries_module, "FrameLoaderWorker", FakeFrameLoaderWorker)

    state = AppState()
    manager = SimpleNamespace(current_driver=None, current_driver_type=None)
    controller = timeseries_module.TimeSeriesController(manager, state)
    scene = _make_scene("scene_1", "/data/scene_1.nc")

    controller.set_scenes([scene])
    controller.set_file_groups([["/data/frame_1.nc"]])

    assert state.normalized_scenes == []
    assert state.file_groups == [["/data/frame_1.nc"]]
