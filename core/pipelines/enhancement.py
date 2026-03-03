"""
Image Enhancement Nodes

Provides image enhancement operations for satellite imagery.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
import numpy as np
import logging
from core.image_proc import normalize_percentile, apply_gamma as _apply_gamma

logger = logging.getLogger(__name__)


class BaseEnhancer(ABC):
    """Abstract base class for image enhancement operations."""

    @abstractmethod
    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Apply enhancement to image data.

        Args:
            data: Input image array (0-1 normalized)
            **kwargs: Enhancement parameters

        Returns:
            Enhanced image array
        """
        pass


class GammaEnhancer(BaseEnhancer):
    """
    Gamma correction for non-linear brightness adjustment.

    Useful for enhancing dark or bright images.
    """

    def __init__(self, default_gamma: float = 1.0):
        """
        Initialize enhancer.

        Args:
            default_gamma: Default gamma value
        """
        self.default_gamma = default_gamma

    def enhance(self, data: np.ndarray, gamma: Optional[float] = None,
                **kwargs) -> np.ndarray:
        """
        Apply gamma correction.

        Args:
            data: Input image array (0-1 normalized)
            gamma: Gamma value (None uses default)

        Returns:
            Gamma-corrected image
        """
        g = gamma if gamma is not None else self.default_gamma

        if g == 1.0 or np.isclose(g, 1.0):
            return data

        return np.power(np.clip(data, 0, 1), 1.0 / g)

    def __repr__(self) -> str:
        return f"GammaEnhancer(default_gamma={self.default_gamma})"


class ContrastEnhancer(BaseEnhancer):
    """
    Linear contrast adjustment using histogram stretching.

    Enhances contrast by stretching the range of pixel values.
    """

    def __init__(self, low_percent: float = 2.0, high_percent: float = 98.0):
        """
        Initialize enhancer.

        Args:
            low_percent: Lower percentile for stretch
            high_percent: Upper percentile for stretch
        """
        self.low_percent = low_percent
        self.high_percent = high_percent

    def enhance(self, data: np.ndarray,
               low: Optional[float] = None,
               high: Optional[float] = None,
               **kwargs) -> np.ndarray:
        """
        Apply contrast stretch.

        Args:
            data: Input image array
            low: Low value for stretch (None uses percentile)
            high: High value for stretch (None uses percentile)

        Returns:
            Contrast-enhanced image
        """
        if low is None and high is None:
            # Use canonical implementation when both bounds are automatic
            return normalize_percentile(data, low_pct=self.low_percent, high_pct=self.high_percent)

        if low is None:
            low = np.nanpercentile(data, self.low_percent)
        if high is None:
            high = np.nanpercentile(data, self.high_percent)

        if high - low <= 0:
            return data

        enhanced = (data - low) / (high - low)
        return np.clip(enhanced, 0, 1)

    def __repr__(self) -> str:
        return f"ContrastEnhancer(low={self.low_percent}%, high={self.high_percent}%)"


class SharpeningEnhancer(BaseEnhancer):
    """
    Unsharp masking for image sharpening.

    Enhances edges and fine details.
    """

    def __init__(self, amount: float = 0.5, radius: float = 1.0):
        """
        Initialize enhancer.

        Args:
            amount: Sharpening strength
            radius: Gaussian blur radius
        """
        self.amount = amount
        self.radius = radius

    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Apply unsharp masking.

        Args:
            data: Input image array

        Returns:
            Sharpened image
        """
        import scipy.ndimage as ndimage

        # Create blurred version
        blurred = ndimage.gaussian_filter(data, sigma=self.radius)

        # Calculate sharpened version
        sharpened = data + self.amount * (data - blurred)

        return np.clip(sharpened, 0, 1)

    def __repr__(self) -> str:
        return f"SharpeningEnhancer(amount={self.amount}, radius={self.radius})"


class DenoisingEnhancer(BaseEnhancer):
    """
    Non-local means denoising for image cleanup.

    Reduces noise while preserving edges.
    """

    def __init__(self, strength: float = 0.1):
        """
        Initialize enhancer.

        Args:
            strength: Denoising strength
        """
        self.strength = strength

    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Apply denoising.

        Args:
            data: Input image array

        Returns:
            Denoised image
        """
        try:
            import cv2

            # Convert to 8-bit for OpenCV
            img_uint8 = (data * 255).astype(np.uint8)

            # Apply fastNlMeansDenoising
            if len(data.shape) == 3:
                # Color image
                denoised = cv2.fastNlMeansDenoisingColored(
                    img_uint8, None, self.strength * 255, self.strength * 255, 7, 21
                )
            else:
                # Grayscale
                denoised = cv2.fastNlMeansDenoising(
                    img_uint8, None, self.strength * 255, 7, 21
                )

            return denoised.astype(np.float32) / 255.0

        except ImportError:
            logger.warning("OpenCV not available, skipping denoising")
            return data

    def __repr__(self) -> str:
        return f"DenoisingEnhancer(strength={self.strength})"


class CLAHEEnhancer(BaseEnhancer):
    """
    Contrast Limited Adaptive Histogram Equalization (CLAHE).

    Improves local contrast without amplifying noise.
    """

    def __init__(self, clip_limit: float = 2.0, grid_size: Tuple[int, int] = (8, 8)):
        """
        Initialize enhancer.

        Args:
            clip_limit: Contrast clipping limit
            grid_size: Grid size for tile division
        """
        self.clip_limit = clip_limit
        self.grid_size = grid_size

    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Apply CLAHE.

        Args:
            data: Input image array

        Returns:
            CLAHE-enhanced image
        """
        try:
            import cv2

            # Convert to 8-bit
            img_uint8 = (np.clip(data, 0, 1) * 255).astype(np.uint8)

            # Apply CLAHE
            clahe = cv2.createCLAHE(
                clipLimit=self.clip_limit,
                tileGridSize=self.grid_size
            )

            if len(data.shape) == 3:
                # Apply to each channel
                result = np.zeros_like(img_uint8)
                for i in range(3):
                    result[..., i] = clahe.apply(img_uint8[..., i])
            else:
                result = clahe.apply(img_uint8)

            return result.astype(np.float32) / 255.0

        except ImportError:
            logger.warning("OpenCV not available, skipping CLAHE")
            return data

    def __repr__(self) -> str:
        return f"CLAHEEnhancer(clip_limit={self.clip_limit}, grid={self.grid_size})"


class NanHandlingEnhancer(BaseEnhancer):
    """
    Handle NaN and invalid values in satellite data.

    Ensures clean data for visualization.
    """

    def __init__(self, fill_value: float = 0.0,
                 check_inf: bool = True,
                 replace_inf: float = True):
        """
        Initialize enhancer.

        Args:
            fill_value: Value to use for NaN
            check_inf: Whether to check for infinity values
            replace_inf: Value to use for infinity
        """
        self.fill_value = fill_value
        self.check_inf = check_inf
        self.replace_inf = replace_inf if isinstance(replace_inf, (int, float)) else 1.0

    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Replace NaN and invalid values.

        Args:
            data: Input image array

        Returns:
            Cleaned image
        """
        result = np.copy(data)

        # Replace NaN
        result = np.nan_to_num(result, nan=self.fill_value)

        # Handle infinity
        if self.check_inf:
            result = np.where(np.isinf(result), self.replace_inf, result)

        return result

    def __repr__(self) -> str:
        return f"NanHandlingEnhancer(fill_value={self.fill_value})"


class EnhancementPipeline:
    """
    Sequenced image enhancement pipeline.

    Applies multiple enhancements in sequence.
    """

    def __init__(self, steps: Optional[list] = None):
        """
        Initialize pipeline.

        Args:
            steps: List of enhancer instances in order
        """
        self.steps = steps or []

    def add_step(self, enhancer: BaseEnhancer) -> 'EnhancementPipeline':
        """
        Add enhancement step.

        Args:
            enhancer: Enhancer instance

        Returns:
            Self for chaining
        """
        self.steps.append(enhancer)
        return self

    def enhance(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """
        Apply all enhancement steps in sequence.

        Args:
            data: Input image array
            **kwargs: Parameters passed to each enhancer

        Returns:
            Enhanced image
        """
        result = data.copy()

        for step in self.steps:
            try:
                result = step.enhance(result, **kwargs)
            except Exception as e:
                logger.error(f"Enhancement step {step} failed: {e}")

        return result

    def __repr__(self) -> str:
        step_names = [str(s) for s in self.steps]
        return f"EnhancementPipeline({step_names})"

    @classmethod
    def create_default(cls) -> 'EnhancementPipeline':
        """Create pipeline with default enhancements."""
        return cls([
            NanHandlingEnhancer(),
            ContrastEnhancer(),
            GammaEnhancer(),
        ])
