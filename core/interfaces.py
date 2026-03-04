"""
Deprecated legacy interfaces.

This module is retained only for very old integrations that still import
``core.interfaces``. New code should use ``core.drivers.base.BaseSatelliteDriver``.

Deprecated since: 2026-03-03 (satpy-free migration).
Planned removal: next major version.
"""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod

warnings.warn(
    "core.interfaces is deprecated. Use core.drivers.base.BaseSatelliteDriver instead.",
    DeprecationWarning,
    stacklevel=2,
)


class ISatelliteDataProvider(ABC):
    """
    Deprecated legacy provider interface.

    The historical satpy-era API used method names such as ``load_scene`` and
    ``get_available_datasets``. These names are preserved here only for
    backward import compatibility.
    """

    @abstractmethod
    def load_scene(self, file_paths: list):
        """Legacy load entrypoint."""
        raise NotImplementedError

    @abstractmethod
    def get_available_datasets(self) -> list:
        """Legacy dataset list entrypoint."""
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self) -> dict:
        """Legacy metadata entrypoint."""
        raise NotImplementedError

    @abstractmethod
    def request_image(self, bands: list, size=(1000, 1000)) -> tuple:
        """Legacy image request entrypoint."""
        raise NotImplementedError

