import argparse
import os
import sys

from version import APP_NAME, APP_VERSION

# 确保项目根目录在 path 中，防止 ModuleNotFoundError
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=f"{APP_NAME} launcher")
    parser.add_argument("--version", action="store_true", help="print application version and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    from ui.style import DARK_THEME_QSS

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # 这里可以添加全局样式表 (QSS)
    app.setStyleSheet(DARK_THEME_QSS)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
