import sys
import os
import logging

# Ensure project root is in path.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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

