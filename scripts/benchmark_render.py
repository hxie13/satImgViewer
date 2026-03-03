"""
Benchmark load/process/render latency for satellite preview pipeline.
"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

from core.manager import SatelliteImageManager


def _parse_bands(raw: str) -> List[str]:
    bands = [b.strip() for b in raw.split(",") if b.strip()]
    if not bands:
        raise ValueError("At least one band is required")
    return bands


def _p50_p90(values: List[float]) -> Tuple[float, float]:
    arr = np.asarray(values, dtype=np.float64)
    return float(np.percentile(arr, 50)), float(np.percentile(arr, 90))


def _simulate_render(image: np.ndarray) -> None:
    # Approximate render-side work: sanitize and convert to display-ready uint8.
    _ = (np.clip(np.nan_to_num(image, nan=0.0), 0.0, 1.0) * 255).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark render pipeline latency")
    parser.add_argument("--input-dir", required=True, help="Satellite data directory")
    parser.add_argument("--bands", required=True, help="Comma-separated bands, e.g. IR105 or IR105,IR086,VIS006")
    parser.add_argument("--projection", default="plate_carree_global")
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--frames", type=int, default=5, help="Number of time groups to benchmark")
    parser.add_argument("--driver-type", default=None, help="Optional explicit driver type")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    bands = _parse_bands(args.bands)
    manager = SatelliteImageManager()

    files = manager.scan_directory(str(input_dir))
    if not files:
        raise RuntimeError("No supported satellite files found")

    groups = manager.get_time_series_groups(files)
    if not groups:
        raise RuntimeError("No time groups available")
    groups = groups[: max(1, int(args.frames))]

    load_ms: List[float] = []
    process_ms: List[float] = []
    render_ms: List[float] = []

    for i, group in enumerate(groups, start=1):
        t0 = time.perf_counter()
        ok = manager.load_files(group, driver_type=args.driver_type) if args.driver_type else manager.load_files(group)
        if not ok:
            raise RuntimeError(f"Failed to load frame {i}")
        t1 = time.perf_counter()

        image, _ = manager.process_image(
            bands=bands,
            gamma=args.gamma,
            proj_name=args.projection,
            size=(args.width, args.height),
            quality_profile="preview_fast",
            resample_method="nearest",
        )
        t2 = time.perf_counter()

        _simulate_render(image)
        t3 = time.perf_counter()

        load_ms.append((t1 - t0) * 1000.0)
        process_ms.append((t2 - t1) * 1000.0)
        render_ms.append((t3 - t2) * 1000.0)
        print(f"Frame {i}: load={load_ms[-1]:.1f}ms process={process_ms[-1]:.1f}ms render={render_ms[-1]:.1f}ms")

    l50, l90 = _p50_p90(load_ms)
    p50, p90 = _p50_p90(process_ms)
    r50, r90 = _p50_p90(render_ms)

    print("\nSummary (ms)")
    print(f"load    P50={l50:.1f} P90={l90:.1f} mean={statistics.mean(load_ms):.1f}")
    print(f"process P50={p50:.1f} P90={p90:.1f} mean={statistics.mean(process_ms):.1f}")
    print(f"render  P50={r50:.1f} P90={r90:.1f} mean={statistics.mean(render_ms):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
