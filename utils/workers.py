from PyQt6.QtCore import QThread, pyqtSignal
import time
import cv2
import numpy as np

class VideoExportWorker(QThread):
    progress = pyqtSignal(int, int) # (current, total)
    finished = pyqtSignal(str)      # output_path
    error = pyqtSignal(str)

    def __init__(self, driver, file_groups, output_path, bands, params, fps=10):
        super().__init__()
        self.driver = driver
        self.file_groups = file_groups
        self.output_path = output_path
        self.bands = bands
        self.params = params
        self.fps = fps
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            total = len(self.file_groups)
            if total == 0:
                raise ValueError("No frames to export")

            # 初始化 VideoWriter
            writer = None
            
            # 投影设置
            proj_name = self.params.get('proj_name', 'plate_carree_global')
            
            for i, files in enumerate(self.file_groups):
                if self._is_cancelled:
                    break
                
                # 1. 加载场景 (复用 Driver，但在不同线程需小心，最好 Driver 是线程安全的或无状态的)
                # 这里假设 Driver 的 load_scene 是足够快的 I/O 操作
                self.driver.load_scene(files)
                
                # 2. 请求图像 (强制高清 size=None)
                img_data, _ = self.driver.request_image(self.bands, size=None, params=self.params, proj_name=proj_name)
                
                # 3. 数据转 uint8
                if img_data is None: 
                    continue
                    
                img_u8 = np.nan_to_num(np.clip(img_data, 0, 1) * 255).astype(np.uint8)
                
                # 4. 尺寸修正 (OpenCV 要求所有帧尺寸一致)
                # 注意：OpenCV 是 BGR 顺序，Satpy 输出是 RGB
                if img_u8.ndim == 3:
                    frame = cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR)
                else:
                    frame = cv2.cvtColor(img_u8, cv2.COLOR_GRAY2BGR)
                
                height, width, _ = frame.shape
                
                # 5. 初始化 Writer (第一帧时)
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # 或 'avc1'
                    writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (width, height))
                    if not writer.isOpened():
                        raise RuntimeError("Could not open video writer")
                
                writer.write(frame)
                self.progress.emit(i + 1, total)
            
            if writer:
                writer.release()
                
            if not self._is_cancelled:
                self.finished.emit(self.output_path)
                
        except Exception as e:
            self.error.emit(str(e))

class ImageLoaderWorker(QThread):
    data_ready = pyqtSignal(object, object)
    error = pyqtSignal(str)

    def __init__(self, provider, bands, params=None): # <--- 增加 params
        super().__init__()
        self.provider = provider
        self.bands = bands
        self.params = params

    def run(self):
        try:
            print(f"[Worker] Starting image generation for bands={self.bands}")
            t0 = time.time()
            # Extract proj_name from params, default to 'geostationary_native'
            proj_name = 'geostationary_native'
            if self.params:
                proj_name = self.params.get('proj_name', 'geostationary_native')
            # 将 params 和 proj_name 传递给 driver
            img, area = self.provider.request_image(
                self.bands, 
                size=None,  # <--- 关键修改：禁用强制降采样
                params=self.params, 
                proj_name=proj_name
            )
            t1 = time.time()
            print(f"[Worker] request_image returned in {t1-t0:.2f}s")
            print(f"[Worker] Emitting data_ready signal with img shape={getattr(img, 'shape', 'unknown')}, area={type(area)}")
            self.data_ready.emit(img, area)
            print(f"[Worker] Signal emitted successfully")
        except Exception as e:
            # 发出错误信号，供 UI 显示友好提示
            print(f"[Worker] Exception caught: {e}")
            try:
                self.error.emit(str(e))
            except Exception:
                pass
            print(f"Worker Error: {e}")