# 专业级深色主题 (Dark Pro)
DARK_THEME_QSS = """
/* === 全局基础设置 === */
QWidget {
    background-color: #2b2b2b;
    color: #e0e0e0;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 10pt;
}

/* === 主窗口与面板 === */
QMainWindow {
    background-color: #2b2b2b;
}

QSplitter::handle {
    background-color: #1e1e1e;
    width: 2px;
}

/* === 按钮 (扁平化设计) === */
QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #4c4c4c;
    border-color: #0078d7; /* 悬停高亮蓝 */
}
QPushButton:pressed {
    background-color: #0078d7;
    color: white;
    border-color: #005a9e;
}
QPushButton:disabled {
    background-color: #2b2b2b;
    color: #666;
    border-color: #333;
}

/* === 列表控件 (侧边栏) === */
QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    outline: none; /* 去掉选中时的虚线框 */
}
QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #2a2a2a;
}
QListWidget::item:selected {
    background-color: #004275; /* 选中项深蓝背景 */
    color: white;
    border-left: 3px solid #0078d7; /* 左侧强调线 */
}
QListWidget::item:hover {
    background-color: #2a2a2a;
}

/* === 输入框与 DropZone === */
QLineEdit {
    background-color: #1e1e1e;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #0078d7;
}
QLineEdit:focus {
    border: 1px solid #0078d7;
}

/* === 组合框 (GroupBox) === */
QGroupBox {
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    margin-top: 20px; /* 为标题留出空间 */
    background-color: #323232;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: #aaa;
    font-weight: bold;
}

/* === 滑块 (Slider) - 关键美化点 === */
QSlider::groove:horizontal {
    border: 1px solid #3d3d3d;
    height: 6px;
    background: #1e1e1e;
    margin: 2px 0;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #0078d7;
    border: 1px solid #0078d7;
    width: 14px;
    height: 14px;
    margin: -5px 0; /* 垂直居中 */
    border-radius: 7px; /* 圆形手柄 */
}
QSlider::handle:horizontal:hover {
    background: #1e8feb;
}

/* === 滚动条 (精细化) === */
QScrollBar:vertical {
    border: none;
    background: #2b2b2b;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #555;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* === 状态栏 === */
QStatusBar {
    background-color: #0078d7;
    color: white;
    font-weight: bold;
}
"""