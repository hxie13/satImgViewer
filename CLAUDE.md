# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Himawari/FY Satellite Analyst (Pro Edition) - A PyQt6 desktop application for processing and visualizing geostationary satellite imagery from Fengyun (FY-4A/B) and Himawari-8/9 satellites.

## Running the Application

```bash
# Activate conda environment
conda activate satImgLib

# Run the application
python main.py
```

For debug output, set environment variable before running:
```bash
SATIMG_DEBUG=1 python main.py
```

## Application Architecture

### Entry Point
- `main.py` - Initializes QApplication with dark theme and launches MainWindow

### Core Layer (`core/`)
- **`satpy_driver.py`** - Central satellite data driver. Handles file loading, reader detection, image generation, and export. Implements `ISatelliteDataProvider` interface. Key methods:
  - `load_scene(file_paths)` - Lazy-loads SatPy Scene, suppresses verbose reader warnings
  - `scan_and_group_files(folder)` - Scans folder and groups files by timestamp (for time-series data)
  - `request_image(bands, size, params, proj_name)` - Generates RGB/grayscale images with optional gamma correction
  - `export_image()` - Exports to PNG or GeoTIFF with memory-optimized region cropping

- **`projections.py`** - Projection configuration and AreaDefinition creation. Supports:
  - `geostationary_native` - Native satellite projection (fastest, uses meters)
  - `plate_carree_global` - 0.1-degree global grid (WGS84)
  - `mercator_web` - Web Mercator (EPSG:3857)
  - `extract_geographic_extent()` - Smart extraction using proj_dict lon_0 for geostationary satellites

- **`calibration.py`** - Radiometric calibration utilities:
  - `Calibration` - DN to radiance/reflectance/brightness temperature conversion
  - `GLTCorrection` - Geometric correction using Geolocation Lookup Table
  - `RegionCropper` - Crop by predefined regions (china, east_asia, global)
  - `GeoTIFFWriter` - GDAL-based GeoTIFF export with metadata

- **`geo_utils.py`** - Coordinate transformation utilities. Main function `get_geographic_extent()` converts area_def to (west, east, south, north) tuples.

- **`image_proc.py`** - Image processing: normalization, gamma correction, RGB combination.

### UI Layer (`ui/`)
- **`main_window.py`** - Main application window with:
  - Left control panel (file loading, band selection, RGB compositor, projection selector, gamma slider)
  - Right tabbed display: 2D Map View (Cartopy/Matplotlib) and 3D Globe View (VisPy)
  - Time-series player for animated satellite imagery
  - Video export functionality

- **`canvas.py`** - 2D visualization using Matplotlib with Cartopy projections. `GeoCanvas.update_image()` handles native geostationary (meters) and geographic (degrees) projections.

- **`globe_canvas.py`** - 3D globe visualization using VisPy for texture rendering.

- **`widgets.py`** - Custom widgets: DraggableList for band selection, BandDropZone for RGB compositor.

### Utilities (`utils/`)
- **`workers.py`** - QThread workers for background processing:
  - `ImageLoaderWorker` - Async image generation
  - `VideoExportWorker` - Time-series to MP4 export using OpenCV

## Satellite Data Support

**Supported satellites and readers:**
| Satellite | Reader | File Patterns |
|-----------|--------|---------------|
| Himawari-8/9 | `ahi_hsd` | `.dat`, `.bz2` |
| Himawari-8/9 | `ahi_l1b_gridded` | `.nc` |
| FY-4A | `agri_fy4a` | `.nc`, `.h5` |
| FY-4B | `agri_fy4b` | `.nc`, `.h5` |

**Band naming:** Short names like `B01`, `B13` map to full dataset names via `dataset_map` in SatpyDriver.

## Key Patterns

1. **Lazy SatPy Import** - SatPy is imported inside `load_scene()` with stdout/stderr suppressed to avoid YAML parsing warnings.

2. **Projection-Aware Image Generation** - The `request_image()` method handles two modes:
   - Native (`geostationary_native`): Fast, uses satellite's native projection
   - Geographic (PlateCarree, Mercator): Resamples to target grid for 3D globe compatibility

3. **Threading Model** - Long-running operations (image generation, video export) run in QThread workers to keep UI responsive. Signal/slot pattern for results delivery.

4. **Memory Optimization** - Export uses region-specific AreaDefinition to avoid generating full global grids, reducing memory from ~1.5GB to minimal.

## Common Development Tasks

### Adding a New Projection
1. Add entry to `PROJECTIONS` dict in `core/projections.py`
2. Update `get_available_projections()` return value if needed
3. Test with both 2D canvas and 3D globe rendering

### Adding a New Satellite
1. Update `_detect_reader_for_file()` in `core/satpy_driver.py`
2. Add calibration coefficients to `core/calibration.py`
3. Add spatial resolution mappings to `Resampler.SPATIAL_RESOLUTIONS`

### Debugging Image Display Issues
- Check console output for `[Canvas]` and `[Projections]` debug messages
- Enable debug mode: `SATIMG_DEBUG=1 python main.py`
- Verify area_def has correct `proj_dict` with `lon_0` for geostationary satellites
- Extent format: imshow expects `(west, east, south, north)` but area_def uses `(xmin, ymin, xmax, ymax)`
