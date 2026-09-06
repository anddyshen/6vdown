"""主题：跟随系统亮/暗，可手动切换；QSS + QPalette。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# 颜色主题表
COLORS = {
    "dark": {
        "window": "#1e1f24", "panel": "#26282e", "text": "#e8e8ea",
        "subtext": "#9aa0a6", "border": "#3a3d44", "input": "#2c2e34",
        "accent": "#3b82f6", "sel": "#2f3d55", "btn": "#34373e",
        "btn_hover": "#3d4048", "console_bg": "#15161a",
    },
    "light": {
        "window": "#f4f5f7", "panel": "#ffffff", "text": "#1f2328",
        "subtext": "#6b7280", "border": "#d6d9de", "input": "#ffffff",
        "accent": "#2563eb", "sel": "#dbe7fb", "btn": "#eceef1",
        "btn_hover": "#e2e5ea", "console_bg": "#16181d",
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
QWidget {{ background: {c['window']}; color: {c['text']}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {c['window']}; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; top: -1px; }}
QTabBar::tab {{ background: {c['panel']}; padding: 7px 16px;
  border: 1px solid {c['border']}; border-bottom: none;
  border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {c['window']}; color: {c['accent']}; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px;
  margin-top: 12px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
  color: {c['accent']}; }}
QPushButton {{ background: {c['btn']}; border: 1px solid {c['border']};
  border-radius: 5px; padding: 5px 14px; }}
QPushButton:hover {{ background: {c['btn_hover']}; }}
QPushButton:disabled {{ color: {c['subtext']}; }}
QPushButton#primary {{ background: {c['accent']}; color: white; border: none; }}
QPushButton#danger {{ background: #c0392b; color: white; border: none; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
  background: {c['input']}; border: 1px solid {c['border']};
  border-radius: 5px; padding: 3px 6px; selection-background-color: {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['border']}; }}
QCheckBox {{ spacing: 6px; }}
QTableWidget, QTableView {{ background: {c['panel']};
  border: 1px solid {c['border']}; gridline-color: {c['border']};
  alternate-background-color: {c['window']}; }}
QHeaderView::section {{ background: {c['btn']}; border: none;
  border-right: 1px solid {c['border']}; border-bottom: 1px solid {c['border']};
  padding: 5px; color: {c['subtext']}; }}
QTableWidget::item:selected {{ background: {c['sel']}; }}
QToolTip {{ background: {c['panel']}; color: {c['text']};
  border: 1px solid {c['border']}; padding: 4px; }}
QStatusBar {{ background: {c['panel']}; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; }}
QMenu::item {{ padding: 6px 24px 6px 12px; }}
QMenu::item:selected {{ background: {c['accent']}; color: white; }}
QScrollBar:vertical {{ background: {c['window']}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px;
  min-height: 24px; }}
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
