"""
Satellite Image Viewer — Custom Exception Hierarchy

All domain-specific errors inherit from SatImgError so callers can catch
the broad base class or individual subtypes as needed.
"""


class SatImgError(Exception):
    """Base exception for all satellite image viewer errors."""


# ---------------------------------------------------------------------------
# Data loading errors
# ---------------------------------------------------------------------------

class SatDataLoadError(SatImgError):
    """
    Raised when satellite data cannot be loaded.

    Common causes:
    - File not found or unreadable
    - Unrecognised file format / reader detection failure
    - Corrupt or truncated HDF5 / NetCDF file
    """


class UnsupportedFormatError(SatDataLoadError):
    """Raised when no driver can handle the supplied files."""


class ReaderDetectionError(SatDataLoadError):
    """Raised when satellite type cannot be determined from file names."""


# ---------------------------------------------------------------------------
# Projection / geometry errors
# ---------------------------------------------------------------------------

class ProjectionError(SatImgError):
    """
    Raised when a projection operation fails.

    Common causes:
    - Invalid or unsupported projection name
    - AreaDefinition creation failure (bad extent / proj_dict)
    - Resampling failure
    """


class InvalidExtentError(ProjectionError):
    """Raised when a geographic extent is invalid (e.g. west >= east)."""


class ResamplingError(ProjectionError):
    """Raised when pyresample resampling fails."""


# ---------------------------------------------------------------------------
# Calibration errors
# ---------------------------------------------------------------------------

class CalibrationError(SatImgError):
    """
    Raised when radiometric calibration fails.

    Common causes:
    - Missing calibration coefficients for a band
    - DN values outside expected range
    - Invalid calibration type (neither reflectance nor brightness temperature)
    """


class MissingCoefficientsError(CalibrationError):
    """Raised when calibration coefficients are absent for a band/satellite."""


# ---------------------------------------------------------------------------
# Export errors
# ---------------------------------------------------------------------------

class ExportError(SatImgError):
    """
    Raised when image export fails.

    Common causes:
    - Output directory not writable
    - Unsupported export format
    - GDAL / PIL write failure
    """


class UnsupportedExportFormatError(ExportError):
    """Raised when the requested export format is not supported."""


# ---------------------------------------------------------------------------
# Pipeline errors
# ---------------------------------------------------------------------------

class PipelineError(SatImgError):
    """Raised when a processing pipeline node fails."""


class BandNotFoundError(PipelineError):
    """Raised when a requested band is not available in the loaded scene."""
