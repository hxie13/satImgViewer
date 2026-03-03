"""
Image Processing Utilities

Pixel-level operations: normalization, gamma correction, RGB combination.
Module-level functions are the canonical implementation; other modules should
call these instead of duplicating the logic.
"""
import numpy as np


# =============================================================================
# Module-level canonical implementations
# =============================================================================

def normalize_percentile(data: np.ndarray,
                          low_pct: float = 2.0,
                          high_pct: float = 98.0) -> np.ndarray:
    """
    Percentile-based linear stretch, handles NaN values.

    Args:
        data:     Input array (any shape). NaN pixels are preserved.
        low_pct:  Lower percentile cutoff  (default 2.0).
        high_pct: Upper percentile cutoff  (default 98.0).

    Returns:
        Float array clipped to [0, 1] with original NaN positions preserved.
    """
    valid_mask = ~np.isnan(data)
    if not np.any(valid_mask):
        return np.zeros_like(data, dtype=np.float32)

    vmin, vmax = np.percentile(data[valid_mask], (low_pct, high_pct))

    if vmax - vmin < 1e-6:
        # Flat data — avoid division by zero; clamp to 0
        result = np.where(valid_mask, 0.0, np.nan).astype(np.float32)
    else:
        result = (data - vmin) / (vmax - vmin)
        result = np.clip(result, 0.0, 1.0).astype(np.float32)
        result[~valid_mask] = np.nan

    return result


def apply_gamma(data: np.ndarray, gamma: float = 1.0) -> np.ndarray:
    """
    Non-linear brightness adjustment (power-law).

    Args:
        data:  Input array in [0, 1] range.
        gamma: Gamma value (>1 brightens, <1 darkens).

    Returns:
        Gamma-corrected array, same shape and dtype as input.
    """
    if gamma == 1.0:
        return data
    return np.power(np.clip(data, 0.0, 1.0), 1.0 / gamma)


# =============================================================================
# Class-based API (kept for backward compatibility)
# =============================================================================

class ImageProcessor:
    """
    Static utility class for pixel-level operations.

    Delegates to the module-level canonical functions above.
    """

    @staticmethod
    def normalize(data: np.ndarray, clip_range=(2, 98)):
        """
        Robust normalization with percentile clipping.

        Args:
            data:       Raw physical-quantity data (reflectance or BT).
            clip_range: (min_pct, max_pct) percentile range.
        """
        return normalize_percentile(data, low_pct=clip_range[0], high_pct=clip_range[1])

    @staticmethod
    def apply_gamma(data: np.ndarray, gamma=1.0):
        """Non-linear brightness adjustment. data must be in [0, 1]."""
        return apply_gamma(data, gamma)

    @staticmethod
    def apply_lut(data: np.ndarray, lut_name='gray'):
        """
        Reserved interface: pseudo-color (LUT) application.
        Currently returns input unchanged; hook into matplotlib colormaps later.
        """
        return data

    @staticmethod
    def combine_rgb(r, g, b, gamma=1.0):
        """RGB composition pipeline: normalize each band, stack, apply gamma."""
        r_n = normalize_percentile(r)
        g_n = normalize_percentile(g)
        b_n = normalize_percentile(b)

        rgb = np.dstack((r_n, g_n, b_n))
        return apply_gamma(rgb, gamma)
