THEME_TOKENS_DARK = {
    # Core backgrounds — deeper navy family
    "bg_app":             "#080E1C",
    "bg_panel":           "#0E1828",
    "bg_subtle":          "#141F33",
    "bg_elevated":        "#1A2540",
    # Text
    "text_primary":       "#EEF4FF",
    "text_secondary":     "#8BA5C5",
    "text_dim":           "#4E6480",
    # Borders
    "border_default":     "#1E3050",
    "border_subtle":      "#162440",
    # Accents
    "accent_primary":     "#38BDF8",
    "accent_primary_dim": "#0C4A6E",
    "accent_success":     "#34D399",
    "accent_warn":        "#FCD34D",
    "accent_danger":      "#F87171",
    # RGB channel indicator colors
    "channel_r":          "#F87171",
    "channel_g":          "#34D399",
    "channel_b":          "#60A5FA",
    # Layout
    "radius":             "8px",
    "control_h":          "30px",
    "font_family":        '"Segoe UI", "Microsoft YaHei", sans-serif',
}

_THEME_TEMPLATE = """
QWidget {
    background-color: {bg_app};
    color: {text_primary};
    font-family: {font_family};
    font-size: 10pt;
}

QMainWindow {
    background-color: {bg_app};
}

/* ── Panel containers ── */
#TopToolbar, #LeftPanel, #RightPanel, #MainCenter {
    background-color: {bg_panel};
    border: 1px solid {border_default};
    border-radius: {radius};
}

#LeftPanel, #RightPanel, #MainCenter {
    padding: 6px;
}

/* ── Header ── */
#HeaderTitle {
    font-size: 16px;
    font-weight: 700;
    color: {text_primary};
}

#HeaderMeta {
    color: {accent_primary};
    font-size: 8.5pt;
    background-color: {accent_primary_dim};
    border: 1px solid {border_default};
    border-radius: 4px;
    padding: 1px 6px;
}

#ViewStatusLabel, #RenderInfoLabel, #FrameInfoLabel, #ExportInfoLabel {
    color: {text_secondary};
    font-size: 8.5pt;
}

/* ── GroupBox: VS Code-style left accent border ── */
QGroupBox {
    border: 1px solid {border_subtle};
    border-left: 3px solid {border_default};
    border-radius: {radius};
    margin-top: 20px;
    background-color: {bg_panel};
    font-weight: 600;
    font-size: 9pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -1px;
    padding: 2px 6px;
    color: {text_secondary};
    font-size: 8.5pt;
}

/* ── QPushButton base ── */
QPushButton {
    min-height: {control_h};
    border-radius: 6px;
    border: 1px solid {border_default};
    background-color: {bg_subtle};
    color: {text_primary};
    padding: 4px 11px;
    font-weight: 600;
    font-size: 9.5pt;
}

QPushButton:hover {
    border-color: {accent_primary};
    background-color: {bg_elevated};
}

QPushButton:pressed {
    background-color: {accent_primary_dim};
    border-color: {accent_primary};
}

QPushButton:focus {
    border: 2px solid {accent_primary};
    padding: 3px 10px;
}

QPushButton:disabled {
    color: {text_dim};
    border-color: {border_subtle};
    background-color: {bg_panel};
}

/* ── Primary: gradient teal ── */
QPushButton[role="primary"] {
    background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #0EA5A0,stop:1 #0C7A76);
    color: #E0FFFE;
    border: 1px solid #14B8A6;
    font-weight: 700;
}

QPushButton[role="primary"]:hover {
    background-color: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #14C8C0,stop:1 #0F9690);
    border-color: {accent_primary};
}

QPushButton[role="primary"]:pressed {
    background-color: #085955;
}

QPushButton[role="primary"]:focus {
    border: 2px solid {accent_primary};
    padding: 3px 10px;
}

QPushButton[role="primary"]:disabled {
    background-color: #0B2E2C;
    border-color: #0F4F4C;
    color: #4A8A87;
}

/* ── Secondary: outlined ── */
QPushButton[role="secondary"] {
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid {border_default};
}

QPushButton[role="secondary"]:hover {
    background-color: {bg_elevated};
    color: {text_primary};
    border-color: {accent_primary};
}

QPushButton[role="secondary"]:pressed {
    background-color: {accent_primary_dim};
}

/* ── Ghost ── */
QPushButton[role="ghost"] {
    background-color: transparent;
    border: 1px solid {border_subtle};
    color: {text_secondary};
    font-size: 9pt;
}

QPushButton[role="ghost"]:hover {
    background-color: {bg_elevated};
    color: {text_primary};
    border-color: {border_default};
}

/* ── Danger ── */
QPushButton[role="danger"] {
    background-color: #7F1D1D;
    color: #FFE4E4;
    border: 1px solid {accent_danger};
}

QPushButton[role="danger"]:hover {
    background-color: #991B1B;
}

QPushButton[role="danger"]:disabled {
    background-color: #3D1010;
    border-color: #5A1A1A;
    color: #9A7070;
}

/* ── Clear-band × button (small circle) ── */
QPushButton[role="clear_band"] {
    min-height: 22px;
    max-height: 22px;
    min-width: 22px;
    max-width: 22px;
    border-radius: 11px;
    border: 1px solid {border_default};
    background-color: transparent;
    color: {text_dim};
    font-size: 11pt;
    font-weight: 700;
    padding: 0px;
}

QPushButton[role="clear_band"]:hover {
    background-color: #4A1D1D;
    border-color: {accent_danger};
    color: {accent_danger};
}

/* ── Toolbar buttons slightly taller ── */
#TopToolbar QPushButton {
    min-height: 32px;
    padding: 4px 14px;
}

/* ── Form controls ── */
QComboBox, QLineEdit, QSpinBox {
    min-height: {control_h};
    border: 1px solid {border_default};
    border-radius: 6px;
    background-color: {bg_subtle};
    color: {text_primary};
    padding: 0 8px;
    font-size: 9.5pt;
}

QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border: 1.5px solid {accent_primary};
    background-color: {bg_elevated};
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: {bg_subtle};
    border: 1px solid {border_default};
    selection-background-color: {accent_primary_dim};
    selection-color: {accent_primary};
    outline: none;
}

/* ── BandDropZone ── */
#BandDropZone {
    background-color: {bg_app};
    border: 1.5px dashed {border_default};
    border-radius: 6px;
    color: {text_dim};
    padding: 0 8px;
    font-style: italic;
    font-size: 9pt;
}

#BandDropZone[dropState="hover"] {
    background-color: {accent_primary_dim};
    border: 1.5px dashed {accent_primary};
    color: {accent_primary};
}

#BandDropZone[dropState="active"] {
    background-color: #0E2035;
    border: 1.5px solid {accent_primary};
    color: {text_primary};
    font-style: normal;
    font-weight: 600;
}

#BandDropZone[dropState="invalid"] {
    background-color: #2A1010;
    border: 1.5px solid {accent_danger};
    color: {accent_danger};
}

/* Channel-coloured active borders */
#BandDropZone[channel="R"][dropState="active"] {
    border-color: {channel_r};
    color: {channel_r};
}

#BandDropZone[channel="G"][dropState="active"] {
    border-color: {channel_g};
    color: {channel_g};
}

#BandDropZone[channel="B"][dropState="active"] {
    border-color: {channel_b};
    color: {channel_b};
}

/* Channel label colours */
QLabel[channel="R"] {
    color: {channel_r};
    font-weight: 700;
}

QLabel[channel="G"] {
    color: {channel_g};
    font-weight: 700;
}

QLabel[channel="B"] {
    color: {channel_b};
    font-weight: 700;
}

/* ── QListWidget ── */
QListWidget {
    background-color: {bg_subtle};
    border: 1px solid {border_default};
    border-radius: 6px;
    outline: none;
}

QListWidget::item {
    border-bottom: 1px solid {border_subtle};
    padding: 5px 8px;
    color: {text_secondary};
}

QListWidget::item:hover {
    background-color: {bg_elevated};
    color: {text_primary};
}

QListWidget::item:selected {
    background-color: {accent_primary_dim};
    color: {accent_primary};
    border-left: 3px solid {accent_primary};
    padding-left: 5px;
}

QListWidget[density="compact"]::item {
    padding: 2px 8px;
}

QListWidget[density="comfortable"]::item {
    padding: 6px 8px;
}

/* ── QTabWidget: underline style ── */
QTabWidget::pane {
    border: 1px solid {border_default};
    border-top: none;
    background-color: {bg_panel};
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {text_secondary};
    padding: 7px 18px 6px 18px;
    font-size: 9.5pt;
    font-weight: 600;
    margin-right: 2px;
}

QTabBar::tab:hover {
    color: {text_primary};
    border-bottom: 2px solid {border_default};
}

QTabBar::tab:selected {
    color: {accent_primary};
    border-bottom: 2px solid {accent_primary};
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    border: none;
    background: {border_default};
    height: 4px;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: {accent_primary};
    border-radius: 2px;
    height: 4px;
}

QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {accent_primary};
    background: {bg_elevated};
}

QSlider::handle:horizontal:hover {
    background: {accent_primary};
}

/* ── Scrollbar (vertical) ── */
QScrollBar:vertical {
    background: {bg_app};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: {border_default};
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: {accent_primary};
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

/* ── Scrollbar (horizontal) ── */
QScrollBar:horizontal {
    background: {bg_app};
    height: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background: {border_default};
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: {accent_primary};
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── Status bar ── */
QStatusBar {
    background-color: {bg_panel};
    color: {text_secondary};
    border-top: 1px solid {border_default};
    font-size: 8.5pt;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

/* ── Status dot ── */
#StatusDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
}

#StatusDot[level="idle"]    { background-color: #3D5266; }
#StatusDot[level="loading"] { background-color: {accent_warn}; }
#StatusDot[level="success"] { background-color: {accent_success}; }
#StatusDot[level="error"]   { background-color: {accent_danger}; }

/* ── Splitter ── */
QSplitter::handle {
    background-color: {border_default};
    width: 1px;
    height: 1px;
}

QSplitter::handle:hover {
    background-color: {accent_primary};
}

/* ── Tooltip ── */
QToolTip {
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border_default};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 8.5pt;
}
"""


def _render_theme_template(template: str, tokens: dict) -> str:
    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


DARK_THEME_QSS = _render_theme_template(_THEME_TEMPLATE, THEME_TOKENS_DARK)


def get_theme_qss(theme: str = "dark") -> str:
    """Return application QSS theme string.

    Currently only the dark theme is implemented.
    """
    return DARK_THEME_QSS
