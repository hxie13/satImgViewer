@echo off
chcp 65001 >nul
echo ==========================================
echo Direct I/O Full Environment Setup
echo ==========================================
echo.
echo NOTE: satpy-based loading has been removed.
echo This script now installs the satpy-free full dependency set.
echo.

REM Activate conda environment
call conda activate satImgLib
if errorlevel 1 (
    echo Error: Could not activate satImgLib environment
    echo Please ensure the environment exists
    pause
    exit /b 1
)

echo Current environment: %CONDA_DEFAULT_ENV%
echo.

echo [1/3] Installing full requirements (satpy-free)...
pip install -r requirements_full.txt
if errorlevel 1 (
    echo pip install failed, trying conda fallback for core packages...
    conda install -c conda-forge h5py h5netcdf netCDF4 xarray pyresample pyproj dask distributed -y
)
echo.

echo [2/3] Verifying direct reader stack...
python scripts/verify_readers.py
if errorlevel 1 (
    echo Verification failed. Please review the error output above.
    pause
    exit /b 1
)
echo.

echo [3/3] Done.
echo You can now run: python main.py
echo.
pause
