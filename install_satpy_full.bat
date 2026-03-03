@echo off
chcp 65001 >nul
echo ==========================================
echo Satpy Full Installation Script
echo ==========================================
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

REM Check current satpy version
echo [1/5] Checking current satpy installation...
pip show satpy 2>nul | findstr "Version"
if errorlevel 1 (
    echo satpy not found, will install fresh
) else (
    echo satpy found, will upgrade to full version
)
echo.

REM Install/upgrade satpy with all readers
echo [2/5] Installing satpy with all readers...
conda install -c conda-forge satpy -y
if errorlevel 1 (
    echo Conda install failed, trying pip...
    pip install --upgrade satpy
)
echo.

REM Install optional dependencies for better performance
echo [3/5] Installing performance optimization packages...
conda install -c conda-forge h5netcdf xarray dask -y
echo.

REM Install FY-4 specific dependencies
echo [4/5] Installing FY-4 AGRI specific dependencies...
conda install -c conda-forge h5py netCDF4 -y
echo.

REM Verify installation
echo [5/5] Verifying installation...
echo Available satpy readers:
python -c "import satpy; print('\n'.join(sorted(satpy.available_readers())))"
echo.

echo ==========================================
echo Installation Complete!
echo ==========================================
echo.
echo You can now run: python main.py
echo The warnings should be eliminated.
pause
