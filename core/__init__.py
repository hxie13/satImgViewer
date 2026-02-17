"""Core package public API with lazy imports.

This keeps lightweight utilities importable even when optional heavy dependencies
aren't installed in the current environment.
"""

__all__ = ["ISatelliteDataProvider", "ImageProcessor", "SatpyDriver"]


def __getattr__(name: str):
    if name == "ISatelliteDataProvider":
        from .interfaces import ISatelliteDataProvider

        return ISatelliteDataProvider
    if name == "ImageProcessor":
        from .image_proc import ImageProcessor

        return ImageProcessor
    if name == "SatpyDriver":
        from .satpy_driver import SatpyDriver

        return SatpyDriver
    raise AttributeError(f"module 'core' has no attribute {name!r}")
