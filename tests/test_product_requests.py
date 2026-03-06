"""Tests for normalized render/export request models."""

from core.product_requests import (
    ProductRecipe,
    RenderRequest,
    StillExportRequest,
    VideoExportRequest,
)


def test_render_request_preview_resolves_preview_defaults():
    request = RenderRequest.preview(
        ["VIS006", "IR105"],
        projection="plate_carree_global",
        gamma=1.2,
        output_size=(800, 400),
    )

    assert request.bands == ("VIS006", "IR105")
    assert request.quality_profile == "preview_fast"
    assert request.resolved_resample_method() == "nearest"
    assert request.to_processing_params().output_proj == "plate_carree_global"


def test_render_request_globe_texture_targets_shared_global_grid():
    request = RenderRequest.globe_texture(
        ["VIS006", "IR105", "IR112"],
        gamma=1.0,
        output_size=(1600, 800),
    )

    assert request.projection == "plate_carree_global"
    assert request.quality_profile == "preview_fast"
    assert request.resolved_resample_method() == "nearest"


def test_still_export_request_resolves_format_from_output_suffix():
    png_request = StillExportRequest(
        output_path="preview.png",
        render_request=RenderRequest(bands=("VIS006",)),
    )
    tif_request = StillExportRequest(
        output_path="preview.tif",
        render_request=RenderRequest(bands=("VIS006",)),
    )

    assert png_request.resolved_format() == "png"
    assert tif_request.resolved_format() == "geotiff"


def test_video_export_request_preserves_driver_pin():
    request = VideoExportRequest(
        output_path="sequence.mp4",
        render_request=RenderRequest(bands=("VIS006",), projection="plate_carree_global"),
        fps=12,
        pinned_driver_type="himawari",
    )

    assert request.fps == 12
    assert request.pinned_driver_type == "himawari"
    assert request.render_request.projection == "plate_carree_global"


def test_product_recipe_builds_preview_and_texture_requests():
    recipe = ProductRecipe(
        bands=("VIS006", "IR105", "IR112"),
        projection="plate_carree_global",
        gamma=1.1,
    )

    preview = recipe.preview_request((1200, 600))
    texture = recipe.texture_request((1600, 800))

    assert preview.projection == "plate_carree_global"
    assert preview.output_size == (1200, 600)
    assert texture.projection == "plate_carree_global"
    assert texture.output_size == (1600, 800)


def test_product_recipe_builds_export_requests_with_consistent_bands():
    recipe = ProductRecipe(
        bands=("VIS006", "IR105", "IR112"),
        projection="plate_carree_global",
        gamma=1.1,
    )

    still_request = recipe.still_export_request("preview.tif")
    video_request = recipe.video_export_request(
        "preview.mp4",
        fps=15,
        pinned_driver_type="himawari",
    )

    assert still_request.render_request.bands == recipe.bands
    assert still_request.resolved_format() == "geotiff"
    assert video_request.render_request.bands == recipe.bands
    assert video_request.pinned_driver_type == "himawari"
    assert video_request.fps == 15
