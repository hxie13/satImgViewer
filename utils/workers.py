"""
Background Workers

QThread workers for async image processing and video export.
Uses SatelliteImageManager API.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal
import threading
import time
import cv2
import numpy as np
import gc
import logging

from core.product_requests import RenderRequest, VideoExportRequest

logger = logging.getLogger(__name__)


class FrameLoaderWorker(QThread):
    """
    Background worker for loading a single satellite data frame.

    Executes manager.load_scene() / manager.reload_current() / manager.load_files() in a dedicated
    QThread so the main UI thread remains fully responsive during file I/O.

    Signals:
        frame_loaded(time_str): Emitted on successful load with the frame's
            start-time string extracted from file metadata.
        error(message): Emitted when loading fails.
    """

    frame_loaded = pyqtSignal(str)   # time_str on success
    error        = pyqtSignal(str)   # error message on failure

    def __init__(self, manager, files=None, pinned_driver_type=None, scene=None):
        super().__init__()
        self.manager = manager
        self.files = list(files) if files else []
        self.pinned_driver_type = pinned_driver_type
        self.scene = scene
        self._cancel_event = threading.Event()

    def cancel(self):
        """Request cooperative cancellation (checked before emitting signals)."""
        self._cancel_event.set()

    def run(self):
        if self._cancel_event.is_set():
            return
        try:
            ok = False
            if self.scene is not None:
                ok = self.manager.load_scene(self.scene, reuse_session=True)
            else:
                # Prefer reload_current: reuses existing driver, skips factory detection
                if self.manager.current_driver is not None:
                    ok = self.manager.reload_current(self.files)

                if not ok and not self._cancel_event.is_set():
                    kwargs = {"reuse_session": True}
                    if self.pinned_driver_type:
                        kwargs["pinned_driver_type"] = self.pinned_driver_type
                    ok = self.manager.load_files(self.files, **kwargs)

            if self._cancel_event.is_set():
                return

            if not ok:
                self.error.emit("Frame loading failed")
                return

            meta = self.manager.get_metadata()
            time_str = (
                meta.get("start_time")
                or getattr(self.scene, "nominal_time", None)
                or "Unknown"
            )
            self.frame_loaded.emit(time_str)

        except Exception as e:
            if not self._cancel_event.is_set():
                self.error.emit(str(e))


class VideoExportWorker(QThread):
    """
    Worker for exporting time-series scenes/frames to video.
    """
    progress = pyqtSignal(int, int)  # (current, total)
    finished = pyqtSignal(str)       # output_path
    error = pyqtSignal(str)

    def __init__(
        self,
        manager,
        request: VideoExportRequest,
        *,
        file_groups=None,
        scenes=None,
    ):
        """
        Initialize worker.

        Args:
            manager: SatelliteImageManager instance
            request: Video export request
            file_groups: Legacy list of file groups (each group = one time point)
            scenes: Preferred list of normalized scenes for export
        """
        super().__init__()
        self.manager = manager
        self.request = request
        self.file_groups = [list(group) for group in file_groups] if file_groups else []
        self.scenes = list(scenes) if scenes else []
        self._cancel_event = threading.Event()
        self._load_times_ms = []
        self._process_times_ms = []
        self._encode_times_ms = []

    def _frame_count(self) -> int:
        if self.scenes:
            return len(self.scenes)
        return len(self.file_groups)

    def _load_frame_source(
        self,
        index: int,
        *,
        reuse_session: bool,
        pinned_driver_type: Optional[str],
    ) -> bool:
        """Load one export frame from either normalized scenes or raw file groups."""
        if self.scenes:
            if index < 0 or index >= len(self.scenes):
                return False
            return self.manager.load_scene(self.scenes[index], reuse_session=reuse_session)

        if index < 0 or index >= len(self.file_groups):
            return False

        files = self.file_groups[index]
        if reuse_session:
            ok = self.manager.reload_current(files)
            if ok:
                return True
        return self.manager.load_files(
            files,
            reuse_session=reuse_session,
            pinned_driver_type=pinned_driver_type,
        )

    def cancel(self):
        """Cancel export."""
        self._cancel_event.set()

    def run(self):
        """Execute video export."""
        try:
            total = self._frame_count()
            if total == 0:
                raise ValueError("No frames to export")

            writer = None
            written_frames = 0
            render_request = self.request.render_request
            driver_type = self.request.pinned_driver_type
            output_size = self._balanced_output_size(render_request.output_size)
            target_w, target_h = int(output_size[0]), int(output_size[1])
            frame_request = render_request.with_output_size(output_size)

            # Initialize (or reuse) a driver session once before frame loop.
            init_t0 = time.perf_counter()
            ok = self._load_frame_source(
                0,
                reuse_session=False,
                pinned_driver_type=driver_type,
            )
            init_ms = (time.perf_counter() - init_t0) * 1000.0
            if not ok:
                raise RuntimeError("Failed to initialize export session")

            for i in range(total):
                if self._cancel_event.is_set():
                    break

                # Per-frame load: first frame already loaded, following frames only reload current driver.
                load_t0 = time.perf_counter()
                if i == 0:
                    load_ms = init_ms
                else:
                    ok = self._load_frame_source(
                        i,
                        reuse_session=True,
                        pinned_driver_type=driver_type,
                    )
                    if not ok:
                        logger.warning(f"Frame {i} load failed")
                        continue
                    load_ms = (time.perf_counter() - load_t0) * 1000.0
                self._load_times_ms.append(load_ms)

                try:
                    process_t0 = time.perf_counter()
                    img_data, _ = self.manager.process_render_request(frame_request)
                    process_ms = (time.perf_counter() - process_t0) * 1000.0
                    self._process_times_ms.append(process_ms)
                except Exception as e:
                    logger.warning(f"Frame {i} process failed: {e}")
                    continue

                if img_data is None:
                    continue

                encode_t0 = time.perf_counter()
                # Convert to uint8
                img_u8 = np.nan_to_num(np.clip(img_data, 0, 1) * 255).astype(np.uint8)

                # Convert RGB to BGR for OpenCV
                if img_u8.ndim == 3:
                    frame = cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR)
                else:
                    frame = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2BGR)

                # VideoWriter requires fixed frame size for all frames.
                # Some sources (e.g. FY3D swath fallback paths) may output
                # variable-sized frames per timestamp, so normalize here.
                height, width = frame.shape[:2]
                if width != target_w or height != target_h:
                    interpolation = cv2.INTER_AREA if (width > target_w or height > target_h) else cv2.INTER_LINEAR
                    frame = cv2.resize(frame, (target_w, target_h), interpolation=interpolation)

                # Initialize writer on first frame
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    writer = cv2.VideoWriter(
                        self.request.output_path,
                        fourcc,
                        self.request.fps,
                        (target_w, target_h),
                    )
                    if not writer.isOpened():
                        raise RuntimeError("Could not open video writer")

                writer.write(frame)
                written_frames += 1
                encode_ms = (time.perf_counter() - encode_t0) * 1000.0
                self._encode_times_ms.append(encode_ms)
                self.progress.emit(i + 1, total)
                logger.info(
                    "[Perf][Video] frame=%d/%d load_ms=%.1f process_ms=%.1f encode_ms=%.1f",
                    i + 1, total, load_ms, process_ms, encode_ms
                )

                # Periodic cleanup
                if (i + 1) % 20 == 0:
                    gc.collect()

            if writer:
                writer.release()

            if not self._cancel_event.is_set():
                if written_frames == 0:
                    raise RuntimeError("Video export produced zero frames")
                self._log_perf_summary()
                self.finished.emit(self.request.output_path)
                logger.info(f"Video export complete: {self.request.output_path}")

        except Exception as e:
            logger.error(f"Video export failed: {e}")
            self.error.emit(str(e))

    @staticmethod
    def _balanced_output_size(size):
        """Cap export size to a balanced 1920x1080 budget."""
        max_w, max_h = 1920, 1080
        if not size:
            return (max_w, max_h)
        try:
            w, h = int(size[0]), int(size[1])
        except Exception:
            return (max_w, max_h)
        if w <= 0 or h <= 0:
            return (max_w, max_h)
        scale = min(1.0, max_w / float(w), max_h / float(h))
        return (max(16, int(w * scale)), max(16, int(h * scale)))

    @staticmethod
    def _p50_p90(values):
        if not values:
            return (0.0, 0.0)
        arr = np.asarray(values, dtype=np.float32)
        return (float(np.percentile(arr, 50)), float(np.percentile(arr, 90)))

    def _log_perf_summary(self):
        load_p50, load_p90 = self._p50_p90(self._load_times_ms)
        proc_p50, proc_p90 = self._p50_p90(self._process_times_ms)
        enc_p50, enc_p90 = self._p50_p90(self._encode_times_ms)
        logger.info(
            "[Perf][Video][Summary] load_p50=%.1f load_p90=%.1f process_p50=%.1f process_p90=%.1f encode_p50=%.1f encode_p90=%.1f",
            load_p50, load_p90, proc_p50, proc_p90, enc_p50, enc_p90
        )


class ImageLoaderWorker(QThread):
    """
    Worker for async image generation.

    Uses SatelliteImageManager instance for processing.
    """
    data_ready = pyqtSignal(object, object)
    error = pyqtSignal(str)

    def __init__(self, manager, request: RenderRequest):
        """
        Initialize worker.

        Args:
            manager: SatelliteImageManager instance
            request: Normalized render request
        """
        super().__init__()
        self.manager = manager
        self.request = request
        self._cancel_event = threading.Event()

    def cancel(self):
        """Request cooperative cancellation."""
        self._cancel_event.set()

    def run(self):
        """Execute image generation."""
        try:
            if self._cancel_event.is_set():
                return
            logger.info(f"[Worker] Starting image generation for bands={self.request.bands}")
            t0 = time.time()

            img, area = self.manager.process_render_request(self.request)

            t1 = time.time()
            logger.info(f"[Worker] Image generated in {t1 - t0:.2f}s")
            logger.info(f"[Worker] Emitting data_ready with shape={getattr(img, 'shape', 'unknown')}")

            if self._cancel_event.is_set():
                return
            self.data_ready.emit(img, area)

        except Exception as e:
            logger.error(f"[Worker] Failed: {e}")
            if not self._cancel_event.is_set():
                self.error.emit(str(e))
