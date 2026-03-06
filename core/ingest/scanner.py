"""File-system scanner for ingest-time scene discovery."""
from __future__ import annotations

import os
from typing import Iterable, List, Optional

from core.scene import SourceFileRecord


class IngestScanner:
    """Collect candidate satellite data files before recognition/normalization."""

    DEFAULT_EXTENSIONS = {".nc", ".NC", ".dat", ".DAT", ".bz2", ".h5", ".H5", ".hdf", ".HDF"}

    def scan_directory(
        self,
        directory: str,
        extensions: Optional[Iterable[str]] = None,
    ) -> List[SourceFileRecord]:
        """Return discovered source files in a directory."""
        allowed = set(extensions or self.DEFAULT_EXTENSIONS)
        records: List[SourceFileRecord] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1]
                if ext not in allowed:
                    continue
                size_bytes = None
                try:
                    size_bytes = entry.stat().st_size
                except OSError:
                    pass
                records.append(
                    SourceFileRecord(
                        path=entry.path,
                        file_name=entry.name,
                        size_bytes=size_bytes,
                    )
                )
        return sorted(records, key=lambda item: item.file_name.lower())
