#!/usr/bin/env python3
"""
Smoke test for real satellite datasets using SatelliteImageManager.

Default root:
    D:\\BaiduNetdiskDownload\\satImg

This script performs a minimal end-to-end check:
1) discover files by family (FY4B/FY3D/Himawari)
2) load files with SatelliteImageManager
3) query available bands
4) run one process_image call
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import List

# Ensure project root is importable when launched via `python scripts/...`.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _collect_files(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    files = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            files.append(path)
    return files


def _pick_bands(bands: List[dict]) -> List[str]:
    canon = [b.get("canonical") for b in bands if b.get("canonical")]
    if len(canon) >= 3:
        return canon[:3]
    if canon:
        return canon[:1]
    return []


def _run_case(name: str, files: List[str]) -> bool:
    from core.manager import SatelliteImageManager

    print("=" * 80)
    print(f"[CASE] {name}")
    print(f"file_count={len(files)}")
    if not files:
        print("result=SKIP (no files)")
        return False

    mgr = SatelliteImageManager()
    ok = mgr.load_files(files)
    print(f"load_ok={ok} driver={mgr.current_driver_type}")
    if not ok:
        print("result=FAIL (load)")
        return False

    bands = mgr.get_available_bands()
    print(f"bands_count={len(bands)}")
    use_bands = _pick_bands(bands)
    print(f"use_bands={use_bands}")
    if not use_bands:
        print("result=FAIL (no bands)")
        return False

    img, area = mgr.process_image(
        bands=use_bands,
        gamma=1.0,
        proj_name="geostationary_native",
    )
    print(
        "image_shape={} dtype={} area_none={}".format(
            getattr(img, "shape", None),
            getattr(img, "dtype", None),
            area is None,
        )
    )
    print("result=OK")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=r"D:\BaiduNetdiskDownload\satImg",
        help="Root folder containing FY4B/FY3D/Himawari subfolders",
    )
    parser.add_argument(
        "--exclude-fy4a",
        action="store_true",
        default=True,
        help="Compatibility flag; this script does not include FY4A by design.",
    )
    args = parser.parse_args()

    root = args.root
    print(f"[INFO] root={root}")

    cases = [
        ("FY4B", _collect_files(os.path.join(root, "FY4B"))),
        ("FY3D", _collect_files(os.path.join(root, "FY3D"))),
        ("Himawari", _collect_files(os.path.join(root, "Himawari"))),
    ]

    all_ok = True
    for name, files in cases:
        try:
            ok = _run_case(name, files)
            all_ok = all_ok and ok
        except Exception as exc:
            print(f"[ERROR] case={name} exc={exc!r}")
            traceback.print_exc()
            all_ok = False

    print("=" * 80)
    if all_ok:
        print("[SUMMARY] ALL_OK")
        return 0
    print("[SUMMARY] HAS_FAILURE")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
