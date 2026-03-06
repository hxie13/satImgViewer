"""
Image View Controller.

Manages image generation, worker lifecycle, and 3D texture logic.
Separates image-processing decisions from the UI layout in MainWindow.
"""
from __future__ import annotations

from collections import OrderedDict
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from core.app_state import AppState
from core.config import PROJECTION_GRID_EXTENTS, PROJECTION_GRID_SHAPES
from core.geo_utils import get_geographic_extent
from core.product_requests import RenderRequest
from utils.workers import ImageLoaderWorker

if TYPE_CHECKING:
    from core.manager import SatelliteImageManager

logger = logging.getLogger(__name__)


class ImageViewController(QObject):
    """
    Presenter/Controller for 2D and 3D image rendering.

    Signals:
        image_ready(img, extent, area_def): 2D image is ready to display.
        texture_3d_ready(img, extent): 3D globe texture is ready.
        error(message): processing failed.
        status(message): status-bar text update.
    """

    image_ready = pyqtSignal(object, object, object)  # img, extent, area_def
    texture_3d_ready = pyqtSignal(object, object)  # img, extent
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(
        self,
        manager: SatelliteImageManager,
        state: AppState,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._state = state
        self._worker: Optional[ImageLoaderWorker] = None
        self._worker_3d: Optional[ImageLoaderWorker] = None
        self._retired_workers: List[ImageLoaderWorker] = []

        # Request sequence guards against stale worker results.
        self._request_seq = 0
        self._request_seq_3d = 0

        # Sequence -> request metadata for stale-result filtering and behavior.
        self._seq_to_2d_key = {}
        self._seq_need_3d = {}
        self._seq_to_3d_key = {}

        # LRU caches
        self._preview_cache_size = 6
        self._texture_cache_size = 2
        self._preview_cache = OrderedDict()  # key -> (img, extent, area_def)
        self._texture_cache = OrderedDict()  # key -> (img, extent)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_render_request(
        self,
        request: RenderRequest,
        *,
        need_3d_texture: bool = False,
    ) -> None:
        """Start background image generation for a normalized render request."""
        frame_idx = self._state.current_frame_index
        req_key = request.cache_key(frame_idx)

        # LRU cache hit: emit immediately.
        cached = self._preview_cache.get(req_key)
        if cached is not None:
            img, extent, area_def = cached
            self._preview_cache.move_to_end(req_key)
            self._state.cached_img = img
            self._state.cached_extent = extent
            self._state.cached_area_def = area_def
            self.image_ready.emit(img, extent, area_def)
            self.status.emit("Image ready (cache hit).")
            return

        self._state.selected_bands = list(request.bands)
        self._state.current_projection = request.projection
        self._state.gamma = float(request.gamma)

        self._cancel_and_retire("_worker")

        self._request_seq += 1
        seq = self._request_seq
        self._seq_to_2d_key[seq] = req_key
        self._seq_need_3d[seq] = bool(need_3d_texture)
        worker = ImageLoaderWorker(self._manager, request)
        self._worker = worker

        worker.data_ready.connect(
            lambda img, area_def, s=seq: self._on_2d_data_ready(img, area_def, s)
        )
        worker.error.connect(lambda msg, s=seq: self._on_2d_error(msg, s))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w, "_worker"))
        worker.start()
        self.status.emit("Generating image...")

    def generate_image(
        self,
        bands: list,
        projection: str,
        gamma: float,
        output_size: Optional[Tuple[int, int]] = None,
        quality_profile: str = "preview_fast",
        resample_method: str = "nearest",
        need_3d_texture: bool = False,
    ) -> None:
        """Backward-compatible wrapper for 2D image generation."""
        request = RenderRequest(
            bands=tuple(bands),
            projection=projection,
            gamma=gamma,
            output_size=output_size,
            quality_profile=quality_profile,
            resample_method=resample_method,
        )
        self.generate_render_request(request, need_3d_texture=need_3d_texture)

    def generate_texture_request(self, request: RenderRequest) -> None:
        """Start background generation of a normalized 3D texture request."""
        frame_idx = self._state.current_frame_index
        req_key = request.cache_key(frame_idx)

        cached = self._texture_cache.get(req_key)
        if cached is not None:
            img, extent = cached
            self._texture_cache.move_to_end(req_key)
            self._state.img_3d = img
            self._state.extent_3d = extent
            self._state.proj_3d = "plate_carree_global"
            self.texture_3d_ready.emit(img, extent)
            return

        self._cancel_and_retire("_worker_3d")

        self._request_seq_3d += 1
        seq = self._request_seq_3d
        self._seq_to_3d_key[seq] = req_key
        worker = ImageLoaderWorker(self._manager, request)
        self._worker_3d = worker

        worker.data_ready.connect(
            lambda img, area_def, s=seq: self._on_3d_texture_ready(img, area_def, s)
        )
        worker.error.connect(lambda msg, s=seq: self._on_3d_error(msg, s))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w, "_worker_3d"))
        worker.start()

    def generate_3d_texture(
        self,
        bands: list,
        gamma: float,
        output_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Backward-compatible wrapper for 3D texture generation."""
        request = RenderRequest.globe_texture(
            bands=tuple(bands),
            gamma=gamma,
            output_size=output_size,
        )
        self.generate_texture_request(request)

    def cancel(self) -> None:
        """Request cancellation for running workers."""
        self._cancel_and_retire("_worker")
        self._cancel_and_retire("_worker_3d")

    def clear_cache(self) -> None:
        """Clear in-memory preview/texture caches."""
        self._preview_cache.clear()
        self._texture_cache.clear()
        self._seq_to_2d_key.clear()
        self._seq_need_3d.clear()
        self._seq_to_3d_key.clear()

    def shutdown(self, wait_ms: int = 2000) -> None:
        """Cancel all workers and wait briefly to avoid QThread teardown warnings."""
        self.cancel()
        workers = [w for w in (self._worker, self._worker_3d, *self._retired_workers) if w]
        for worker in workers:
            if worker.isRunning():
                worker.wait(wait_ms)
            worker.deleteLater()
        self._worker = None
        self._worker_3d = None
        self._retired_workers.clear()

    # ------------------------------------------------------------------
    # Worker lifecycle helpers
    # ------------------------------------------------------------------

    def _cancel_and_retire(self, attr_name: str) -> None:
        """Cancel an existing worker and keep a strong ref until it fully exits."""
        worker = getattr(self, attr_name, None)
        if worker is None:
            return

        if worker.isRunning():
            worker.cancel()
            if worker not in self._retired_workers:
                self._retired_workers.append(worker)
                worker.finished.connect(lambda w=worker: self._cleanup_retired_worker(w))
        else:
            worker.deleteLater()

        setattr(self, attr_name, None)

    def _on_worker_finished(self, worker: ImageLoaderWorker, attr_name: str) -> None:
        if getattr(self, attr_name, None) is worker:
            setattr(self, attr_name, None)
        if worker in self._retired_workers:
            self._retired_workers.remove(worker)
        worker.deleteLater()

    def _cleanup_retired_worker(self, worker: ImageLoaderWorker) -> None:
        if worker in self._retired_workers:
            self._retired_workers.remove(worker)
        worker.deleteLater()

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_2d_error(self, message: str, seq: int) -> None:
        """Emit errors only for active request sequence."""
        self._seq_to_2d_key.pop(seq, None)
        self._seq_need_3d.pop(seq, None)
        if seq != self._request_seq:
            return
        self.error.emit(message)

    def _on_2d_data_ready(self, img, area_def, seq: int) -> None:
        """Slot: 2D image worker finished."""
        req_key = self._seq_to_2d_key.pop(seq, None)
        need_3d_texture = self._seq_need_3d.pop(seq, False)
        if seq != self._request_seq:
            logger.debug("[ImageCtrl] Dropped stale 2D result")
            return

        h, w = img.shape[:2]
        grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
        if grid_proj is not None:
            extent = PROJECTION_GRID_EXTENTS[grid_proj]
        else:
            extent = get_geographic_extent(area_def)

        self._state.cached_img = img
        self._state.cached_extent = extent
        self._state.cached_area_def = area_def
        if req_key is not None:
            self._put_lru(
                self._preview_cache,
                req_key,
                (img, extent, area_def),
                self._preview_cache_size,
            )

        self.image_ready.emit(img, extent, area_def)
        self.status.emit("Image ready.")

        if need_3d_texture and self._state.selected_bands:
            self.generate_3d_texture(
                self._state.selected_bands,
                self._state.gamma,
                output_size=(1600, 800),
            )

    def _on_3d_error(self, message: str, seq: int) -> None:
        self._seq_to_3d_key.pop(seq, None)
        if seq != self._request_seq_3d:
            return
        logger.warning(f"[ImageCtrl] 3D texture error: {message}")

    def _on_3d_texture_ready(self, img, area_def, seq: int) -> None:
        """Slot: 3D texture worker finished."""
        req_key = self._seq_to_3d_key.pop(seq, None)
        if seq != self._request_seq_3d:
            logger.debug("[ImageCtrl] Dropped stale 3D result")
            return

        h, w = img.shape[:2]
        grid_proj = PROJECTION_GRID_SHAPES.get((w, h))
        if grid_proj is not None:
            extent = PROJECTION_GRID_EXTENTS[grid_proj]
        else:
            extent = get_geographic_extent(area_def)

        self._state.img_3d = img
        self._state.extent_3d = extent
        self._state.proj_3d = "plate_carree_global"
        if req_key is not None:
            self._put_lru(
                self._texture_cache,
                req_key,
                (img, extent),
                self._texture_cache_size,
            )
        self.texture_3d_ready.emit(img, extent)

    @staticmethod
    def _put_lru(cache: OrderedDict, key, value, max_size: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)
