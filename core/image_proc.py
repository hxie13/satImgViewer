import numpy as np

class ImageProcessor:
    """
    静态工具类，负责所有的像素级运算：
    定标、归一化、Gamma校正、直方图拉伸。
    """

    @staticmethod
    def normalize(data: np.ndarray, clip_range=(2, 98)):
        """
        鲁棒的归一化算法，处理 NaN 和 异常值。
        Args:
            data: 原始物理量数据 (Reflectance or BT)
            clip_range: 百分比截断范围 (min_pct, max_pct)
        """
        # 1. 处理 NaN (填充为最小值，防止运算报错)
        valid_mask = ~np.isnan(data)
        if not np.any(valid_mask):
            return np.zeros_like(data)
        
        # 2. 计算截断阈值
        vmin, vmax = np.percentile(data[valid_mask], clip_range)
        
        # 3. 线性拉伸并截断
        # 避免除以零
        if vmax - vmin < 1e-6:
            norm_data = data - vmin
        else:
            norm_data = (data - vmin) / (vmax - vmin)
            
        return np.clip(norm_data, 0, 1)

    @staticmethod
    def apply_gamma(data: np.ndarray, gamma=1.0):
        """
        非线性亮度调整
        data: 必须是 0-1 范围
        """
        if gamma == 1.0:
            return data
        return np.power(data, 1.0 / gamma)

    @staticmethod
    def apply_lut(data: np.ndarray, lut_name='gray'):
        """
        预留接口：应用伪彩色 (Pseudo-color)
        目前返回原始数据，后期可对接 matplotlib colormaps
        """
        return data

    @staticmethod
    def combine_rgb(r, g, b, gamma=1.0):
        """RGB 合成流水线"""
        # 分别归一化
        r_n = ImageProcessor.normalize(r)
        g_n = ImageProcessor.normalize(g)
        b_n = ImageProcessor.normalize(b)
        
        # 堆叠
        rgb = np.dstack((r_n, g_n, b_n))
        
        # 统一 Gamma 校正
        return ImageProcessor.apply_gamma(rgb, gamma)