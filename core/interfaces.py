from abc import ABC, abstractmethod

class ISatelliteDataProvider(ABC):
    """
    卫星数据提供者接口。
    无论是葵花(HSD)还是风云(HDF/NC)，都必须实现这些方法。
    """
    
    @abstractmethod
    def load_scene(self, file_paths: list):
        """加载文件列表，建立索引，不读取具体数据"""
        pass

    @abstractmethod
    def get_available_datasets(self) -> list:
        """返回可用波段/产品列表 (e.g. ['B01', 'B13', 'T05'])"""
        pass

    @abstractmethod
    def get_metadata(self) -> dict:
        """返回公共元数据 (时间, 卫星名, 分辨率)"""
        pass

    @abstractmethod
    def request_image(self, bands: list, size=(1000, 1000)) -> tuple:
        """
        请求图像数据。
        Args:
            bands: 波段列表 ['B01'] 或 ['B03', 'B02', 'B01']
            size: 预览时的重采样大小，优化性能
        Returns:
            (image_data: np.ndarray, crs: object, extent: tuple)
            image_data 必须是已经物理定标(Ref/BT)并归一化过的
        """
        pass
