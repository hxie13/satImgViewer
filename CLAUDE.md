# CLAUDE.md

This file provides repository guidance for coding agents.

## Project Overview

satImgViewer is a PyQt6 desktop application for loading, processing, and visualizing:
- FY-4A/FY-4B AGRI
- FY-3D MERSI-2
- Himawari-8/9 L1b gridded NetCDF

The current architecture is satpy-free and uses direct I/O readers.

## Run

```bash
conda activate satImgLib
python main.py
```

Debug mode:

```bash
SATIMG_DEBUG=1 python main.py
```

## Architecture

### Entry
- `main.py`: app bootstrap, logging, UI launch

### Core
- `core/manager.py`: `SatelliteImageManager` facade
- `core/drivers/`: satellite drivers
  - `fengyun.py`: FY-4 L1/L2
  - `fengyun3d.py`: FY-3D MERSI swath workflow
  - `himawari.py`: Himawari gridded NetCDF workflow
- `core/io/`: direct readers
  - `fy4_reader.py`
  - `fy3d_reader.py`
  - `himawari_reader.py`
  - `area_builder.py`
- `core/geometry/`: projection and target area creation
- `core/file_recognizer.py`: filename-to-format recognition (`preferred_format`)

### UI
- `ui/main_window.py`: main window and interaction flow
- `ui/controllers/`: image/timeseries/export controllers
- `ui/canvas.py`: 2D rendering
- `ui/globe_canvas.py`: 3D rendering

### Workers
- `utils/workers.py`: background image and export workers

## Data Support

| Satellite | Format | Status |
|---|---|---|
| FY-4A/B | HDF5 L1, NetCDF L2 | Supported |
| FY-3D MERSI-2 | HDF5 (+ optional GEO file/folder) | Supported |
| Himawari-8/9 | L1b gridded NetCDF (`.nc`) | Supported |
| Himawari HSD raw (`.dat`, `.bz2`) | Raw binary | Not supported |

## Development Notes

- Prefer `SatelliteImageManager` instead of direct driver handling in UI code.
- Keep image generation async via controllers/workers.
- Use `scripts/verify_readers.py` for dependency and reader-stack verification.
- Use `scripts/smoke_test_real_data.py --root <dataset_root>` for real-data regression.
