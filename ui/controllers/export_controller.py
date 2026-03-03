"""
Export Controller.

Manages PNG, GeoTIFF, and video export operations.
Decouples export logic and worker lifecycle from MainWindow.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.app_state import AppState
from utils.workers import VideoExportWorker

if TYPE_CHECKING:
    from core.manager import SatelliteImageManager

logger = logging.getLogger(__name__)


class ExportController(QObject):
    """
    Presenter/Controller for image and video export.

    Signals:
        export_finished(path): still-image export completed successfully.
        export_error(message): still-image export failed.
        video_progress(current, total): video export frame progress.
        video_finished(path): video export completed.
        video_error(message): video export failed.
        status(message): status-bar update.
    """

    export_finished = pyqtSignal(str)
    export_error = pyqtSignal(str)
    video_progress = pyqtSignal(int, int)
    video_finished = pyqtSignal(str)
    video_error = pyqtSignal(str)
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
        self._vid_worker: Optional[VideoExportWorker] = None

    # ------------------------------------------------------------------
    # Still-image export
    # ------------------------------------------------------------------

    def export_still(self, output_path: str, bands: List[str], gamma: float, projection: str) -> None:
        """Export current view as PNG or GeoTIFF."""
        fmt = "geotiff" if output_path.lower().endswith(".tif") else "png"
        self.status.emit(f"Exporting {fmt.upper()}...")

        try:
            result = self._manager.export_image(
                output_path=output_path,
                bands=bands,
                gamma=gamma,
                proj_name=projection,
                format=fmt,
            )
            if result.get("success"):
                self.export_finished.emit(output_path)
                self.status.emit("Export complete.")
            else:
                raise RuntimeError("export_image() returned unsuccessful result")
        except Exception as exc:
            msg = f"Export failed: {exc}"
            logger.error(f"[ExportCtrl] {msg}")
            self.export_error.emit(msg)
            self.status.emit("Export failed.")

    # ------------------------------------------------------------------
    # Video export
    # ------------------------------------------------------------------

    def start_video_export(
        self,
        output_path: str,
        bands: List[str],
        gamma: float,
        projection: str,
        fps: int = 10,
    ) -> bool:
        """Start background video export for the full time series."""
        if self._vid_worker and self._vid_worker.isRunning():
            logger.warning("[ExportCtrl] Video export already in progress")
            return False
        if not self._state.file_groups:
            self.video_error.emit("No time-series data loaded.")
            return False

        params = {
            "gamma": gamma,
            "proj_name": projection,
            "quality_profile": "default",
            "resample_method": "bilinear",
            "driver_type": self._manager.current_driver_type,
            # Worker will cap to 1920x1080 for balanced-quality export.
            "output_size": None,
        }
        worker = VideoExportWorker(
            self._manager,
            self._state.file_groups,
            output_path,
            bands,
            params,
            fps=fps,
        )
        self._vid_worker = worker
        worker.progress.connect(self.video_progress)
        worker.finished.connect(self._on_video_finished)
        worker.error.connect(self.video_error)
        worker.finished.connect(lambda _: self._cleanup_video_worker())
        worker.start()
        self.status.emit("Video export started...")
        return True

    def cancel_video_export(self) -> None:
        """Request cancellation of an in-progress video export."""
        if self._vid_worker and self._vid_worker.isRunning():
            self._vid_worker.cancel()
            logger.info("[ExportCtrl] Video export cancellation requested")

    def shutdown(self, wait_ms: int = 3000) -> None:
        """Cancel and wait for video worker during app shutdown."""
        if self._vid_worker is None:
            return
        if self._vid_worker.isRunning():
            self._vid_worker.cancel()
            self._vid_worker.wait(wait_ms)
        self._vid_worker.deleteLater()
        self._vid_worker = None

    @property
    def is_video_exporting(self) -> bool:
        return self._vid_worker is not None and self._vid_worker.isRunning()

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_video_finished(self, path: str) -> None:
        self.video_finished.emit(path)
        self.status.emit("Video export complete.")

    def _cleanup_video_worker(self) -> None:
        if self._vid_worker is not None and not self._vid_worker.isRunning():
            self._vid_worker.deleteLater()
            self._vid_worker = None
