import os
import re
from pathlib import Path
from typing import Dict, List

from .models import FileGroup


SUPPORTED_EXTENSIONS = {".nc", ".nc4", ".dat", ".bz2", ".h5", ".hdf"}


def detect_reader_for_file(file_path: str) -> str:
    """Detect a satpy reader name for a single file path."""
    filename = os.path.basename(file_path)
    name_upper = filename.upper()
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if "FY4A" in name_upper or "FY-4A" in name_upper:
        return "agri_fy4a"
    if "FY4B" in name_upper or "FY-4B" in name_upper:
        if "L2" in name_upper:
            return "satpy_cf_nc"
        return "agri_fy4b"

    if "H08" in name_upper or "H09" in name_upper or "HIMAWARI" in name_upper:
        if ext in {".dat", ".bz2"}:
            return "ahi_hsd"
        if ext in {".nc", ".nc4"}:
            return "ahi_l1b_gridded"

    if ext in {".nc", ".nc4"}:
        return "generic_image"
    return "ahi_hsd"


def group_files_by_reader(file_paths: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for file_path in file_paths:
        reader = detect_reader_for_file(file_path)
        grouped.setdefault(reader, []).append(file_path)
    return grouped


def scan_and_group_files(folder_path: str) -> List[List[str]]:
    """Scan folder and group files into time-like batches."""
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return []

    all_files = [
        str(f)
        for f in sorted(p.iterdir())
        if f.is_file() and _is_supported(f.name)
    ]
    if not all_files:
        return []

    groups: Dict[str, List[str]] = {}
    hsd_pattern = re.compile(r"(\d{8}_\d{4})")
    generic_pattern = re.compile(r"(\d{12,14})")

    for f in all_files:
        basename = os.path.basename(f)
        match = hsd_pattern.search(basename) or generic_pattern.search(basename)
        key = match.group(1) if match else basename
        groups.setdefault(key, []).append(f)

    grouped_models = [FileGroup(key=k, files=groups[k]) for k in sorted(groups.keys())]
    return [g.files for g in grouped_models]


def _is_supported(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS)

