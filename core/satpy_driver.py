"""
Legacy SatpyDriver compatibility shim.

This project is now fully satpy-free. The historical ``SatpyDriver`` class is
kept only to provide a clear migration error for stale integrations that still
import ``core.satpy_driver``.
"""
from __future__ import annotations

import warnings

from .interfaces import ISatelliteDataProvider


_MIGRATION_MSG = (
    "SatpyDriver has been removed. Use core.manager.SatelliteImageManager and "
    "the direct-I/O drivers under core.drivers instead."
)


class SatpyDriver(ISatelliteDataProvider):
    """
    Backward-compatibility shim for removed satpy-based driver.

    Any operational method call raises a RuntimeError with migration guidance.
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(_MIGRATION_MSG, DeprecationWarning, stacklevel=2)

    def _unsupported(self):
        raise RuntimeError(_MIGRATION_MSG)

    def load_scene(self, file_paths: list):
        self._unsupported()

    def get_available_datasets(self) -> list:
        self._unsupported()

    def get_metadata(self) -> dict:
        self._unsupported()

    def request_image(self, bands: list, size=(1000, 1000)) -> tuple:
        self._unsupported()


__all__ = ["SatpyDriver"]
