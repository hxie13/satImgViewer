#!/usr/bin/env python3
"""
Verify direct I/O library availability for satImgViewer.

Tests that all required libraries for direct satellite data reading
(without satpy) are properly installed and functional.

Usage:
    conda activate satImgLib
    python scripts/verify_readers.py
    python scripts/verify_readers.py --file path/to/satellite.HDF
"""

import sys
import time
import argparse

print("=" * 60)
print("satImgViewer Direct I/O Verification")
print("=" * 60)

ok = True

# ── 1. Core I/O libraries ─────────────────────────────────────────────────────
print("\n[1/4] Core I/O libraries...")

_libs = {
    'h5py':       'HDF5 reading (FY-4A/B, FY-3D)',
    'xarray':     'NetCDF reading (Himawari, FY-4 L2)',
    'numpy':      'Array operations and calibration',
    'pyresample': 'Swath / area resampling',
    'pyproj':     'Map projections',
}

for lib, desc in _libs.items():
    try:
        mod = __import__(lib)
        ver = getattr(mod, '__version__', '?')
        print(f"  ✓ {lib:<15s} {ver:<10s}  {desc}")
    except ImportError as e:
        print(f"  ✗ {lib:<15s} MISSING        {desc}  [{e}]")
        ok = False

# ── 2. HDF5 open test ─────────────────────────────────────────────────────────
print("\n[2/4] h5py HDF5 open benchmark...")
try:
    import h5py, io, tempfile, os
    import numpy as np

    # Create a minimal in-memory HDF5 file and round-trip it
    t0 = time.perf_counter()
    tmp = tempfile.NamedTemporaryFile(suffix='.h5', delete=False)
    tmp.close()
    with h5py.File(tmp.name, 'w') as f:
        f.create_dataset('test', data=np.arange(1000, dtype=np.float32))
        f.attrs['NOMCentLon'] = 104.7
    with h5py.File(tmp.name, 'r') as f:
        data = f['test'][:]
        lon = float(f.attrs['NOMCentLon'])
    os.unlink(tmp.name)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  ✓ HDF5 write+read round-trip: {elapsed:.1f} ms  (NOMCentLon={lon})")
except Exception as e:
    print(f"  ✗ HDF5 test failed: {e}")
    ok = False

# ── 3. xarray NetCDF open test ───────────────────────────────────────────────
print("\n[3/4] xarray NetCDF open benchmark...")
try:
    import xarray as xr
    import numpy as np, tempfile, os

    t0 = time.perf_counter()
    tmp = tempfile.NamedTemporaryFile(suffix='.nc', delete=False)
    tmp.close()
    ds = xr.Dataset(
        {'albedo_01': xr.DataArray(np.random.rand(100, 100).astype('float32'),
                                    dims=['lat', 'lon'])},
        attrs={'sub_lon': 140.7}
    )
    ds.to_netcdf(tmp.name)
    ds2 = xr.open_dataset(tmp.name)
    _ = ds2['albedo_01'].values
    ds2.close()
    os.unlink(tmp.name)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  ✓ NetCDF write+read round-trip: {elapsed:.1f} ms  (sub_lon=140.7)")
except Exception as e:
    print(f"  ✗ NetCDF test failed: {e}")
    ok = False

# ── 4. pyresample AreaDefinition construction ─────────────────────────────────
print("\n[4/4] pyresample AreaDefinition construction...")
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from core.io.area_builder import build_geos_area, build_lonlat_area

    t0 = time.perf_counter()
    # FY-4A AGRI full-disk native area
    area_fy4 = build_geos_area(
        lon_0=104.7, sat_height_m=35786023.0,
        img_width=2748, img_height=2748,
        ifov_x=28.0e-6, ifov_y=28.0e-6,
    )
    elapsed_fy4 = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    # Himawari-8 plate carree
    area_hi = build_lonlat_area(-180, -90, 180, 90, 3600, 1800)
    elapsed_hi = (time.perf_counter() - t0) * 1000

    print(f"  ✓ FY-4 GEOS area: {area_fy4.width}×{area_fy4.height} px  ({elapsed_fy4:.1f} ms)")
    print(f"  ✓ Himawari lonlat area: {area_hi.width}×{area_hi.height} px  ({elapsed_hi:.1f} ms)")
except Exception as e:
    print(f"  ✗ AreaDefinition test failed: {e}")
    ok = False

# ── Optional: open a real satellite file ─────────────────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--file', default=None)
args, _ = parser.parse_known_args()

if args.file:
    print(f"\n[BONUS] Opening real satellite file: {args.file}")
    ext = args.file.lower()
    try:
        t0 = time.perf_counter()
        if ext.endswith('.nc'):
            import xarray as xr
            ds = xr.open_dataset(args.file)
            print(f"  ✓ NetCDF variables: {list(ds.data_vars)[:8]}")
            ds.close()
        elif ext.endswith(('.hdf', '.h5', '.hdf5')):
            import h5py
            with h5py.File(args.file, 'r') as f:
                keys = list(f.keys())[:8]
                attrs = dict(f.attrs)
                print(f"  ✓ HDF5 root keys: {keys}")
                print(f"  ✓ Root attrs: { {k: v for k, v in list(attrs.items())[:5]} }")
        else:
            print(f"  ⚠ Unknown extension — skipping open test")
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  Open time: {elapsed:.1f} ms")
    except Exception as e:
        print(f"  ✗ Failed to open file: {e}")
        ok = False

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if ok:
    print("✓ All checks passed — direct I/O stack is ready!")
    sys.exit(0)
else:
    print("✗ Some checks failed — install missing packages.")
    print("  conda install -c conda-forge h5py xarray pyresample pyproj")
    sys.exit(1)
