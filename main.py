import sys
import os

# 确保项目根目录在 path 中，防止 ModuleNotFoundError
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.style import DARK_THEME_QSS

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Himawari Pro Viewer")
    
    # 这里可以添加全局样式表 (QSS)
    app.setStyleSheet(DARK_THEME_QSS) 

    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()