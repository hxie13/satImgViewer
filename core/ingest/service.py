"""Scene ingest and normalization service."""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.config import L2_PRODUCT_CONFIG, get_satellite_band_map, get_thermal_bands
from core.scene import (
    DatasetDescriptor,
    FileRole,
    GeometryDescriptor,
    GeometryType,
    MeasurementType,
    NormalizedScene,
    SceneCollection,
    SourceFileRecord,
    get_analysis_grid_definition,
)

from .recognizer import SceneRecognizer
from .scanner import IngestScanner


class SceneIngestService:
    """Convert raw files into normalized analysis scenes with a shared grid baseline."""

    def __init__(self) -> None:
        self._scanner = IngestScanner()
        self._recognizer = SceneRecognizer()

    def scan_directory(self, directory: str) -> List[SourceFileRecord]:
        """Scan a directory and enrich discovered files with recognition metadata."""
        return self._recognizer.recognize_records(self._scanner.scan_directory(directory))

    def normalize_file_paths(
        self,
        file_paths: Sequence[str],
        *,
        analysis_grid_id: str = "plate_carree_global",
        probe_metadata: bool = True,
    ) -> SceneCollection:
        """Normalize an arbitrary file list into a scene collection."""
        records = [self._create_raw_record(path) for path in file_paths]
        return self._build_collection(
            self._recognizer.recognize_records(records),
            root_path=None,
            analysis_grid_id=analysis_grid_id,
            probe_metadata=probe_metadata,
        )

    def build_scene_collection(
        self,
        root_path: str,
        *,
        analysis_grid_id: str = "plate_carree_global",
        probe_metadata: bool = True,
    ) -> SceneCollection:
        """Scan a directory and return normalized scenes ready for loading."""
        records = self.scan_directory(root_path)
        return self._build_collection(
            records,
            root_path=root_path,
            analysis_grid_id=analysis_grid_id,
            probe_metadata=probe_metadata,
        )

    @staticmethod
    def _create_raw_record(path: str) -> SourceFileRecord:
        file_name = os.path.basename(path)
        size_bytes = None
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            pass
        return SourceFileRecord(path=path, file_name=file_name, size_bytes=size_bytes)

    def _build_collection(
        self,
        records: Sequence[SourceFileRecord],
        *,
        root_path: Optional[str],
        analysis_grid_id: str,
        probe_metadata: bool,
    ) -> SceneCollection:
        warnings: List[str] = []
        unmatched_files = [record for record in records if record.driver_type is None]
        groups = self._group_records(records)
        scenes = [
            self._build_scene(group, analysis_grid_id=analysis_grid_id, probe_metadata=probe_metadata, warnings=warnings)
            for group in groups
        ]
        scenes.sort(key=lambda item: (item.nominal_time or "", item.scene_id))
        return SceneCollection(
            root_path=root_path,
            discovered_files=list(records),
            scenes=scenes,
            warnings=warnings,
            unmatched_files=unmatched_files,
        )

    @staticmethod
    def _group_records(records: Sequence[SourceFileRecord]) -> List[List[SourceFileRecord]]:
        groups: Dict[Tuple[str, str, str, str, str, str], List[SourceFileRecord]] = {}
        for record in records:
            key = (
                record.driver_type or "unknown",
                record.satellite_platform or "UNKNOWN",
                record.sensor or "UNKNOWN",
                record.product_level or "UNKNOWN",
                record.product_code or "",
                record.nominal_time or record.file_name,
            )
            groups.setdefault(key, []).append(record)
        grouped = list(groups.values())
        grouped.sort(key=lambda group: group[0].nominal_time or group[0].file_name)
        return grouped

    def _build_scene(
        self,
        group: Sequence[SourceFileRecord],
        *,
        analysis_grid_id: str,
        probe_metadata: bool,
        warnings: List[str],
    ) -> NormalizedScene:
        files = sorted(group, key=lambda item: (item.role != FileRole.PRIMARY, item.file_name.lower()))
        primary = next((record for record in files if record.role == FileRole.PRIMARY), files[0])
        driver_type = primary.driver_type
        reader_type = primary.reader_hint
        probe = self._probe_scene(files) if probe_metadata else {}

        native_geometry = self._build_geometry_descriptor(
            primary,
            probe,
        )
        datasets = self._build_dataset_descriptors(primary, probe)
        scene_id = self._make_scene_id(primary, files)
        if not datasets:
            warnings.append(f"{scene_id}: no normalized datasets available from ingest probe")

        metadata = {
            "group_size": len(files),
            "primary_file": primary.file_name,
            "auxiliary_files": [record.file_name for record in files if record.role == FileRole.AUXILIARY],
            **probe.get("metadata", {}),
        }

        return NormalizedScene(
            scene_id=scene_id,
            driver_type=driver_type,
            reader_type=reader_type,
            satellite_family=primary.satellite_family,
            satellite_platform=primary.satellite_platform,
            sensor=primary.sensor,
            product_level=primary.product_level,
            product_code=primary.product_code,
            nominal_time=primary.nominal_time,
            files=list(files),
            datasets=datasets,
            native_geometry=native_geometry,
            analysis_grid=get_analysis_grid_definition(analysis_grid_id),
            metadata=metadata,
        )

    @staticmethod
    def _make_scene_id(primary: SourceFileRecord, files: Sequence[SourceFileRecord]) -> str:
        product = primary.product_code or "GEN"
        timestamp = (primary.nominal_time or "unknown-time").replace(":", "").replace(" ", "T")
        return f"{primary.satellite_platform or 'UNKNOWN'}_{primary.sensor or 'UNK'}_{product}_{timestamp}_{len(files)}f"

    def _probe_scene(self, files: Sequence[SourceFileRecord]) -> Dict[str, object]:
        primary = next((record for record in files if record.role == FileRole.PRIMARY), files[0])
        if not os.path.exists(primary.path):
            return {}

        reader_hint = primary.reader_hint
        if reader_hint == "fy4_agri_l1":
            from core.io.fy4_reader import FY4Reader

            with FY4Reader(primary.path, satellite=primary.satellite_platform or "auto") as reader:
                area = reader.get_area_definition()
                return {
                    "metadata": reader.get_metadata(),
                    "available_ids": reader.available_bands(),
                    "area": area,
                }

        if reader_hint == "fy4_l2_nc":
            from core.io.fy4_reader import FY4L2Reader

            with FY4L2Reader(primary.path) as reader:
                area = reader.get_area_definition()
                return {
                    "metadata": reader.get_metadata(),
                    "available_ids": reader.available_variables(),
                    "area": area,
                }

        if reader_hint == "himawari_l1b_nc":
            from core.io.himawari_reader import HimawariNCReader

            with HimawariNCReader(primary.path) as reader:
                area = reader.get_area_definition()
                return {
                    "metadata": reader.get_metadata(),
                    "available_ids": reader.available_bands(),
                    "area": area,
                }

        if reader_hint == "fy3d_mersi_l1":
            from core.io.fy3d_reader import FY3DReader

            geo_path = next(
                (record.path for record in files if record.auxiliary_role == "geolocation" and os.path.exists(record.path)),
                None,
            )
            with FY3DReader(primary.path, geo_file=geo_path) as reader:
                return {
                    "metadata": reader.get_metadata(),
                    "available_ids": reader.available_bands(),
                    "area": None,
                }

        return {}

    def _build_dataset_descriptors(
        self,
        primary: SourceFileRecord,
        probe: Dict[str, object],
    ) -> List[DatasetDescriptor]:
        available_ids = set(probe.get("available_ids", []) or [])
        reader_hint = primary.reader_hint

        if reader_hint == "fy4_agri_l1":
            return self._build_band_descriptors("AGRI_L1", available_ids)
        if reader_hint == "himawari_l1b_nc":
            return self._build_band_descriptors("AHI", available_ids)
        if reader_hint == "fy3d_mersi_l1":
            return self._build_band_descriptors("MERSI_L1", available_ids)
        if reader_hint == "fy4_l2_nc":
            return self._build_l2_descriptors(primary, available_ids)
        return []

    @staticmethod
    def _build_band_descriptors(sensor_key: str, available_ids: Iterable[str]) -> List[DatasetDescriptor]:
        band_map = get_satellite_band_map(sensor_key)
        thermal = get_thermal_bands(sensor_key)
        available_lookup = set(available_ids)
        descriptors: List[DatasetDescriptor] = []
        for canonical_name, info in band_map.items():
            native_name = str(info.get("name", canonical_name))
            if available_lookup and native_name not in available_lookup and canonical_name not in available_lookup:
                continue
            is_thermal = canonical_name in thermal or str(info.get("type")) == "thermal"
            measurement_type = (
                MeasurementType.BRIGHTNESS_TEMPERATURE
                if is_thermal
                else MeasurementType.REFLECTANCE
            )
            descriptors.append(
                DatasetDescriptor(
                    dataset_id=canonical_name,
                    canonical_name=canonical_name,
                    native_name=native_name,
                    display_name=canonical_name,
                    measurement_type=measurement_type,
                    resolution=info.get("resolution"),
                    wavelength=info.get("wavelength"),
                    is_thermal=is_thermal,
                )
            )
        return descriptors

    @staticmethod
    def _build_l2_descriptors(primary: SourceFileRecord, available_ids: Iterable[str]) -> List[DatasetDescriptor]:
        available_lookup = list(available_ids)
        product_code = primary.product_code or "L2"
        config = L2_PRODUCT_CONFIG.get(product_code, {})
        if available_lookup:
            return [
                DatasetDescriptor(
                    dataset_id=str(var_name),
                    canonical_name=str(var_name),
                    native_name=str(var_name),
                    display_name=str(var_name),
                    measurement_type=MeasurementType.PRODUCT,
                    resolution=config.get("resolution"),
                    wavelength=None,
                    is_thermal=False,
                    metadata={"unit": config.get("unit")},
                )
                for var_name in available_lookup
            ]
        return [
            DatasetDescriptor(
                dataset_id=product_code,
                canonical_name=product_code,
                native_name=product_code,
                display_name=config.get("name", product_code),
                measurement_type=MeasurementType.PRODUCT,
                resolution=config.get("resolution"),
                wavelength=None,
                is_thermal=False,
                metadata={"unit": config.get("unit")},
            )
        ]

    @staticmethod
    def _build_geometry_descriptor(
        primary: SourceFileRecord,
        probe: Dict[str, object],
    ) -> GeometryDescriptor:
        area = probe.get("area")
        metadata = probe.get("metadata", {}) or {}
        if primary.reader_hint == "fy3d_mersi_l1":
            return GeometryDescriptor(
                geometry_type=GeometryType.SWATH,
                projection_id="swath_native",
                width=None,
                height=None,
                area_extent=metadata.get("swath_extent"),
                extent_units="degrees",
                has_geolocation=bool(metadata.get("geo_file")),
                metadata={"geo_file": metadata.get("geo_file")},
            )

        if primary.reader_hint == "fy4_agri_l1":
            return GeometryDescriptor(
                geometry_type=GeometryType.GEOSTATIONARY_GRID,
                projection_id="geostationary_native",
                width=metadata.get("width"),
                height=metadata.get("height"),
                area_extent=getattr(area, "area_extent", None),
                extent_units="meters",
                has_geolocation=True,
                metadata={"lon_0": metadata.get("lon_0"), "resolution_m": metadata.get("resolution_m")},
            )

        if primary.reader_hint in {"fy4_l2_nc", "himawari_l1b_nc"}:
            return GeometryDescriptor(
                geometry_type=GeometryType.LATLON_GRID,
                projection_id="plate_carree_native",
                width=getattr(area, "width", None),
                height=getattr(area, "height", None),
                area_extent=getattr(area, "area_extent", None),
                extent_units="degrees",
                has_geolocation=area is not None,
                metadata={},
            )

        return GeometryDescriptor(
            geometry_type=GeometryType.UNKNOWN,
            projection_id="unknown",
            width=None,
            height=None,
            area_extent=None,
            extent_units=None,
            has_geolocation=False,
            metadata={},
        )
