"""主题与现代 QSS：系统亮/暗切换、现代化无边框感、微动效与排版美化。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# 优化现代调色板
COLORS = {
    "dark": {
        "window": "#18191d",
        "panel": "#212328",
        "panel_light": "#2a2d34",
        "text": "#f1f3f7",
        "subtext": "#94a3b8",
        "border": "#333742",
        "border_light": "#474d5c",
        "input": "#1d1f24",
        "accent": "#3b82f6",
        "accent_hover": "#60a5fa",
        "accent_active": "#2563eb",
        "sel": "#26354a",
        "btn": "#2b2e36",
        "btn_hover": "#363a45",
        "btn_active": "#22252c",
        "console_bg": "#121316",
        "tag_new_bg": "#3e2908",
        "tag_new_fg": "#fbbf24",
        "tag_upd_bg": "#0c2c45",
        "tag_upd_fg": "#38bdf8",
        "danger": "#ef4444",
        "danger_hover": "#dc2626",
    },
    "light": {
        "window": "#f8fafc",
        "panel": "#ffffff",
        "panel_light": "#f1f5f9",
        "text": "#0f172a",
        "subtext": "#64748b",
        "border": "#e2e8f0",
        "border_light": "#cbd5e1",
        "input": "#ffffff",
        "accent": "#2563eb",
        "accent_hover": "#3b82f6",
        "accent_active": "#1d4ed8",
        "sel": "#e0edff",
        "btn": "#f1f5f9",
        "btn_hover": "#e2e8f0",
        "btn_active": "#cbd5e1",
        "console_bg": "#0f172a",
        "tag_new_bg": "#fef3c7",
        "tag_new_fg": "#b45309",
        "tag_upd_bg": "#e0f2fe",
        "tag_upd_fg": "#0369a1",
        "danger": "#ef4444",
        "danger_hover": "#dc2626",
    },
}


def detect_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve_mode(mode: str, app: QApplication) -> str:
    """system / light / dark -> 'light'/'dark'"""
    if mode == "light":
        return "light"
    if mode == "dark":
        return "dark"
    return "dark" if detect_dark(app) else "light"


def _build_qss(c: dict) -> str:
    return f"""
/* 全局字体与基础控件 */
QWidget {{
    background: {c['window']};
    color: {c['text']};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background: {c['window']};
}}

/* 现代化导航 TabWidget */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    background: {c['panel']};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {c['subtext']};
    padding: 9px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
    margin-right: 4px;
}}

QTabBar::tab:hover {{
    color: {c['text']};
    background: {c['panel_light']};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}

QTabBar::tab:selected {{
    color: {c['accent']};
    font-weight: 600;
    border-bottom: 2px solid {c['accent']};
}}

/* 分组面板 QGroupBox */
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    background: {c['panel']};
    margin-top: 18px;
    padding-top: 20px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: {c['accent']};
    background: {c['panel']};
}}

/* 按钮规范 */
QPushButton {{
    background: {c['btn']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 15px;
    font-weight: 500;
}}

QPushButton:hover {{
    background: {c['btn_hover']};
    border-color: {c['border_light']};
}}

QPushButton:pressed {{
    background: {c['btn_active']};
}}

QPushButton:disabled {{
    color: {c['subtext']};
    background: {c['panel_light']};
    border-color: {c['border']};
}}

QPushButton#primary {{
    background: {c['accent']};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}

QPushButton#primary:hover {{
    background: {c['accent_hover']};
}}

QPushButton#primary:pressed {{
    background: {c['accent_active']};
}}

QPushButton#danger {{
    background: {c['danger']};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}

QPushButton#danger:hover {{
    background: {c['danger_hover']};
}}

/* 输入框与选择框 */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {c['input']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {c['accent']};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {c['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    selection-background-color: {c['sel']};
    selection-color: {c['text']};
    outline: none;
}}

QCheckBox {{
    spacing: 7px;
}}

/* 表格视觉美化 */
QTableWidget, QTableView {{
    background: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    gridline-color: transparent;
    alternate-background-color: {c['window']};
    selection-background-color: {c['sel']};
    selection-color: {c['text']};
    outline: none;
}}

QHeaderView::section {{
    background: {c['panel_light']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 7px 8px;
    color: {c['subtext']};
    font-weight: 600;
    font-size: 12px;
}}

QTableWidget::item {{
    padding: 4px;
}}

QTableWidget::item:selected {{
    background: {c['sel']};
    color: {c['text']};
}}

/* 提示气泡 Tooltip */
QToolTip {{
    background: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* 状态栏 */
QStatusBar {{
    background: {c['panel']};
    color: {c['subtext']};
    border-top: 1px solid {c['border']};
    padding: 3px 10px;
}}

/* 弹出菜单 */
QMenu {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 7px 24px 7px 14px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background: {c['accent']};
    color: #ffffff;
}}

/* 极细现代滚动条 */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 4px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c['border_light']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 4px;
    min-width: 28px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {c['border_light']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""


def apply_theme(app: QApplication, mode: str = "system") -> str:
    """应用主题，返回实际模式 'light'/'dark'。"""
    app.setStyle("Fusion")
    cur = resolve_mode(mode, app)
    c = COLORS[cur]

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["panel"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["btn"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["subtext"]))
    app.setPalette(pal)

    app.setStyleSheet(_build_qss(c))
    return cur
