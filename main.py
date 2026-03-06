import sys
import os
import logging
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# Fix PROJ_LIB pollution from system-level PostgreSQL/PostGIS.
# PostGIS installs its own PROJ data directory and sets PROJ_LIB globally,
# which causes pyproj/PROJ version mismatch ("no database context specified").
# PROJ_LIB must be set BEFORE any pyproj/cartopy import — importing pyproj
# itself triggers PROJ C library initialization with whatever PROJ_LIB is
# set at that moment.
# ---------------------------------------------------------------------------
def _configure_proj_runtime() -> None:
    """
    Bind pyproj/PROJ to the active conda environment data directory.

    In this project environment, pyproj's bundled proj_dir may fail to provide
    a valid DB context, while `%CONDA_PREFIX%/Library/share/proj` works.
    """
    logger = logging.getLogger(__name__)

    def _valid_proj_dir(path: Path) -> bool:
        return path.is_dir() and (path / "proj.db").is_file()

    conda_prefix = Path(os.environ.get("CONDA_PREFIX") or sys.prefix)
    candidate_dirs = [
        conda_prefix / "Library" / "share" / "proj",  # Windows conda
        conda_prefix / "share" / "proj",              # Linux/macOS conda
    ]
    proj_dir = next((p for p in candidate_dirs if _valid_proj_dir(p)), None)

    if proj_dir is None:
        logger.warning("No valid PROJ data directory found; skipping PROJ runtime fix")
        return

    # Clear potentially polluted global path (e.g. PostgreSQL/PostGIS).
    os.environ.pop("PROJ_LIB", None)
    os.environ["PROJ_DATA"] = str(proj_dir)

    # pyproj import may emit one bootstrap warning before data dir is rebound.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="pyproj unable to set PROJ database path.*",
            category=UserWarning,
        )
        from pyproj import datadir

    datadir.set_data_dir(str(proj_dir))

    try:
        import pyproj.database as _db
        if len(_db.get_authorities()) == 0:
            logger.warning("PROJ database context still unavailable after initialization")
    except Exception as exc:
        logger.warning(f"PROJ database probe failed: {exc}")

    # Noisy informational warning triggered by CRS->PROJ4 conversion in dependencies.
    warnings.filterwarnings(
        "ignore",
        message="You will likely lose important projection information when converting to a PROJ string.*",
        category=UserWarning,
        module=r"pyproj\.crs\.crs",
    )

_configure_proj_runtime()

# Ensure project root is in path.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def _configure_logging() -> None:
    """Default WARNING logging; enable DEBUG when SATIMG_DEBUG=1."""
    debug_enabled = os.environ.get("SATIMG_DEBUG") == "1"
    level = logging.DEBUG if debug_enabled else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(name)s:%(message)s",
    )


def main():
    _configure_logging()
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from ui.main_window import MainWindow
    from ui.style import get_theme_qss

    app = QApplication(sys.argv)
    # Keep title/version out of the UI for software copyright screenshots/materials.
    app.setApplicationName("satImgViewer")
    icon_path = Path(__file__).resolve().parent / "ui" / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(get_theme_qss("dark"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
