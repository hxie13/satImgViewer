#!/usr/bin/env python3
"""
Verify direct I/O library availability for satImgViewer.

Usage:
    python scripts/verify_readers.py
    python scripts/verify_readers.py --file path/to/satellite.HDF
"""

import argparse
import os
import sys
import tempfile
import time


def print_result(ok: bool, name: str, detail: str = "") -> None:
    status = "[OK]" if ok else "[FAIL]"
    if detail:
        print(f"  {status} {name:<15s} {detail}")
    else:
        print(f"  {status} {name}")


def main() -> int:
    print("=" * 60)
    print("satImgViewer Direct I/O Verification")
    print("=" * 60)

    all_ok = True

    print("\n[1/4] Core I/O libraries...")
    libs = {
        "h5py": "HDF5 reading (FY-4A/B, FY-3D)",
        "xarray": "NetCDF reading (Himawari, FY-4 L2)",
        "numpy": "Array operations and calibration",
        "pyresample": "Swath / area resampling",
        "pyproj": "Map projections",
    }
    for lib, desc in libs.items():
        try:
            mod = __import__(lib)
            ver = getattr(mod, "__version__", "?")
            print_result(True, lib, f"{ver:<10s} {desc}")
        except Exception as exc:
            print_result(False, lib, f"MISSING    {desc} [{exc}]")
            all_ok = False

    print("\n[2/4] h5py HDF5 open benchmark...")
    try:
        import h5py
        import numpy as np

        t0 = time.perf_counter()
        tmp = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        tmp.close()
        with h5py.File(tmp.name, "w") as f:
            f.create_dataset("test", data=np.arange(1000, dtype=np.float32))
            f.attrs["NOMCentLon"] = 104.7
        with h5py.File(tmp.name, "r") as f:
            _ = f["test"][:]
            lon = float(f.attrs["NOMCentLon"])
        os.unlink(tmp.name)
        elapsed = (time.perf_counter() - t0) * 1000
        print_result(True, "h5py_roundtrip", f"{elapsed:.1f} ms (NOMCentLon={lon})")
    except Exception as exc:
        print_result(False, "h5py_roundtrip", str(exc))
        all_ok = False

    print("\n[3/4] xarray NetCDF open benchmark...")
    try:
        import numpy as np
        import xarray as xr

        t0 = time.perf_counter()
        tmp = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
        tmp.close()
        ds = xr.Dataset(
            {"albedo_01": xr.DataArray(np.random.rand(64, 64).astype("float32"), dims=["lat", "lon"])},
            attrs={"sub_lon": 140.7},
        )
        ds.to_netcdf(tmp.name)
        ds2 = xr.open_dataset(tmp.name)
        _ = ds2["albedo_01"].values
        ds2.close()
        os.unlink(tmp.name)
        elapsed = (time.perf_counter() - t0) * 1000
        print_result(True, "xarray_roundtrip", f"{elapsed:.1f} ms")
    except Exception as exc:
        print_result(False, "xarray_roundtrip", str(exc))
        all_ok = False

    print("\n[4/4] pyresample AreaDefinition construction...")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from core.io.area_builder import build_geos_area, build_lonlat_area

        t0 = time.perf_counter()
        area_fy4 = build_geos_area(
            lon_0=104.7,
            sat_height_m=35786023.0,
            img_width=2748,
            img_height=2748,
            ifov_x=28.0e-6,
            ifov_y=28.0e-6,
        )
        dt1 = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        area_h = build_lonlat_area(-180, -90, 180, 90, 3600, 1800)
        dt2 = (time.perf_counter() - t0) * 1000

        print_result(True, "area_fy4", f"{area_fy4.width}x{area_fy4.height} ({dt1:.1f} ms)")
        print_result(True, "area_lonlat", f"{area_h.width}x{area_h.height} ({dt2:.1f} ms)")
    except Exception as exc:
        print_result(False, "area_builder", str(exc))
        all_ok = False

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file", default=None)
    args, _ = parser.parse_known_args()
    if args.file:
        print(f"\n[BONUS] Opening real satellite file: {args.file}")
        try:
            ext = args.file.lower()
            t0 = time.perf_counter()
            if ext.endswith(".nc"):
                import xarray as xr

                ds = xr.open_dataset(args.file)
                vars_preview = list(ds.data_vars)[:8]
                ds.close()
                print_result(True, "real_netcdf", f"vars={vars_preview}")
            elif ext.endswith((".hdf", ".h5", ".hdf5")):
                import h5py

                with h5py.File(args.file, "r") as f:
                    keys = list(f.keys())[:8]
                    attrs = list(f.attrs.keys())[:8]
                print_result(True, "real_hdf5", f"keys={keys}, attrs={attrs}")
            else:
                print_result(False, "real_file", "unsupported extension")
                all_ok = False
            elapsed = (time.perf_counter() - t0) * 1000
            print_result(True, "open_time", f"{elapsed:.1f} ms")
        except Exception as exc:
            print_result(False, "real_file", str(exc))
            all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("[OK] All checks passed.")
        return 0
    print("[FAIL] Some checks failed. Install missing packages in satImgLib.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

