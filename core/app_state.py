"""
Application State — Centralised UI State Container

A single dataclass that holds all mutable application state so that:
  - State is never spread across multiple instance attributes in MainWindow
  - Controllers can read/write state without coupling to the UI layout
  - AppState can be serialised for session restore (future)

Usage::

    state = AppState()
    state.gamma = 1.5
    state.current_frame_index = 2
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any

import numpy as np


@dataclass
class AppState:
    """Centralised mutable state for the satellite image viewer."""

    # ------------------------------------------------------------------
    # Enhancement settings
    # ------------------------------------------------------------------
    gamma: float = 1.0
    """Current gamma correction value (slider range: 0.5 – 3.0)."""

    opacity: float = 1.0
    """3D overlay opacity (0.0 – 1.0, mapped from slider 0 – 100)."""

    # ------------------------------------------------------------------
    # Band selection
    # ------------------------------------------------------------------
    selected_bands: List[str] = field(default_factory=list)
    """Ordered list of selected canonical band names.  Length is 1 (mono)
    or 3 (RGB)."""

    # ------------------------------------------------------------------
    # Time series / frame management
    # ------------------------------------------------------------------
    file_groups: List[List[str]] = field(default_factory=list)
    """All time slices: ``file_groups[t]`` is the list of files for frame t."""

    current_frame_index: int = -1
    """Currently displayed frame index (–1 = no data loaded)."""

    # ------------------------------------------------------------------
    # Cached render results (2D)
    # ------------------------------------------------------------------
    cached_img: Optional[np.ndarray] = field(default=None, repr=False)
    """Most recently generated image array (float32, 0–1)."""

    cached_extent: Optional[Tuple[float, float, float, float]] = None
    """Geographic extent of the cached image: (west, east, south, north)."""

    cached_area_def: Optional[Any] = field(default=None, repr=False)
    """pyresample AreaDefinition associated with cached_img."""

    # ------------------------------------------------------------------
    # 3D texture cache
    # ------------------------------------------------------------------
    img_3d: Optional[np.ndarray] = field(default=None, repr=False)
    """Plate-Carrée image dedicated to the 3D globe texture."""

    extent_3d: Optional[Tuple[float, float, float, float]] = None
    """Geographic extent of img_3d: (west, east, south, north)."""

    proj_3d: Optional[str] = None
    """Projection key used to generate img_3d ('plate_carree_global')."""

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    current_projection: str = 'geostationary_native'
    """Current projection key (matches keys in PREDEFINED_PROJECTIONS)."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        return bool(self.file_groups) and self.current_frame_index >= 0

    @property
    def total_frames(self) -> int:
        """Total number of time frames available."""
        return len(self.file_groups)

    @property
    def current_files(self) -> List[str]:
        """File paths for the currently loaded frame."""
        if self.has_data:
            return self.file_groups[self.current_frame_index]
        return []
