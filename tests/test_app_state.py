"""Tests for AppState scene-aware frame access."""

from core.app_state import AppState
from core.scene import (
    FileRole,
    GeometryDescriptor,
    GeometryType,
    NormalizedScene,
    SourceFileRecord,
    get_analysis_grid_definition,
)


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


def test_app_state_prefers_normalized_scene_for_current_frame():
    scene = _make_scene("scene_1", "/data/scene_1.nc")
    state = AppState(
        file_groups=[["/data/fallback.nc"]],
        normalized_scenes=[scene],
        current_frame_index=0,
    )

    assert state.has_data is True
    assert state.total_frames == 1
    assert state.current_scene is scene
    assert state.current_files == ["/data/scene_1.nc"]


def test_app_state_falls_back_to_file_groups_without_normalized_scene():
    state = AppState(
        file_groups=[["/data/frame_1.nc", "/data/frame_1_geo.nc"]],
        current_frame_index=0,
    )

    assert state.current_scene is None
    assert state.total_frames == 1
    assert state.current_files == ["/data/frame_1.nc", "/data/frame_1_geo.nc"]


def test_app_state_set_normalized_scenes_updates_compat_file_groups():
    scene_1 = _make_scene("scene_1", "/data/scene_1.nc")
    scene_2 = _make_scene("scene_2", "/data/scene_2.nc")
    state = AppState(current_frame_index=3)

    state.set_normalized_scenes([scene_1, scene_2])

    assert state.current_frame_index == -1
    assert state.normalized_scenes == [scene_1, scene_2]
    assert state.file_groups == [scene_1.file_paths, scene_2.file_paths]
    assert state.get_frame_files(1) == ["/data/scene_2.nc"]


def test_app_state_clear_time_series_resets_scene_and_file_state():
    scene = _make_scene("scene_1", "/data/scene_1.nc")
    state = AppState(current_frame_index=0)
    state.set_normalized_scenes([scene])

    state.clear_time_series()

    assert state.current_frame_index == -1
    assert state.normalized_scenes == []
    assert state.file_groups == []
    assert state.total_frames == 0
