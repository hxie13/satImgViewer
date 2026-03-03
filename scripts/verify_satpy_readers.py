#!/usr/bin/env python3
"""
Verify satpy readers installation and performance.
Run this after installing satpy to check if all required readers are available.
"""

import sys
import time

print("=" * 60)
print("Satpy Readers Verification")
print("=" * 60)

# Test 1: Import satpy and list available readers
print("\n[1/4] Checking available satpy readers...")
try:
    import satpy
    readers = sorted(satpy.available_readers())
    print(f"✓ Found {len(readers)} available readers:")
    for reader in readers:
        print(f"  - {reader}")
except ImportException as e:
    print(f"✗ Failed to import satpy: {e}")
    sys.exit(1)

# Test 2: Check for required readers
print("\n[2/4] Checking required readers for satImgViewer...")
required_readers = {
    'agri_fy4a': 'FY-4A AGRI L1 data',
    'agri_fy4b': 'FY-4B AGRI L1 data',
    'ahi_hsd': 'Himawari HSD data',
    'mersi2_l1b': 'FY3D MERSI L1 data',
}

missing = []
for reader, desc in required_readers.items():
    if reader in readers:
        print(f"  ✓ {reader:20s} - {desc}")
    else:
        print(f"  ✗ {reader:20s} - {desc} (MISSING)")
        missing.append(reader)

if missing:
    print(f"\n⚠ Warning: {len(missing)} required reader(s) missing!")
    print("  Install with: conda install -c conda-forge satpy")
else:
    print("\n✓ All required readers are available!")

# Test 3: Performance benchmark
print("\n[3/4] Running reader import performance test...")
times = {}
for reader_name in ['agri_fy4b', 'agri_fy4a', 'ahi_hsd', 'generic_image']:
    try:
        start = time.time()
        # Just check if reader module can be loaded
        from satpy.readers import load_reader
        load_reader(reader_name)
        elapsed = (time.time() - start) * 1000
        times[reader_name] = elapsed
        print(f"  {reader_name:20s}: {elapsed:.2f} ms")
    except Exception as e:
        print(f"  {reader_name:20s}: Failed - {e}")

if times:
    avg_time = sum(times.values()) / len(times)
    print(f"\n  Average reader load time: {avg_time:.2f} ms")

# Test 4: Check optional performance dependencies
print("\n[4/4] Checking optional performance dependencies...")
optional_deps = {
    'h5netcdf': 'Enhanced HDF5/NetCDF4 performance',
    'xarray': 'Optimized array operations',
    'dask': 'Parallel processing support',
    'cupy': 'GPU acceleration (if available)',
}

for dep, desc in optional_deps.items():
    try:
        __import__(dep)
        print(f"  ✓ {dep:15s} - {desc}")
    except ImportError:
        print(f"  ✗ {dep:15s} - {desc} (optional)")

print("\n" + "=" * 60)
print("Verification Complete")
print("=" * 60)

if missing:
    print("\n⚠ Recommendation: Install missing readers for optimal performance")
    print("   Run: conda install -c conda-forge satpy h5netcdf xarray")
    sys.exit(1)
else:
    print("\n✓ System ready for high-performance satellite data processing!")
    sys.exit(0)
