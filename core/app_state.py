"""
Application state container for the viewer UI.

This centralizes mutable UI state so controllers and views can share one
runtime model instead of duplicating transient values across widgets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    from core.scene import NormalizedScene


@dataclass
class AppState:
    """Centralized mutable state for the satellite image viewer."""

    # ------------------------------------------------------------------
    # Enhancement settings
    # ------------------------------------------------------------------
    gamma: float = 1.0
    opacity: float = 1.0

    # ------------------------------------------------------------------
    # Band selection
    # ------------------------------------------------------------------
    selected_bands: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Time series / scene navigation
    # ------------------------------------------------------------------
    file_groups: List[List[str]] = field(default_factory=list)
    """Compatibility time slices used by existing export/playback paths."""

    normalized_scenes: List[NormalizedScene] = field(default_factory=list)
    """Preferred metadata-first frame source for scene-driven workflows."""

    current_frame_index: int = -1

    # ------------------------------------------------------------------
    # Cached render results (2D)
    # ------------------------------------------------------------------
    cached_img: Optional[np.ndarray] = field(default=None, repr=False)
    cached_extent: Optional[Tuple[float, float, float, float]] = None
    cached_area_def: Optional[Any] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # 3D texture cache
    # ------------------------------------------------------------------
    img_3d: Optional[np.ndarray] = field(default=None, repr=False)
    extent_3d: Optional[Tuple[float, float, float, float]] = None
    proj_3d: Optional[str] = None

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    current_projection: str = "geostationary_native"

    def clear_time_series(self) -> None:
        """Reset all frame/scene navigation state."""
        self.file_groups = []
        self.normalized_scenes = []
        self.current_frame_index = -1

    def set_file_groups(self, file_groups: Sequence[Sequence[str]]) -> None:
        """Replace the current time series with raw file groups."""
        self.file_groups = [list(group) for group in file_groups] if file_groups else []
        self.normalized_scenes = []
        self.current_frame_index = -1

    def set_normalized_scenes(self, scenes: Sequence[NormalizedScene]) -> None:
        """Replace the current time series with normalized scenes."""
        self.normalized_scenes = list(scenes) if scenes else []
        self.file_groups = [scene.file_paths for scene in self.normalized_scenes]
        self.current_frame_index = -1

    def clear_image_cache(self) -> None:
        """Invalidate 2D and 3D image caches."""
        self.cached_img = None
        self.cached_extent = None
        self.cached_area_def = None
        self.img_3d = None
        self.extent_3d = None
        self.proj_3d = None

    @property
    def has_data(self) -> bool:
        """True if at least one time frame has been loaded."""
        return self.total_frames > 0 and self.current_frame_index >= 0

    @property
    def total_frames(self) -> int:
        """Total number of time frames available."""
        if self.normalized_scenes:
            return len(self.normalized_scenes)
        return len(self.file_groups)

    @property
    def current_scene(self) -> Optional[NormalizedScene]:
        """Normalized scene for the current frame, if available."""
        if (
            self.normalized_scenes
            and 0 <= self.current_frame_index < len(self.normalized_scenes)
        ):
            return self.normalized_scenes[self.current_frame_index]
        return None

    @property
    def current_files(self) -> List[str]:
        """File paths for the currently loaded frame."""
        return self.get_frame_files(self.current_frame_index)

    def get_frame_files(self, index: int) -> List[str]:
        """Return file paths for an arbitrary frame index."""
        if index < 0:
            return []
        if index < len(self.normalized_scenes):
            return self.normalized_scenes[index].file_paths
        if index < len(self.file_groups):
            return self.file_groups[index]
        return []
