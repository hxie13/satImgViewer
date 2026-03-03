"""
RGB Compositor Nodes

Provides different RGB composition strategies for satellite imagery.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import logging
from core.image_proc import normalize_percentile, apply_gamma as _apply_gamma

logger = logging.getLogger(__name__)


class BaseCompositor(ABC):
    """Abstract base class for RGB compositing strategies."""

    @abstractmethod
    def composite(self, bands_data: Dict[str, np.ndarray],
                  band_order: List[str]) -> np.ndarray:
        """
        Compose bands into a single RGB image.

        Args:
            bands_data: Dictionary mapping band names to data arrays
            band_order: List of band names in order [R, G, B]

        Returns:
            RGB image array with shape (height, width, 3)
        """
        pass

    @abstractmethod
    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Normalize data to 0-1 range."""
        pass

    @abstractmethod
    def apply_gamma(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction."""
        pass


class LinearCompositor(BaseCompositor):
    """
    Linear RGB compositor with normalization.

    Simple linear stretching of band values.
    """

    def composite(self, bands_data: Dict[str, np.ndarray],
                  band_order: List[str]) -> np.ndarray:
        """Compose RGB image using linear normalization."""
        if len(band_order) != 3:
            raise ValueError("RGB composition requires exactly 3 bands")

        r_data = bands_data.get(band_order[0])
        g_data = bands_data.get(band_order[1])
        b_data = bands_data.get(band_order[2])

        if any(d is None for d in [r_data, g_data, b_data]):
            missing = [b for b, d in zip(band_order, [r_data, g_data, b_data]) if d is None]
            raise ValueError(f"Missing bands: {missing}")

        # Normalize each band
        r = self.normalize(r_data)
        g = self.normalize(g_data)
        b = self.normalize(b_data)

        return np.stack([r, g, b], axis=-1)

    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Linear normalization with outlier rejection (2–98 percentile)."""
        return normalize_percentile(data, low_pct=2.0, high_pct=98.0)

    def apply_gamma(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction."""
        return _apply_gamma(data, gamma)


class PercentileCompositor(BaseCompositor):
    """
    RGB compositor using percentile-based normalization.

    Provides better color balance for varying illumination conditions.
    """

    def composite(self, bands_data: Dict[str, np.ndarray],
                  band_order: List[str]) -> np.ndarray:
        """Compose RGB image using percentile normalization."""
        if len(band_order) != 3:
            raise ValueError("RGB composition requires exactly 3 bands")

        r_data = bands_data.get(band_order[0])
        g_data = bands_data.get(band_order[1])
        b_data = bands_data.get(band_order[2])

        if any(d is None for d in [r_data, g_data, b_data]):
            missing = [b for b, d in zip(band_order, [r_data, g_data, b_data]) if d is None]
            raise ValueError(f"Missing bands: {missing}")

        r = self.normalize(r_data)
        g = self.normalize(g_data)
        b = self.normalize(b_data)

        return np.stack([r, g, b], axis=-1)

    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Percentile-based normalization with automatic contrast (0.5–99.5%)."""
        return normalize_percentile(data, low_pct=0.5, high_pct=99.5)

    def apply_gamma(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction."""
        return _apply_gamma(data, gamma)


class HistogramEqualizationCompositor(BaseCompositor):
    """
    RGB compositor with histogram equalization.

    Provides enhanced contrast for visualization.
    """

    def __init__(self, n_bins: int = 256):
        """
        Initialize compositor.

        Args:
            n_bins: Number of histogram bins
        """
        self.n_bins = n_bins

    def composite(self, bands_data: Dict[str, np.ndarray],
                  band_order: List[str]) -> np.ndarray:
        """Compose RGB image with histogram equalization."""
        if len(band_order) != 3:
            raise ValueError("RGB composition requires exactly 3 bands")

        r_data = bands_data.get(band_order[0])
        g_data = bands_data.get(band_order[1])
        b_data = bands_data.get(band_order[2])

        if any(d is None for d in [r_data, g_data, b_data]):
            missing = [b for b, d in zip(band_order, [r_data, g_data, b_data]) if d is None]
            raise ValueError(f"Missing bands: {missing}")

        r = self._equalize(r_data)
        g = self._equalize(g_data)
        b = self._equalize(b_data)

        return np.stack([r, g, b], axis=-1)

    def _equalize(self, data: np.ndarray) -> np.ndarray:
        """Apply histogram equalization."""
        # Flatten for histogram calculation
        flat = data.flatten()

        # Calculate histogram
        hist, bins = np.histogram(flat, bins=self.n_bins, density=True)

        # Cumulative distribution
        cdf = np.cumsum(hist)

        # Normalize
        cdf = cdf / cdf[-1]

        # Linear interpolation for equalization
        equalized = np.interp(flat, bins[:-1], cdf)
        equalized = equalized.reshape(data.shape)

        return np.clip(equalized, 0, 1)

    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Simple linear normalization."""
        p2, p98 = np.nanpercentile(data, (2, 98))
        if p98 - p2 > 0:
            return np.clip((data - p2) / (p98 - p2), 0, 1)
        return data

    def apply_gamma(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction."""
        if gamma == 1.0:
            return data
        return np.power(np.clip(data, 0, 1), 1.0 / gamma)


class SingleBandCompositor(BaseCompositor):
    """
    Compositor for single-band (grayscale) visualization.

    Applies colormap for enhanced visualization.
    """

    def __init__(self, colormap: str = 'gray'):
        """
        Initialize compositor.

        Args:
            colormap: Matplotlib colormap name
        """
        self.colormap_name = colormap
        import matplotlib.pyplot as plt
        self.colormap = plt.cm.get_cmap(colormap)

    def composite(self, bands_data: Dict[str, np.ndarray],
                  band_order: List[str]) -> np.ndarray:
        """Create grayscale image from single band."""
        if len(band_order) != 1:
            raise ValueError("Single band composition requires exactly 1 band")

        band_name = band_order[0]
        data = bands_data.get(band_name)

        if data is None:
            raise ValueError(f"Missing band: {band_name}")

        # Normalize
        norm_data = self.normalize(data)

        # Apply colormap
        colored = self.colormap(norm_data)

        # Return RGB only
        return colored[..., :3]

    def normalize(self, data: np.ndarray) -> np.ndarray:
        """Linear normalization with percentile stretch."""
        p2, p98 = np.nanpercentile(data, (2, 98))
        if p98 - p2 > 0:
            return np.clip((data - p2) / (p98 - p2), 0, 1)
        return np.clip(data, 0, 1)

    def apply_gamma(self, data: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction."""
        if gamma == 1.0:
            return data
        return np.power(np.clip(data, 0, 1), 1.0 / gamma)


class RGBCompositorFactory:
    """Factory for creating RGB compositors."""

    _compositors = {
        'linear': LinearCompositor,
        'percentile': PercentileCompositor,
        'histogram': HistogramEqualizationCompositor,
        'grayscale': SingleBandCompositor,
    }

    @classmethod
    def create(cls, method: str = 'linear', **kwargs) -> BaseCompositor:
        """
        Create compositor instance.

        Args:
            method: Compositing method name
            **kwargs: Additional arguments passed to compositor

        Returns:
            Compositor instance

        Raises:
            ValueError: Unknown compositor method
        """
        if method not in cls._compositors:
            available = list(cls._compositors.keys())
            raise ValueError(f"Unknown compositor method: {method}. "
                             f"Available: {available}")

        return cls._compositors[method](**kwargs)

    @classmethod
    def get_available_methods(cls) -> List[str]:
        """Get list of available compositing methods."""
        return list(cls._compositors.keys())

    @classmethod
    def register(cls, name: str, compositor_class: type) -> None:
        """
        Register a new compositor.

        Args:
            name: Unique identifier
            compositor_class: Compositor class (must inherit from BaseCompositor)
        """
        if not issubclass(compositor_class, BaseCompositor):
            raise TypeError("Compositor must inherit from BaseCompositor")

        cls._compositors[name] = compositor_class
