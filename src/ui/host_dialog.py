"""下载主机编辑对话框。"""
from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QMessageBox,
)

from ..models import DownloadHost
from .workers import TestHostRunnable

TYPE_ITEMS = [("qb", "qBittorrent"), ("tr", "Transmission"), ("ar", "Aria2")]


class HostDialog(QDialog):
    def __init__(self, manager, host: DownloadHost | None = None, parent=None):
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("编辑下载主机")
        self.setMinimumWidth(420)
        self.result_host: DownloadHost | None = None
        self._pool = QThreadPool.globalInstance()

        form = QFormLayout(self)
        self.type_combo = QComboBox()
        for key, label in TYPE_ITEMS:
            self.type_combo.addItem(label, key)
        form.addRow("下载器类型", self.type_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：客厅 NAS / 主力机")
        form.addRow("名称", self.name_edit)

        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("IP 或主机名，如 192.168.1.10")
        form.addRow("地址", self.addr_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        form.addRow("端口", self.port_spin)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("qB/TR 用户名；Aria2 填 RPC Secret")
        form.addRow("用户名 / Secret", self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("密码", self.pass_edit)

        self.test_label = QLabel("")
        form.addRow("", self.test_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_btn = btns.addButton("测试连接", QDialogButtonBox.ButtonRole.ActionRole)
        self.test_btn.clicked.connect(self._test)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        if host:
            self._fill(host)
        self.type_combo.currentIndexChanged.connect(self._hint_port)

    def _fill(self, h: DownloadHost) -> None:
        idx = self.type_combo.findData(h.type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.name_edit.setText(h.name or "")
        self.addr_edit.setText(h.address or "")
        self.port_spin.setValue(h.port or 8080)
        self.user_edit.setText(h.username or "")
        self.pass_edit.setText(h.password or "")

    def _hint_port(self) -> None:
        t = self.type_combo.currentData()
        default = {"qb": 8080, "tr": 9091, "ar": 6800}.get(t, 8080)
        self.port_spin.setValue(default)

    def _collect(self) -> DownloadHost:
        return DownloadHost(
            type=self.type_combo.currentData() or "qb",
            name=self.name_edit.text().strip(),
            address=self.addr_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip(),
            password=self.pass_edit.text(),
        )

    def _accept(self) -> None:
        if not self._collect().address:
            QMessageBox.warning(self, "提示", "请填写主机地址")
            return
        self.result_host = self._collect()
        self.accept()

    def _test(self) -> None:
        h = self._collect()
        if not h.address:
            QMessageBox.warning(self, "提示", "请先填写主机地址")
            return
        self.test_label.setText("正在测试……")
        runnable = TestHostRunnable(self._manager, h)

        def on_done(ok: bool, msg: str) -> None:
            self.test_label.setText(("✔ " if ok else "✘ ") + msg)

        runnable.signals.done.connect(on_done)
        self._pool.start(runnable)
