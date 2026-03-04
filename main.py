import sys
import os
import logging

# Ensure project root is in path.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Windows: add all conda env DLL directories so h5py can find hdf5.dll and its
# transitive deps.  Git Bash conda-activate only adds Scripts/, not Library/bin.
# The bundled h5py/hdf5.dll is renamed .bak so Windows searches here instead.
if sys.platform == "win32":
    for _d in (
        sys.prefix,
        os.path.join(sys.prefix, "Library", "bin"),
        os.path.join(sys.prefix, "Library", "mingw-w64", "bin"),
        os.path.join(sys.prefix, "Library", "usr", "bin"),
    ):
        if os.path.isdir(_d):
            os.add_dll_directory(_d)

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.style import get_theme_qss


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
    app = QApplication(sys.argv)
    app.setApplicationName("Himawari Pro Viewer")
    app.setStyleSheet(get_theme_qss("dark"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

