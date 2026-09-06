"""主窗口：单窗口多标签（工作台 / 历史 / 设置）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget

from .icons import app_icon
from .workbench import WorkbenchPage


class MainWindow(QMainWindow):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("6vdown · 电影站下载解析器")
        self.setWindowIcon(app_icon())
        self.resize(1080, 720)
        self.setMinimumSize(860, 560)

        self.tabs = QTabWidget()
        self.workbench = WorkbenchPage()
        self.tabs.addTab(self.workbench, "解析工作台")
        self.tabs.addTab(ctl.history_page, "历史记录")
        self.tabs.addTab(ctl.settings_page, "设置")
        self.setCentralWidget(self.tabs)

        self.statusBar().showMessage("待激活 · 复制磁力链接后自动发送")

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def switch_workbench(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: D102
        # 关窗最小化到托盘（除非应用正在退出）
        if not self.ctl.quitting and self.ctl.tray and self.ctl.tray.isVisible():
            event.ignore()
            self.hide()
            self.ctl.notify_tip("6vdown 仍在运行", "程序已最小化到系统托盘。")
        else:
            event.accept()
