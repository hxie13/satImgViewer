"""Tests for scene normalization and shared analysis-grid baselines."""
from core.ingest import SceneIngestService
from core.scene import GeometryType, MeasurementType


def test_normalize_fy3d_scene_groups_geo_file_and_assigns_shared_grid():
    service = SceneIngestService()
    file_paths = [
        "/data/FY3D_MERSI_GBAL_L1_20230101_0300_1000M_MS.HDF",
        "/data/FY3D_MERSI_GBAL_L1_20230101_0300_GEO1K_MS.HDF",
    ]

    collection = service.normalize_file_paths(file_paths, probe_metadata=False)

    assert len(collection.scenes) == 1
    scene = collection.scenes[0]
    assert scene.driver_type == "fengyun3d"
    assert scene.native_geometry.geometry_type == GeometryType.SWATH
    assert scene.analysis_grid.grid_id == "plate_carree_global"
    assert any(record.auxiliary_role == "geolocation" for record in scene.auxiliary_files)
    assert scene.nominal_time == "2023-01-01 03:00:00"


def test_normalize_himawari_scene_exposes_canonical_datasets():
    service = SceneIngestService()
    file_paths = [
        "/data/H08_20230101_0300_sample.nc",
    ]

    collection = service.normalize_file_paths(file_paths, probe_metadata=False)

    assert len(collection.scenes) == 1
    scene = collection.scenes[0]
    dataset_names = {dataset.canonical_name for dataset in scene.datasets}
    assert scene.driver_type == "himawari"
    assert scene.native_geometry.geometry_type == GeometryType.LATLON_GRID
    assert "VIS006" in dataset_names
    assert "IR105" in dataset_names


def test_normalize_fy4_l2_scene_produces_product_descriptor():
    service = SceneIngestService()
    file_paths = [
        "/data/FY4B-_AGRI--_N_DISK_1047E_L2-_CTT-_MULT_NOM_20250721034500_20250721035959_4000M_V0001.NC",
    ]

    collection = service.normalize_file_paths(file_paths, probe_metadata=False)

    assert len(collection.scenes) == 1
    scene = collection.scenes[0]
    assert scene.driver_type == "fengyun"
    assert len(scene.datasets) == 1
    assert scene.datasets[0].canonical_name == "CTT"
    assert scene.datasets[0].measurement_type == MeasurementType.PRODUCT
