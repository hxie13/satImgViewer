"""Recognition helpers that enrich scanned files into normalized source records."""
from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime
from typing import List

from core.drivers import DriverFactory
from core.file_recognizer import FileTypeRecognizer
from core.scene import FileRole, SourceFileRecord


class SceneRecognizer:
    """Attach normalized recognition fields to source file records."""

    def __init__(self) -> None:
        self._recognizer = FileTypeRecognizer()

    def recognize_records(self, files: List[SourceFileRecord]) -> List[SourceFileRecord]:
        """Return enriched file records with satellite/reader metadata."""
        enriched: List[SourceFileRecord] = []
        for record in files:
            result = self._recognizer.recognize(record.path)
            file_name = record.file_name or os.path.basename(record.path)
            role, auxiliary_role = self._infer_file_role(file_name)
            platform = None if result.satellite_type.value == "UNKNOWN" else result.satellite_type.value
            driver_type = DriverFactory.resolve_driver_type(result.reader, [record.path])
            enriched.append(
                replace(
                    record,
                    satellite_family=self._infer_satellite_family(platform),
                    satellite_platform=platform,
                    sensor=result.sensor,
                    product_level=result.product_level.value,
                    product_code=result.product,
                    nominal_time=self._normalize_timestamp(result.timestamp),
                    file_format=result.file_format,
                    driver_type=driver_type,
                    reader_hint=result.reader,
                    confidence=result.confidence,
                    role=role,
                    auxiliary_role=auxiliary_role,
                    metadata={
                        **record.metadata,
                        "region_code": result.region,
                        "recognized_timestamp_raw": result.timestamp,
                    },
                )
            )
        return enriched

    @staticmethod
    def _infer_file_role(file_name: str) -> tuple[FileRole, str | None]:
        upper_name = file_name.upper()
        if any(token in upper_name for token in ("GEO1K", "GEODK", "GEO250", "_GEO_", "LONGITUDE", "LATITUDE")):
            return (FileRole.AUXILIARY, "geolocation")
        return (FileRole.PRIMARY, None)

    @staticmethod
    def _infer_satellite_family(platform: str | None) -> str | None:
        if platform is None:
            return None
        if platform.startswith("FY"):
            return "FENGYUN"
        if platform.startswith("H"):
            return "HIMAWARI"
        return platform

    @staticmethod
    def _normalize_timestamp(timestamp: str | None) -> str | None:
        if not timestamp:
            return None

        patterns = (
            ("%Y%m%d%H%M%S", r"^\d{14}$"),
            ("%Y%m%d_%H%M", r"^\d{8}_\d{4}$"),
            ("%Y%m%d-%H%M", r"^\d{8}-\d{4}$"),
            ("%Y%m%d_%H%M%S", r"^\d{8}_\d{6}$"),
            ("%Y%m%d-%H%M%S", r"^\d{8}-\d{6}$"),
            ("%Y-%m-%d %H:%M:%S", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"),
            ("%Y-%m-%d %H:%M", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$"),
        )
        for fmt, regex in patterns:
            if not re.match(regex, timestamp):
                continue
            try:
                dt = datetime.strptime(timestamp, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return timestamp
