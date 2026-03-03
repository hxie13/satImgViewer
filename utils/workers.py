"""
Background Workers

QThread workers for async image processing and video export.
Uses SatelliteImageManager API.
"""
from PyQt6.QtCore import QThread, pyqtSignal
import time
import cv2
import numpy as np
import gc
import logging

logger = logging.getLogger(__name__)


class FrameLoaderWorker(QThread):
    """
    Background worker for loading a single satellite data frame.

    Executes manager.reload_current() / manager.load_files() in a dedicated
    QThread so the main UI thread remains fully responsive during file I/O.

    Signals:
        frame_loaded(time_str): Emitted on successful load with the frame's
            start-time string extracted from file metadata.
        error(message): Emitted when loading fails.
    """

    frame_loaded = pyqtSignal(str)   # time_str on success
    error        = pyqtSignal(str)   # error message on failure

    def __init__(self, manager, files, pinned_driver_type=None):
        super().__init__()
        self.manager = manager
        self.files = files
        self.pinned_driver_type = pinned_driver_type
        self._is_cancelled = False

    def cancel(self):
        """Request cooperative cancellation (checked before emitting signals)."""
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return
        try:
            ok = False
            # Prefer reload_current: reuses existing driver, skips factory detection
            if self.manager.current_driver is not None:
                ok = self.manager.reload_current(self.files)

            if not ok and not self._is_cancelled:
                kwargs = {"reuse_session": True}
                if self.pinned_driver_type:
                    kwargs["pinned_driver_type"] = self.pinned_driver_type
                ok = self.manager.load_files(self.files, **kwargs)

            if self._is_cancelled:
                return

            if not ok:
                self.error.emit("Frame loading failed")
                return

            meta = self.manager.get_metadata()
            time_str = meta.get("start_time", "Unknown")
            self.frame_loaded.emit(time_str)

        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(str(e))


class VideoExportWorker(QThread):
    """
    Worker for exporting time-series to video.

    Uses SatelliteImageManager instance for processing.
    """
    progress = pyqtSignal(int, int)  # (current, total)
    finished = pyqtSignal(str)       # output_path
    error = pyqtSignal(str)

    def __init__(self, manager, file_groups, output_path, bands, params, fps=10):
        """
        Initialize worker.

        Args:
            manager: SatelliteImageManager instance
            file_groups: List of file groups (each group = one time point)
            output_path: Output video path
            bands: Band names to use
            params: Processing parameters dict
            fps: Video frames per second
        """
        super().__init__()
        self.manager = manager
        self.file_groups = file_groups
        self.output_path = output_path
        self.bands = bands
        self.params = params
        self.fps = fps
        self._is_cancelled = False
        self._load_times_ms = []
        self._process_times_ms = []
        self._encode_times_ms = []

    def cancel(self):
        """Cancel export."""
        self._is_cancelled = True

    def run(self):
        """Execute video export."""
        try:
            total = len(self.file_groups)
            if total == 0:
                raise ValueError("No frames to export")

            writer = None
            proj_name = self.params.get('proj_name', 'plate_carree_global')
            gamma = self.params.get('gamma', 1.0)
            quality_profile = self.params.get('quality_profile', 'export_high')
            resample_method = self.params.get('resample_method', 'bilinear')
            driver_type = self.params.get('driver_type')
            output_size = self._balanced_output_size(self.params.get('output_size'))

            # Initialize (or reuse) a driver session once before frame loop.
            init_t0 = time.perf_counter()
            ok = self.manager.load_files(
                self.file_groups[0],
                reuse_session=True,
                pinned_driver_type=driver_type,
            )
            init_ms = (time.perf_counter() - init_t0) * 1000.0
            if not ok:
                raise RuntimeError("Failed to initialize export session")

            for i, files in enumerate(self.file_groups):
                if self._is_cancelled:
                    break

                # Per-frame load: first frame already loaded, following frames only reload current driver.
                load_t0 = time.perf_counter()
                if i == 0:
                    load_ms = init_ms
                else:
                    ok = self.manager.reload_current(files)
                    if not ok:
                        ok = self.manager.load_files(
                            files,
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
                    img_data, _ = self.manager.process_image(
                        bands=self.bands,
                        gamma=gamma,
                        proj_name=proj_name,
                        size=output_size,
                        resample_method=resample_method,
                        quality_profile=quality_profile,
                    )
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

                height, width, _ = frame.shape

                # Initialize writer on first frame
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (width, height))
                    if not writer.isOpened():
                        raise RuntimeError("Could not open video writer")

                writer.write(frame)
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

            if not self._is_cancelled:
                self._log_perf_summary()
                self.finished.emit(self.output_path)
                logger.info(f"Video export complete: {self.output_path}")

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

    def __init__(self, manager, bands, params=None):
        """
        Initialize worker.

        Args:
            manager: SatelliteImageManager instance
            bands: List of band names
            params: Optional processing parameters dict
        """
        super().__init__()
        self.manager = manager
        self.bands = bands
        self.params = params or {}
        self._is_cancelled = False

    def cancel(self):
        """Request cooperative cancellation."""
        self._is_cancelled = True

    def run(self):
        """Execute image generation."""
        try:
            if self._is_cancelled:
                return
            logger.info(f"[Worker] Starting image generation for bands={self.bands}")
            t0 = time.time()

            # Use SatelliteImageManager API
            proj_name = self.params.get('proj_name', 'geostationary_native')
            img, area = self.manager.process_image(
                bands=self.bands,
                gamma=self.params.get('gamma', 1.0),
                proj_name=proj_name,
                size=self.params.get('output_size'),
                resample_method=self.params.get('resample_method'),
                quality_profile=self.params.get('quality_profile', 'default'),
            )

            t1 = time.time()
            logger.info(f"[Worker] Image generated in {t1 - t0:.2f}s")
            logger.info(f"[Worker] Emitting data_ready with shape={getattr(img, 'shape', 'unknown')}")

            if self._is_cancelled:
                return
            self.data_ready.emit(img, area)

        except Exception as e:
            logger.error(f"[Worker] Failed: {e}")
            if not self._is_cancelled:
                self.error.emit(str(e))


class BatchExportWorker(QThread):
    """
    Worker for batch image export to files.
    """
    progress = pyqtSignal(int, int)  # (current, total)
    finished = pyqtSignal(str, list)  # (output_dir, exported_files)
    error = pyqtSignal(str)

    def __init__(self, manager, file_groups, output_dir, bands, params, format='png'):
        """
        Initialize worker.

        Args:
            manager: SatelliteImageManager instance
            file_groups: List of file groups
            output_dir: Output directory
            bands: Band names
            params: Processing parameters
            format: Output format (png, geotiff)
        """
        super().__init__()
        self.manager = manager
        self.file_groups = file_groups
        self.output_dir = output_dir
        self.bands = bands
        self.params = params
        self.format = format
        self._is_cancelled = False

    def cancel(self):
        """Cancel batch export."""
        self._is_cancelled = True

    def run(self):
        """Execute batch export."""
        try:
            import os

            total = len(self.file_groups)
            if total == 0:
                raise ValueError("No frames to export")

            os.makedirs(self.output_dir, exist_ok=True)
            exported_files = []

            for i, files in enumerate(self.file_groups):
                if self._is_cancelled:
                    break

                # Load frame
                if not self.manager.load_files(files):
                    logger.warning(f"Failed to load frame {i}")
                    continue

                # Generate output filename
                base_name = f"frame_{i:04d}.{self.format}"
                output_path = os.path.join(self.output_dir, base_name)

                # Export
                result = self.manager.export_image(
                    output_path=output_path,
                    bands=self.bands,
                    gamma=self.params.get('gamma', 1.0),
                    proj_name=self.params.get('proj_name', 'geostationary_native'),
                    format=self.format
                )

                if result.get('success'):
                    exported_files.append(output_path)

                self.progress.emit(i + 1, total)

                # Memory cleanup
                if (i + 1) % 5 == 0:
                    gc.collect()

            self.finished.emit(self.output_dir, exported_files)

        except Exception as e:
            logger.error(f"Batch export failed: {e}")
            self.error.emit(str(e))
