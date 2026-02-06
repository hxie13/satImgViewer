from PyQt6.QtCore import QThread, pyqtSignal
import time

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