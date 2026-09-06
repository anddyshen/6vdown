"""设置页：下载主机 / 站点与镜像 / 通用设置。"""
from __future__ import annotations

import re
import time

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import constants
from ..downloader import DownloaderManager
from ..models import MirrorSite
from .host_dialog import HostDialog
from .workers import TestHostRunnable

TYPE_SHORT = {"qb": "qB", "tr": "TR", "ar": "Aria2"}


class NoWheelComboBox(QComboBox):
    """Click-to-open combo box: ignore mouse wheel."""

    def wheelEvent(self, event):  # noqa: D102
        event.ignore()


def _ts(ms: int) -> str:
    if not ms:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


class SettingsPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.db = controller.db
        self.cfg = controller.cfg
        self.manager: DownloaderManager = controller.manager
        self._build()

    # ------------------------------------------------------------ 布局
    def _build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        v = QVBoxLayout(body)
        v.addWidget(self._host_group())
        v.addWidget(self._mirror_group())
        v.addWidget(self._general_group())
        v.addStretch(1)
        body.setLayout(v)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        self.reload()

    # ============================================================ 下载主机
    def _host_group(self) -> QWidget:
        g = QGroupBox("下载主机（qBittorrent / Transmission / Aria2）")
        lay = QVBoxLayout(g)
        self.host_table = QTableWidget(0, 5)
        self.host_table.setHorizontalHeaderLabels(["类型", "名称", "地址:端口", "激活", "操作"])
        hh = self.host_table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.host_table.verticalHeader().setVisible(False)
        self.host_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.host_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.host_table)
        row = QHBoxLayout()
        for text, fn in (("新建", self._host_add), ("设为激活", self._host_active),
                         ("测试连接", self._host_test), ("编辑", self._host_edit),
                         ("删除", self._host_del)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        self.active_host_label = QLabel("")
        self.active_host_label.setStyleSheet("color:#888;")
        row.addWidget(self.active_host_label, 1)
        lay.addLayout(row)
        return g

    def reload_hosts(self) -> None:
        hosts = self.db.list_hosts()
        self.host_table.setRowCount(0)
        self.host_table.setRowCount(len(hosts))
        for r, h in enumerate(hosts):
            self.host_table.setItem(r, 0, QTableWidgetItem(TYPE_SHORT.get(h.type, h.type)))
            self.host_table.setItem(r, 1, QTableWidgetItem(h.name or ""))
            addr = h.address
            port = f":{h.port}" if h.port else ""
            self.host_table.setItem(r, 2, QTableWidgetItem(f"{addr}{port}"))
            self.host_table.setItem(r, 3, QTableWidgetItem("● 激活" if h.is_active else ""))
            if h.is_active:
                self.host_table.item(r, 3).setForeground(Qt.GlobalColor.darkGreen)
            cell = QWidget()
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(2, 0, 2, 0)
            b_act = QPushButton("激活")
            b_act.setFixedSize(52, 22)
            b_act.clicked.connect(lambda _=False, hid=h.id: self._set_active(hid))
            b_edit = QPushButton("编辑")
            b_edit.setFixedSize(52, 22)
            b_edit.clicked.connect(lambda _=False, hid=h.id: self._edit_host(hid))
            b_del = QPushButton("删除")
            b_del.setFixedSize(52, 22)
            b_del.clicked.connect(lambda _=False, hid=h.id: self._del_host(hid))
            hl.addWidget(b_act)
            hl.addWidget(b_edit)
            hl.addWidget(b_del)
            hl.addStretch(1)
            self.host_table.setCellWidget(r, 4, cell)
        h = self.db.active_host()
        self.active_host_label.setText(
            (f"当前发送目标：{TYPE_SHORT.get(h.type, '')}/{(h.name or '')}"
             if h else "尚未配置下载主机"))

    def _selected_host_id(self):
        sel = self.host_table.selectionModel().selectedRows()
        if not sel:
            return None
        row = sel[0].row()
        hosts = self.db.list_hosts()
        return hosts[row].id if row < len(hosts) else None

    def _host_add(self) -> None:
        dlg = HostDialog(self.manager, None, self)
        if dlg.exec() and dlg.result_host:
            self.db.add_host(dlg.result_host)
            self.reload_hosts()

    def _edit_host(self, hid) -> None:
        hosts = self.db.list_hosts()
        h = next((x for x in hosts if x.id == hid), None)
        if not h:
            return
        dlg = HostDialog(self.manager, h, self)
        if dlg.exec() and dlg.result_host:
            dlg.result_host.id = hid
            dlg.result_host.is_active = h.is_active
            self.db.update_host(dlg.result_host)
            self.reload_hosts()

    def _host_edit(self) -> None:
        hid = self._selected_host_id()
        if hid is None:
            QMessageBox.information(self, "提示", "请先选中一行主机")
            return
        self._edit_host(hid)

    def _del_host(self, hid) -> None:
        if QMessageBox.question(self, "确认", "确定删除该下载主机？") != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_host(hid)
        self.reload_hosts()

    def _host_del(self) -> None:
        hid = self._selected_host_id()
        if hid is None:
            QMessageBox.information(self, "提示", "请先选中一行主机")
            return
        self._del_host(hid)

    def _host_active(self) -> None:
        hid = self._selected_host_id()
        self._set_active(hid)

    def _set_active(self, hid) -> None:
        if hid is None:
            QMessageBox.information(self, "提示", "请先选中一行主机")
            return
        self.db.set_active_host(hid)
        self.reload_hosts()

    def _host_test(self) -> None:
        hid = self._selected_host_id()
        if hid is None:
            QMessageBox.information(self, "提示", "请先选中一行主机")
            return
        hosts = self.db.list_hosts()
        h = next((x for x in hosts if x.id == hid), None)
        if not h:
            return
        runnable = TestHostRunnable(self.manager, h)

        def on_done(ok: bool, msg: str) -> None:
            QMessageBox.information(self, "连接测试",
                                    ("✔ " if ok else "✘ ") + msg)

        runnable.signals.done.connect(on_done)
        QThreadPool.globalInstance().start(runnable)

    # ============================================================ 镜像
    def _mirror_group(self) -> QWidget:
        g = QGroupBox("站点与镜像域名（解析源，支持随时新增 / 检测）")
        lay = QVBoxLayout(g)
        self.mirror_table = QTableWidget(0, 6)
        self.mirror_table.setHorizontalHeaderLabels(
            ["地址", "启用", "当前", "可用性", "最近检测", "备注"])
        hh = self.mirror_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.mirror_table.verticalHeader().setVisible(False)
        self.mirror_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mirror_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.mirror_table)
        row = QHBoxLayout()
        for text, fn in (("添加域名", self._mirror_add), ("设为当前", self._mirror_current),
                         ("删除", self._mirror_del)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        b_probe = QPushButton("检测全部可用性")
        b_probe.clicked.connect(lambda: self.ctl.detect_mirrors(False))
        row.addWidget(b_probe)
        b_disc = QPushButton("从发布页发现新域名")
        b_disc.clicked.connect(lambda: self.ctl.detect_mirrors(True))
        row.addWidget(b_disc)
        lay.addLayout(row)
        self.mirror_log = QLabel("")
        self.mirror_log.setStyleSheet("color:#888; font-size:12px;")
        self.mirror_log.setWordWrap(True)
        lay.addWidget(self.mirror_log)
        return g

    def reload_mirrors(self) -> None:
        mirrors = self.db.list_mirrors()
        self.mirror_table.setRowCount(0)
        self.mirror_table.setRowCount(len(mirrors))
        for r, m in enumerate(mirrors):
            self.mirror_table.setItem(r, 0, QTableWidgetItem(m.url))
            self.mirror_table.setItem(r, 1, QTableWidgetItem("✓" if m.enabled else ""))
            self.mirror_table.setItem(r, 2, QTableWidgetItem("★" if m.is_current else ""))
            st = {"ok": "✔ 可用", "fail": "✘ 失效"}.get(m.status, "未检测")
            item = QTableWidgetItem(st)
            item.setForeground(Qt.GlobalColor.darkGreen if m.status == "ok"
                               else Qt.GlobalColor.red if m.status == "fail"
                               else Qt.GlobalColor.gray)
            self.mirror_table.setItem(r, 3, item)
            self.mirror_table.setItem(r, 4, QTableWidgetItem(_ts(m.checked_at)))
            self.mirror_table.setItem(r, 5, QTableWidgetItem(m.note or ""))
        if not mirrors:
            self.mirror_log.setText("（暂无镜像，首次解析将自动写入默认域名）")

    def _selected_mirror(self):
        sel = self.mirror_table.selectionModel().selectedRows()
        if not sel:
            return None
        mirrors = self.db.list_mirrors()
        r = sel[0].row()
        return mirrors[r] if r < len(mirrors) else None

    def _mirror_add(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(self, "添加域名", "镜像地址（如 https://www.6v520.cc/）")
        if not ok or not (url or "").strip():
            return
        url = re.sub(r"^[\s\"']+|[\s\"']+$", "", url)
        if "://" not in url:
            url = "https://" + url
        self.db.upsert_mirror(MirrorSite(url=url.rstrip("/") + "/", enabled=True))
        self.reload_mirrors()

    def _mirror_current(self) -> None:
        m = self._selected_mirror()
        if m:
            self.db.set_current_mirror(m.url)
            self.reload_mirrors()

    def _mirror_del(self) -> None:
        m = self._selected_mirror()
        if not m:
            QMessageBox.information(self, "提示", "请先选中一行镜像")
            return
        if QMessageBox.question(self, "确认", f"删除镜像 {m.url} ？") != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_mirror(m.id)
        self.reload_mirrors()

    def set_mirror_log(self, text: str) -> None:
        self.mirror_log.setText(text)

    # ============================================================ 通用
    def _general_group(self) -> QWidget:
        g = QGroupBox("通用设置")
        form = QFormLayout(g)
        self.theme_combo = NoWheelComboBox()
        for key, lab in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            self.theme_combo.addItem(lab, key)
        form.addRow("界面主题", self.theme_combo)

        self.http_combo = NoWheelComboBox()
        for key, lab in (("ask", "普通网页链接：询问我"), ("send", "一律自动发送"),
                         ("ignore", "忽略普通网页链接")):
            self.http_combo.addItem(lab, key)
        form.addRow("HTTP 链接处理", self.http_combo)

        self.chk_clipboard = QCheckBox("监听剪贴板（磁力 / 下载直链自动识别）")
        form.addRow("", self.chk_clipboard)
        self.chk_auto_magnet = QCheckBox("磁力链接无需确认，直接发送")
        form.addRow("", self.chk_auto_magnet)
        self.chk_notify = QCheckBox("添加任务后右下角弹窗提醒")
        form.addRow("", self.chk_notify)
        self.toast_spin = QSpinBox()
        self.toast_spin.setRange(2, 60)
        self.toast_spin.setSuffix(" 秒")
        form.addRow("弹窗停留时长", self.toast_spin)
        self.chk_boot = QCheckBox("开机自动启动 C2Down")
        form.addRow("", self.chk_boot)
        self.parse_default_combo = NoWheelComboBox()
        for key, lab in (("ask", "每次询问"),
                         ("bg", "默认后台执行"),
                         ("view", "默认查看过程")):
            self.parse_default_combo.addItem(lab, key)
        form.addRow("开始解析默认操作", self.parse_default_combo)
        self.start_behavior_combo = NoWheelComboBox()
        for key, lab in (("window", "启动时显示主窗口"),
                         ("tray", "启动时最小化到托盘（右下角提示）")):
            self.start_behavior_combo.addItem(lab, key)
        form.addRow("启动行为", self.start_behavior_combo)
        self.clip_start_combo = NoWheelComboBox()
        for key, lab in (("enable", "启动时启用剪贴板监听"),
                         ("disable", "启动时禁用剪贴板监听"),
                         ("last", "记住上次关闭时的状态")):
            self.clip_start_combo.addItem(lab, key)
        form.addRow("启动时剪贴板监听", self.clip_start_combo)

        box = QGroupBox("解析区块（解析时仅覆盖勾选的区块）")
        blay = QHBoxLayout(box)
        self.block_checks = []
        for label in constants.BLOCK_KEYWORDS:
            cb = QCheckBox(f"★ {label}")
            self.block_checks.append(cb)
            blay.addWidget(cb)
        blay.addStretch(1)
        form.addRow(box)

        row = QHBoxLayout()
        save = QPushButton("保存设置")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        row.addStretch(1)
        form.addRow(row)

        row2 = QHBoxLayout()
        reset = QPushButton("重置解析数据")
        reset.setObjectName("danger")
        reset.clicked.connect(self._reset_parse)
        row2.addWidget(reset)
        tip = QLabel("清空解析缓存记录，回到“首次解析”状态（不影响下载主机与镜像设置）")
        tip.setStyleSheet("color:#888; font-size:11px;")
        row2.addWidget(tip, 1)
        form.addRow(row2)

        # 数据目录说明
        row3 = QHBoxLayout()
        open_btn = QPushButton("打开数据目录")
        open_btn.clicked.connect(self._open_data_dir)
        row3.addWidget(open_btn)
        from ..constants import app_data_dir

        self.data_dir_label = QLabel(app_data_dir())
        self.data_dir_label.setStyleSheet("color:#888; font-size:11px;")
        self.data_dir_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        row3.addWidget(self.data_dir_label, 1)
        form.addRow(row3)
        return g

    def _open_data_dir(self) -> None:
        import os

        from ..constants import app_data_dir

        d = app_data_dir()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)  # noqa: S606  Windows: 打开资源管理器
        except Exception as e:
            QMessageBox.warning(self, "无法打开", f"{d}\n{e}")

    def _reset_parse(self) -> None:
        if QMessageBox.question(
                self, "确认重置",
                "确定清空全部解析缓存记录？\n\n重置后，下一次解析将被视为首次解析（全量抓取）。"
                "下载主机、镜像域名与历史发送记录不受影响。"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.db.clear_parse_data()
        try:
            wb = self.ctl.window.workbench
            wb.load_items([])
            wb.set_status("解析数据已重置 · 等待下一次全量解析")
        except Exception:
            pass
        self.ctl.notify_ok("解析数据已重置",
                           "下次解析将重新全量抓取并建立缓存。")

    def _save(self) -> None:
        c = self.cfg
        c["theme"] = self.theme_combo.currentData()
        c["http_mode"] = self.http_combo.currentData()
        c["clipboard_monitor"] = self.chk_clipboard.isChecked()
        c["auto_send_magnet"] = self.chk_auto_magnet.isChecked()
        c["notify_enabled"] = self.chk_notify.isChecked()
        c["notify_seconds"] = self.toast_spin.value()
        c["start_on_boot"] = self.chk_boot.isChecked()
        c["parse_default"] = self.parse_default_combo.currentData()
        c["start_behavior"] = self.start_behavior_combo.currentData()
        c["clip_start"] = self.clip_start_combo.currentData()
        c["enabled_blocks"] = [cb.text().replace("★ ", "")
                               for cb in self.block_checks if cb.isChecked()]
        c.save()
        self.ctl.apply_settings()
        self.ctl.notify_ok("设置已保存", "下载主机与解析选项已生效。")

    def reload(self) -> None:
        self.reload_hosts()
        self.reload_mirrors()
        c = self.cfg
        self._set_combo(self.theme_combo, c["theme"])
        self._set_combo(self.http_combo, c["http_mode"])
        self.chk_clipboard.setChecked(bool(c["clipboard_monitor"]))
        self.chk_auto_magnet.setChecked(bool(c["auto_send_magnet"]))
        self.chk_notify.setChecked(bool(c["notify_enabled"]))
        self.chk_boot.setChecked(bool(c["start_on_boot"]))
        self._set_combo(self.parse_default_combo, c.get("parse_default", "ask"))
        self._set_combo(self.start_behavior_combo, c.get("start_behavior", "window"))
        self._set_combo(self.clip_start_combo, c.get("clip_start", "last"))
        self.toast_spin.setValue(int(c["notify_seconds"]))
        enabled = set(c["enabled_blocks"])
        for cb in self.block_checks:
            cb.setChecked(cb.text().replace("★ ", "") in enabled)

    @staticmethod
    def _set_combo(combo: QComboBox, key) -> None:
        i = combo.findData(key)
        combo.setCurrentIndex(i if i >= 0 else 0)



