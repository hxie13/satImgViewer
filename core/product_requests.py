"""
Unified render and export request models.

These request objects decouple downstream visualization/export flows from
ad-hoc parameter dicts assembled inside controllers and workers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .drivers.base import ProcessingParams


def _normalize_bands(bands: Sequence[str]) -> Tuple[str, ...]:
    return tuple(str(band) for band in bands)


def _normalize_output_size(output_size: Optional[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    if output_size is None:
        return None
    return (int(output_size[0]), int(output_size[1]))


@dataclass(frozen=True)
class RenderRequest:
    """Normalized request for generating a rendered satellite image product."""

    bands: Tuple[str, ...]
    projection: str = "geostationary_native"
    gamma: float = 1.0
    output_size: Optional[Tuple[int, int]] = None
    quality_profile: str = "default"
    resample_method: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bands", _normalize_bands(self.bands))
        object.__setattr__(self, "gamma", float(self.gamma))
        object.__setattr__(self, "output_size", _normalize_output_size(self.output_size))

    @classmethod
    def preview(
        cls,
        bands: Sequence[str],
        *,
        projection: str,
        gamma: float,
        output_size: Optional[Tuple[int, int]] = None,
        resample_method: str = "nearest",
    ) -> "RenderRequest":
        """Factory for interactive 2D preview rendering."""
        return cls(
            bands=tuple(bands),
            projection=projection,
            gamma=gamma,
            output_size=output_size,
            quality_profile="preview_fast",
            resample_method=resample_method,
        )

    @classmethod
    def globe_texture(
        cls,
        bands: Sequence[str],
        *,
        gamma: float,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> "RenderRequest":
        """Factory for 3D globe texture generation."""
        return cls(
            bands=tuple(bands),
            projection="plate_carree_global",
            gamma=gamma,
            output_size=output_size,
            quality_profile="preview_fast",
            resample_method="nearest",
        )

    def with_output_size(self, output_size: Optional[Tuple[int, int]]) -> "RenderRequest":
        """Return a copy with a different output size."""
        return RenderRequest(
            bands=self.bands,
            projection=self.projection,
            gamma=self.gamma,
            output_size=output_size,
            quality_profile=self.quality_profile,
            resample_method=self.resample_method,
        )

    def resolved_resample_method(self) -> str:
        """Resolve the runtime resampling method from profile/defaults."""
        if self.resample_method:
            return self.resample_method
        if self.quality_profile == "export_high":
            return "bilinear"
        return "nearest"

    def to_processing_params(self) -> ProcessingParams:
        """Convert to the driver-facing ProcessingParams contract."""
        return ProcessingParams(
            bands=list(self.bands),
            gamma=self.gamma,
            output_size=self.output_size,
            output_proj=self.projection,
            resample_method=self.resolved_resample_method(),
            quality_profile=self.quality_profile,
        )

    def cache_key(self, frame_index: int) -> Tuple[object, ...]:
        """Stable cache key used by image/texture preview caches."""
        return (
            frame_index,
            self.bands,
            self.projection,
            round(float(self.gamma), 3),
            self.output_size,
            self.quality_profile,
            self.resolved_resample_method(),
        )


@dataclass(frozen=True)
class ProductRecipe:
    """Reusable visualization/export recipe independent of output transport."""

    bands: Tuple[str, ...]
    projection: str = "geostationary_native"
    gamma: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "bands", _normalize_bands(self.bands))
        object.__setattr__(self, "gamma", float(self.gamma))

    def preview_request(
        self,
        output_size: Optional[Tuple[int, int]] = None,
        *,
        resample_method: str = "nearest",
    ) -> RenderRequest:
        """Build an interactive preview render request."""
        return RenderRequest.preview(
            self.bands,
            projection=self.projection,
            gamma=self.gamma,
            output_size=output_size,
            resample_method=resample_method,
        )

    def texture_request(
        self,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> RenderRequest:
        """Build a globe texture request from the same band recipe."""
        return RenderRequest.globe_texture(
            self.bands,
            gamma=self.gamma,
            output_size=output_size,
        )

    def still_export_request(self, output_path: str) -> "StillExportRequest":
        """Build a still-image export request."""
        return StillExportRequest(
            output_path=output_path,
            render_request=RenderRequest(
                bands=self.bands,
                projection=self.projection,
                gamma=self.gamma,
                quality_profile="export_high",
            ),
        )

    def video_export_request(
        self,
        output_path: str,
        *,
        fps: int = 10,
        pinned_driver_type: Optional[str] = None,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> "VideoExportRequest":
        """Build a video export request for the full time series."""
        return VideoExportRequest(
            output_path=output_path,
            render_request=RenderRequest(
                bands=self.bands,
                projection=self.projection,
                gamma=self.gamma,
                quality_profile="default",
                resample_method="bilinear",
                output_size=output_size,
            ),
            fps=fps,
            pinned_driver_type=pinned_driver_type,
        )

    def preview_signature(
        self,
        frame_index: int,
        output_size: Optional[Tuple[int, int]],
        *,
        need_3d_texture: bool,
        resample_method: str = "nearest",
    ) -> Tuple[object, ...]:
        """Build a stable preview signature for stale-render suppression."""
        return (
            *self.preview_request(output_size, resample_method=resample_method).cache_key(frame_index),
            bool(need_3d_texture),
        )


@dataclass(frozen=True)
class StillExportRequest:
    """Request for exporting one rendered image to disk."""

    output_path: str
    render_request: RenderRequest
    format: str = "auto"

    def resolved_format(self) -> str:
        """Resolve export format from explicit value or output file suffix."""
        if self.format != "auto":
            return self.format
        lower_path = self.output_path.lower()
        if lower_path.endswith((".tif", ".tiff")):
            return "geotiff"
        return "png"


@dataclass(frozen=True)
class VideoExportRequest:
    """Request for exporting a full time series to video."""

    output_path: str
    render_request: RenderRequest
    fps: int = 10
    pinned_driver_type: Optional[str] = None
