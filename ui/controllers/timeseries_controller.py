"""
Time-Series Controller.

Manages frame navigation, time-slider state, and frame loading.
Decouples time-series playback logic from MainWindow layout code.

Frame loading is performed in a background FrameLoaderWorker so the main
UI thread remains responsive while satellite HDF5/NetCDF files are opened.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.app_state import AppState
from utils.workers import FrameLoaderWorker

if TYPE_CHECKING:
    from core.manager import SatelliteImageManager

logger = logging.getLogger(__name__)


class TimeSeriesController(QObject):
    """
    Presenter/Controller for time-series frame navigation.

    Signals:
        frame_loaded(index, total, time_str): new frame is loaded.
        frame_loading():                      loading has started (use to show spinner).
        error(message):                       frame loading failed.
        status(message):                      status-bar update.
    """

    frame_loaded  = pyqtSignal(int, int, str)
    frame_loading = pyqtSignal()               # fires when background load starts
    error         = pyqtSignal(str)
    status        = pyqtSignal(str)

    def __init__(
        self,
        manager: SatelliteImageManager,
        state: AppState,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._state = state
        self._pinned_driver_type: Optional[str] = None
        self._bad_frame_indices: set[int] = set()

        # Async frame-load state
        self._frame_worker: Optional[FrameLoaderWorker] = None
        self._loading_index: int = -1   # frame index currently being loaded

    def set_file_groups(self, file_groups: List[List[str]]) -> None:
        """Store all time-series file groups in state."""
        self._cancel_current_worker()
        self._state.file_groups = list(file_groups) if file_groups else []
        self._state.current_frame_index = -1
        self._pinned_driver_type = None
        self._bad_frame_indices.clear()
        self._loading_index = -1

    def cancel_loading(self) -> None:
        """Cancel an in-progress frame load and clear transient loading state."""
        self._cancel_current_worker()
        self._loading_index = -1

    def shutdown(self, wait_ms: int = 300) -> None:
        """Stop worker and reset controller transient state."""
        if self._frame_worker and self._frame_worker.isRunning():
            self._frame_worker.cancel()
            self._frame_worker.wait(wait_ms)
        self._frame_worker = None
        self._loading_index = -1
        self._pinned_driver_type = None

    def load_frame(self, index: int, driver_type: Optional[str] = None) -> bool:
        """
        Start asynchronous loading of the frame at *index*.

        Returns True immediately once the background worker has been started
        (not when loading is complete).  Results are delivered via signals:
          - frame_loaded(index, total, time_str) on success
          - error(message) on failure
        """
        if not self._state.file_groups:
            logger.warning("[TSCtrl] No file groups loaded")
            return False

        total = self._state.total_frames
        if index < 0 or index >= total:
            logger.warning(f"[TSCtrl] Frame index {index} out of range [0, {total})")
            return False

        if driver_type:
            self._pinned_driver_type = driver_type

        # Cancel any in-progress load to prevent frame ordering races
        self._cancel_current_worker()

        files = self._state.file_groups[index]
        self._loading_index = index
        self.status.emit(f"Loading frame {index + 1}/{total}...")
        self.frame_loading.emit()

        worker = FrameLoaderWorker(
            self._manager, files, self._pinned_driver_type
        )
        self._frame_worker = worker
        worker.frame_loaded.connect(
            lambda t, idx=index: self._on_frame_loaded(idx, t)
        )
        worker.error.connect(
            lambda msg, idx=index: self._on_frame_error(idx, msg)
        )
        worker.finished.connect(lambda: self._on_worker_finished())
        worker.start()
        return True   # "worker started" — not "frame loaded"

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def go_to_next(self) -> None:
        """Navigate to the next non-bad frame."""
        start = self._state.current_frame_index + 1
        for idx in range(start, self._state.total_frames):
            if idx not in self._bad_frame_indices:
                self.load_frame(idx)
                return
        self.error.emit("No further loadable frame found.")

    def go_to_prev(self) -> None:
        """Navigate to the previous non-bad frame."""
        start = self._state.current_frame_index - 1
        for idx in range(start, -1, -1):
            if idx not in self._bad_frame_indices:
                self.load_frame(idx)
                return
        self.error.emit("No previous loadable frame found.")

    def can_go_next(self) -> bool:
        return self._state.current_frame_index < self._state.total_frames - 1

    def can_go_prev(self) -> bool:
        return self._state.current_frame_index > 0

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_frame_loaded(self, index: int, time_str: str) -> None:
        """Called (from worker thread via signal) when a frame load succeeds."""
        if index != self._loading_index:
            # A newer load was started before this one finished — discard stale result
            logger.debug(f"[TSCtrl] Stale frame result {index} (loading {self._loading_index}), discarding")
            return

        total = self._state.total_frames
        self._state.current_frame_index = index
        self._bad_frame_indices.discard(index)
        if self._pinned_driver_type is None:
            self._pinned_driver_type = self._manager.current_driver_type
        self.frame_loaded.emit(index, total, time_str)

    def _on_frame_error(self, index: int, msg: str) -> None:
        """Called (from worker thread via signal) when a frame load fails."""
        if index != self._loading_index:
            return
        full_msg = f"Failed to load frame {index}: {msg}"
        logger.error(f"[TSCtrl] {full_msg}")
        self._bad_frame_indices.add(index)
        self.error.emit(full_msg)

    def _on_worker_finished(self) -> None:
        """Clean up worker reference after QThread finishes."""
        self._frame_worker = None

    def _cancel_current_worker(self) -> None:
        """Cancel and wait for the currently running worker, if any."""
        if self._frame_worker and self._frame_worker.isRunning():
            self._frame_worker.cancel()
            self._frame_worker.wait(200)   # give it up to 200 ms to stop
        self._frame_worker = None
