"""设置页：下载主机 / 站点与镜像 / 通用设置。"""
from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import constants
from ..downloader import DownloaderManager
from ..models import MirrorSite, SiteInstance
from ..site.modules import list_modules
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


class MirrorDialog(QDialog):
    """新增 / 编辑镜像：地址 + 备注 + 启用。"""

    def __init__(self, mirror=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑镜像" if mirror else "添加镜像")
        self.setMinimumWidth(480)
        self.result_mirror = None
        form = QFormLayout(self)
        self.edit_url = QLineEdit(mirror.url if mirror else "")
        self.edit_url.setPlaceholderText("https://www.example.com/")
        form.addRow("镜像地址", self.edit_url)
        self.edit_note = QLineEdit((mirror.note or "") if mirror else "")
        form.addRow("备注（可选）", self.edit_note)
        self.chk_enabled = QCheckBox("启用该镜像（参与检测与解析轮换）")
        self.chk_enabled.setChecked(bool(mirror.enabled) if mirror else True)
        form.addRow("", self.chk_enabled)
        btns = QHBoxLayout()
        ok = QPushButton("确定")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(btns)

    def _accept(self) -> None:
        url = (self.edit_url.text() or "").strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入镜像地址")
            return
        if "://" not in url:
            url = "https://" + url
        self.result_mirror = MirrorSite(
            url=url.rstrip("/") + "/",
            enabled=self.chk_enabled.isChecked(),
            note=(self.edit_note.text() or "").strip())
        self.accept()


class SiteDialog(QDialog):
    """新增 / 编辑解析站点：名称 + 模块 + 入口地址（每行一个）+ 启用。"""

    def __init__(self, site=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑站点" if site else "添加解析站点")
        self.setMinimumWidth(520)
        self.result_site = None
        form = QFormLayout(self)
        self.edit_name = QLineEdit(site.name if site else "")
        self.edit_name.setPlaceholderText("如：电影港")
        form.addRow("站点名称", self.edit_name)

        self.module_combo = NoWheelComboBox()
        for meta in list_modules():
            self.module_combo.addItem(f"{meta.name}（{meta.module_id}）",
                                      meta.module_id)
        if site:
            i = self.module_combo.findData(site.module_id)
            if i >= 0:
                self.module_combo.setCurrentIndex(i)
        form.addRow("解析模块", self.module_combo)

        self.edit_entries = QPlainTextEdit()
        self.edit_entries.setPlaceholderText(
            "每行一个入口地址，如：\nhttps://www.dygang.tv/\n\n"
            "留空 = 使用上方“镜像域名”池（仅 hao6v 模板支持）")
        self.edit_entries.setPlainText(
            "\n".join(site.entries()) if site else "")
        self.edit_entries.setMaximumHeight(110)
        form.addRow("入口地址", self.edit_entries)

        self.edit_note = QLineEdit((site.note or "") if site else "")
        self.edit_note.setPlaceholderText("可选，如：发布页 dygang.me")
        form.addRow("备注", self.edit_note)

        self.chk_enabled = QCheckBox("启用该站点（参与解析）")
        self.chk_enabled.setChecked(bool(site.enabled) if site else True)
        form.addRow("", self.chk_enabled)

        btns = QHBoxLayout()
        ok = QPushButton("确定")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(btns)

    def _accept(self) -> None:
        name = (self.edit_name.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入站点名称")
            return
        module_id = self.module_combo.currentData()
        entries = []
        for line in (self.edit_entries.toPlainText() or "").splitlines():
            u = line.strip()
            if not u:
                continue
            if "://" not in u:
                u = "https://" + u
            entries.append(u.rstrip("/") + "/")
        self.result_site = SiteInstance(
            module_id=module_id, name=name, entry_urls=entries,
            enabled=self.chk_enabled.isChecked(),
            note=(self.edit_note.text() or "").strip())
        self.accept()


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
        v.addWidget(self._site_group())
        v.addWidget(self._subscription_group())
        v.addWidget(self._emby_group())
        v.addWidget(self._ai_group())
        v.addWidget(self._modules_group())
        v.addWidget(self._search_group())
        v.addWidget(self._general_group())
        v.addStretch(1)
        body.setLayout(v)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        self.reload()

    # ============================================================ 下载主机
    def _host_group(self) -> QWidget:
        g = QGroupBox("🖥️ 下载主机（qBittorrent / Transmission / Aria2）")
        lay = QVBoxLayout(g)
        self.host_table = QTableWidget(0, 5)
        self.host_table.setHorizontalHeaderLabels(["类型", "名称", "地址:端口", "激活", "操作"])
        hh = self.host_table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.host_table.verticalHeader().setVisible(False)
        self.host_table.verticalHeader().setDefaultSectionSize(36)
        self.host_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.host_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.host_table.setMinimumHeight(170)
        lay.addWidget(self.host_table)
        row = QHBoxLayout()
        for text, fn in (("新建", self._host_add), ("设为激活", self._host_active),
                         ("测试连接", self._host_test), ("编辑", self._host_edit),
                         ("删除", self._host_del)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        self.active_host_label = QLabel("")
        self.active_host_label.setStyleSheet("color:#64748b; font-weight:500;")
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
            hl.setContentsMargins(4, 2, 4, 2)
            hl.setSpacing(6)
            b_act = QPushButton("激活")
            b_act.setFixedSize(54, 26)
            b_act.setCursor(Qt.CursorShape.PointingHandCursor)
            b_act.clicked.connect(lambda _=False, hid=h.id: self._set_active(hid))
            b_edit = QPushButton("编辑")
            b_edit.setFixedSize(54, 26)
            b_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            b_edit.clicked.connect(lambda _=False, hid=h.id: self._edit_host(hid))
            b_del = QPushButton("删除")
            b_del.setFixedSize(54, 26)
            b_del.setCursor(Qt.CursorShape.PointingHandCursor)
            b_del.clicked.connect(lambda _=False, hid=h.id: self._del_host(hid))
            hl.addWidget(b_act)
            hl.addWidget(b_edit)
            hl.addWidget(b_del)
            hl.addStretch(1)
            self.host_table.setCellWidget(r, 4, cell)
            self.host_table.setRowHeight(r, 38)
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
        g = QGroupBox("🌐 站点与镜像域名（解析源，支持随时新增 / 检测）")
        lay = QVBoxLayout(g)
        self.mirror_table = QTableWidget(0, 6)
        self.mirror_table.setHorizontalHeaderLabels(
            ["地址", "启用", "当前", "可用性", "最近检测", "备注"])
        hh = self.mirror_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.mirror_table.verticalHeader().setVisible(False)
        self.mirror_table.verticalHeader().setDefaultSectionSize(36)
        self.mirror_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mirror_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mirror_table.setMinimumHeight(190)
        lay.addWidget(self.mirror_table)
        row = QHBoxLayout()
        for text, fn in (("添加域名", self._mirror_add), ("设为当前", self._mirror_current),
                         ("编辑", self._mirror_edit_sel), ("删除", self._mirror_del)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        self.btn_probe = QPushButton("检测全部可用性")
        self.btn_probe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_probe.clicked.connect(lambda: self.ctl.detect_mirrors(False))
        row.addWidget(self.btn_probe)
        self.btn_discover = QPushButton("从发布页发现新域名")
        self.btn_discover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_discover.clicked.connect(lambda: self.ctl.detect_mirrors(True))
        row.addWidget(self.btn_discover)
        lay.addLayout(row)
        self.mirror_log = QLabel("")
        self.mirror_log.setStyleSheet("color:#64748b; font-size:12px;")
        self.mirror_log.setWordWrap(True)
        lay.addWidget(self.mirror_log)
        self.probe_bar = QProgressBar()
        self.probe_bar.setRange(0, 0)
        self.probe_bar.setTextVisible(False)
        self.probe_bar.setFixedHeight(8)
        self.probe_bar.hide()
        lay.addWidget(self.probe_bar)
        self.mirror_table.itemDoubleClicked.connect(
            lambda _it: self._mirror_edit_sel())
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
            self.mirror_table.setRowHeight(r, 38)
        if not mirrors:
            self.mirror_log.setText("（暂无镜像，首次解析将自动写入默认域名）")

    def _selected_mirror(self):
        sel = self.mirror_table.selectionModel().selectedRows()
        if not sel:
            return None
        mirrors = self.db.list_mirrors()
        r = sel[0].row()
        return mirrors[r] if r < len(mirrors) else None

    @staticmethod
    def _norm_url(raw: str) -> str:
        raw = re.sub(r"^[\s\"']+|[\s\"']+$", "", raw or "")
        if "://" not in raw:
            raw = "https://" + raw
        return raw.rstrip("/") + "/"

    def _mirror_add(self) -> None:
        dlg = MirrorDialog(None, self)
        if dlg.exec() and dlg.result_mirror:
            m = dlg.result_mirror
            m.url = self._norm_url(m.url)
            self.db.upsert_mirror(m)
            self.reload_mirrors()

    def _mirror_edit_sel(self) -> None:
        m = self._selected_mirror()
        if not m:
            QMessageBox.information(self, "提示", "请先选中一行镜像")
            return
        self._mirror_edit(m)

    def _mirror_edit(self, m) -> None:
        dlg = MirrorDialog(m, self)
        if not (dlg.exec() and dlg.result_mirror):
            return
        nm = dlg.result_mirror
        nm.id = m.id
        nm.url = self._norm_url(nm.url)
        old_url = m.url
        was_current = bool(m.is_current)
        nm.is_current = was_current
        nm.status = m.status
        nm.checked_at = m.checked_at
        try:
            self.db.update_mirror(nm)
        except ValueError as e:
            QMessageBox.warning(self, "无法保存", str(e))
            return
        if was_current and nm.url != old_url:
            self.db.set_current_mirror(nm.url)
        self.reload_mirrors()

    def set_mirror_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy:
            self.probe_bar.show()
            self.mirror_log.setText("正在检测镜像可用性，请稍候……")
        else:
            self.probe_bar.hide()
        for b in (getattr(self, "btn_probe", None),
                  getattr(self, "btn_discover", None)):
            if b is not None:
                b.setEnabled(not busy)

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

    # ============================================================ 解析站点
    def _site_group(self) -> QWidget:
        g = QGroupBox("🗺️ 解析站点（可设默认站点；勾选解析范围请在“解析工作台”顶部按钮）")
        lay = QVBoxLayout(g)
        self.site_table = QTableWidget(0, 6)
        self.site_table.setHorizontalHeaderLabels(
            ["站点", "模块", "入口", "启用", "默认", "操作"])
        hh = self.site_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.site_table.verticalHeader().setVisible(False)
        self.site_table.verticalHeader().setDefaultSectionSize(36)
        self.site_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.site_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.site_table.setMinimumHeight(170)
        lay.addWidget(self.site_table)
        row = QHBoxLayout()
        for text, fn in (("添加站点", self._site_add), ("编辑", self._site_edit_sel),
                         ("删除", self._site_del_sel)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        self.btn_site_probe = QPushButton("检测入口可用性")
        self.btn_site_probe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_site_probe.clicked.connect(self._site_probe)
        row.addWidget(self.btn_site_probe)
        lay.addLayout(row)
        self.site_log = QLabel("")
        self.site_log.setStyleSheet("color:#64748b; font-size:12px;")
        self.site_log.setWordWrap(True)
        lay.addWidget(self.site_log)
        self.site_probe_bar = QProgressBar()
        self.site_probe_bar.setRange(0, 0)
        self.site_probe_bar.setTextVisible(False)
        self.site_probe_bar.setFixedHeight(8)
        self.site_probe_bar.hide()
        lay.addWidget(self.site_probe_bar)
        self.site_table.itemDoubleClicked.connect(
            lambda _it: self._site_edit_sel())
        return g

    def reload_sites(self) -> None:
        sites = self.db.list_sites()
        self.site_table.setRowCount(0)
        self.site_table.setRowCount(len(sites))
        for r, s in enumerate(sites):
            self.site_table.setItem(r, 0, QTableWidgetItem(s.name or ""))
            self.site_table.setItem(r, 1, QTableWidgetItem(s.module_id))
            entries = s.entries()
            self.site_table.setItem(r, 2, QTableWidgetItem(
                "\n".join(entries) if entries else "（镜像域名池）"))
            self.site_table.setItem(r, 3, QTableWidgetItem("✓" if s.enabled else ""))
            is_cur = bool(getattr(s, "is_current", False))
            cur_item = QTableWidgetItem("● 默认" if is_cur else "")
            cur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cur_item.setToolTip("默认站点：搜索页/工作台的“仅默认站点”使用该站点")
            self.site_table.setItem(r, 4, cur_item)
            cell = QWidget()
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(4, 2, 4, 2)
            hl.setSpacing(6)
            if not is_cur:
                b_cur = QPushButton("设为默认")
                b_cur.setFixedSize(66, 26)
                b_cur.setCursor(Qt.CursorShape.PointingHandCursor)
                b_cur.setToolTip("把该站点设为默认解析站点")
                b_cur.clicked.connect(
                    lambda _=False, sid=s.id: self._site_set_default(sid))
                hl.addWidget(b_cur)
            b_edit = QPushButton("编辑")
            b_edit.setFixedSize(50, 26)
            b_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            b_edit.clicked.connect(lambda _=False, sid=s.id: self._site_edit(sid))
            b_del = QPushButton("删除")
            b_del.setFixedSize(50, 26)
            b_del.setCursor(Qt.CursorShape.PointingHandCursor)
            b_del.clicked.connect(lambda _=False, sid=s.id: self._site_del(sid))
            hl.addWidget(b_edit)
            hl.addWidget(b_del)
            hl.addStretch(1)
            self.site_table.setCellWidget(r, 5, cell)
            self.site_table.setRowHeight(r, 38)
        if not sites:
            self.site_log.setText("（暂无站点实例，重新打开本页会自动补写内置站点）")
        else:
            self.site_log.setText(self._site_selection_text())

    def _site_set_default(self, site_id) -> None:
        """设为默认站点：搜索页/工作台的“仅默认站点”都用它。"""
        try:
            self.db.set_current_site(site_id)
        except Exception as e:
            QMessageBox.warning(self, "设置失败", str(e))
            return
        self.reload_sites()

    def _site_selection_text(self) -> str:
        """显示默认站点与工作台当前勾选的解析范围。"""
        try:
            sites = self.db.list_sites(enabled_only=True)
        except Exception:
            return ""
        sel = []
        for x in (self.cfg.get("enabled_sites") or []):
            try:
                sel.append(int(x))
            except (TypeError, ValueError):
                continue
        try:
            cur = self.db.current_site()
        except Exception:
            cur = None
        head = f"默认站点：{cur.name}。" if cur else "默认站点：未设置。"
        picked = ([s for s in sites if s.id in sel] if sel else list(sites))
        if not picked:
            return head + "当前无可用站点：请先在上方启用至少一个站点。"
        if len(picked) == len(sites):
            return head + f"解析范围：全部 {len(picked)} 个启用站点（工作台可改）"
        return head + ("解析范围：" + "、".join(s.name for s in picked)
                       + "（工作台可改）")

    def _selected_site(self):
        sel = self.site_table.selectionModel().selectedRows()
        if not sel:
            return None
        sites = self.db.list_sites()
        r = sel[0].row()
        return sites[r] if r < len(sites) else None

    def _site_add(self) -> None:
        dlg = SiteDialog(None, self)
        if dlg.exec() and dlg.result_site:
            self.db.upsert_site(dlg.result_site)
            self.reload_sites()

    def _site_edit_sel(self) -> None:
        s = self._selected_site()
        if not s:
            QMessageBox.information(self, "提示", "请先选中一行站点")
            return
        self._site_edit(s.id)

    def _site_edit(self, site_id) -> None:
        s = self.db.get_site(site_id)
        if not s:
            return
        dlg = SiteDialog(s, self)
        if not (dlg.exec() and dlg.result_site):
            return
        ns = dlg.result_site
        ns.id = s.id
        ns.is_current = s.is_current
        self.db.upsert_site(ns)
        self.reload_sites()

    def _site_del_sel(self) -> None:
        s = self._selected_site()
        if not s:
            QMessageBox.information(self, "提示", "请先选中一行站点")
            return
        self._site_del(s.id)

    def _site_del(self, site_id) -> None:
        s = self.db.get_site(site_id)
        if not s:
            return
        if len(self.db.list_sites()) <= 1:
            QMessageBox.warning(self, "无法删除", "至少需要保留一个站点实例")
            return
        if QMessageBox.question(self, "确认", f"删除站点 {s.name} ？") != \
                QMessageBox.StandardButton.Yes:
            return
        self.db.delete_site(site_id)
        self.reload_sites()
        try:
            self.ctl.refresh_source_label()
        except Exception:
            pass

    def _site_probe(self) -> None:
        s = self._selected_site()
        if not s:
            QMessageBox.information(self, "提示", "请先选中一行站点")
            return
        urls = s.entries()
        if not urls:
            QMessageBox.information(self, "提示",
                                    "该站点使用镜像域名池，请用上方“检测全部可用性”")
            return
        self.set_site_busy(True)
        self.site_log.setText("正在检测入口可用性，请稍候……")
        worker = MirrorProbeWorker(self.db, urls)
        worker.log.connect(self.site_log.setText)
        worker.done.connect(self._on_site_probe_done)
        self._site_probe_worker = worker
        worker.start()

    def _on_site_probe_done(self, result: dict) -> None:
        self.set_site_busy(False)
        ok = [u for u, (good, _n, _l) in result.items() if good]
        bad = [u for u, (good, _n, _l) in result.items() if not good]
        parts = []
        if ok:
            parts.append(f"可用 {len(ok)} 个")
        if bad:
            parts.append(f"不可用 {len(bad)} 个（详见日志）")
        self.site_log.setText("检测完成：" + ("；".join(parts) or "无入口"))

    def set_site_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy:
            self.site_probe_bar.show()
        else:
            self.site_probe_bar.hide()
        btn = getattr(self, "btn_site_probe", None)
        if btn is not None:
            btn.setEnabled(not busy)

    # ============================================================ 订阅与画质
    def _subscription_group(self) -> QWidget:
        g = QGroupBox("📺 订阅与自动追剧偏好")
        form = QFormLayout(g)

        self.chk_sub_startup = QCheckBox("启动 6vdown 时自动检查订阅更新")
        form.addRow("", self.chk_sub_startup)

        self.chk_sub_direct = QCheckBox("发现新更新时直接后台下载（无需弹出确认对话框）")
        form.addRow("", self.chk_sub_direct)

        self.chk_sub_sched = QCheckBox("开启后台周期性定时检查订阅")
        form.addRow("", self.chk_sub_sched)

        self.sub_sched_spin = QSpinBox()
        self.sub_sched_spin.setRange(1, 48)
        self.sub_sched_spin.setSuffix(" 小时")
        form.addRow("定时检查间隔", self.sub_sched_spin)

        # 画质优先级（可拖动排序；默认 1080P > 4K > 720P > 其它）
        q_box = QWidget()
        q_lay = QHBoxLayout(q_box)
        q_lay.setContentsMargins(0, 0, 0, 0)
        self.q_list = QListWidget()
        self.q_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.q_list.setFixedHeight(118)
        self.q_list.setSpacing(2)
        q_lay.addWidget(self.q_list, 1)
        btn_q_reset = QPushButton("恢复默认")
        btn_q_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_q_reset.clicked.connect(self._reset_quality_priority)
        q_lay.addWidget(btn_q_reset, 0, Qt.AlignmentFlag.AlignTop)
        form.addRow("下载画质优先级（拖动排序）", q_box)

        tip = QLabel("当某集剧集同时发布多个不同版本时，按列表从上到下选取第一条命中的画质，防止重复下载。")
        tip.setStyleSheet("color: #64748b; font-size: 11px;")
        form.addRow("", tip)
        return g

    def _reload_quality_list(self, order=None) -> None:
        self.q_list.clear()
        for lab in (order or self.cfg.get("quality_priority")
                    or ["1080P", "4K", "720P", "OTHER"]):
            item = QListWidgetItem(str(lab))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.q_list.addItem(item)

    def _reset_quality_priority(self) -> None:
        self._reload_quality_list(["1080P", "4K", "720P", "OTHER"])

    # ============================================================ Emby 联动
    def _emby_group(self) -> QWidget:
        g = QGroupBox("🍿 Emby 媒体库联动（自动对比缺集与防重）")
        form = QFormLayout(g)

        self.chk_emby = QCheckBox("启用与本地/远程 Emby 媒体库联动")
        form.addRow("", self.chk_emby)

        self.edit_emby_url = QLineEdit()
        self.edit_emby_url.setPlaceholderText("http://192.168.1.x:8096")
        form.addRow("Emby 服务器地址", self.edit_emby_url)

        self.edit_emby_key = QLineEdit()
        self.edit_emby_key.setPlaceholderText("在 Emby 后台「高级」-「Api 密钥」中生成")
        self.edit_emby_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API 密钥 (API Key)", self.edit_emby_key)

        test_row = QHBoxLayout()
        btn_test = QPushButton("测试 Emby 连接")
        btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test.clicked.connect(self._test_emby)
        test_row.addWidget(btn_test)

        self.emby_status_lab = QLabel("")
        self.emby_status_lab.setStyleSheet("font-size: 12px; color: #64748b;")
        test_row.addWidget(self.emby_status_lab, 1)
        form.addRow("", test_row)

        emby_tip = QLabel("开启后，自动读取 Emby 媒体库中的已入库集数，自动跳过已有集数，仅下载最新缺集。")
        emby_tip.setStyleSheet("color: #64748b; font-size: 11px;")
        form.addRow("", emby_tip)
        return g

    def _test_emby(self) -> None:
        from ..emby_client import EmbyClient

        cli = EmbyClient(self.edit_emby_url.text(), self.edit_emby_key.text())
        ok, msg = cli.test_connection()
        self.emby_status_lab.setText(msg)
        if ok:
            self.emby_status_lab.setStyleSheet("font-size: 12px; color: green;")
        else:
            self.emby_status_lab.setStyleSheet("font-size: 12px; color: red;")

    # ============================================================ AI 助手
    def _ai_group(self) -> QWidget:
        g = QGroupBox("🤖 AI 助手（仅用于“新站点解析规则生成”，可完全关闭）")
        form = QFormLayout(g)

        self.chk_ai = QCheckBox("启用 AI 助手（未启用时新模块向导只用本地推导）")
        self.chk_ai.toggled.connect(self._ai_toggle)
        form.addRow("", self.chk_ai)

        self.ai_provider_combo = NoWheelComboBox()
        for key, lab in (("external", "外部 API（DeepSeek / OpenAI 兼容服务）"),
                         ("local", "本机（Ollama / LM Studio）")):
            self.ai_provider_combo.addItem(lab, key)
        self.ai_provider_combo.currentIndexChanged.connect(self._ai_provider_changed)
        form.addRow("服务提供商", self.ai_provider_combo)

        self.edit_ai_url = QLineEdit()
        form.addRow("服务地址 base_url", self.edit_ai_url)

        self.edit_ai_model = QLineEdit()
        form.addRow("模型名 model", self.edit_ai_model)

        self.edit_ai_key = QLineEdit()
        self.edit_ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_ai_key.setPlaceholderText("本机 Ollama 一般无需填写")
        form.addRow("API Key", self.edit_ai_key)

        test_row = QHBoxLayout()
        self.btn_ai_test = QPushButton("测试连接")
        self.btn_ai_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_test.clicked.connect(self._ai_test)
        test_row.addWidget(self.btn_ai_test)
        self.btn_ai_wizard = QPushButton("🧭 新模块向导")
        self.btn_ai_wizard.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_wizard.clicked.connect(self._ai_open_wizard)
        test_row.addWidget(self.btn_ai_wizard)
        self.ai_status_lab = QLabel("")
        self.ai_status_lab.setStyleSheet("font-size:12px; color:#64748b;")
        self.ai_status_lab.setWordWrap(True)
        test_row.addWidget(self.ai_status_lab, 1)
        form.addRow("", test_row)

        tip = QLabel(
            "用途：给新站点自动生成解析规则（向导里可预览与修改）。\n"
            "· 发送内容 = 你主动分析的那个站点的页面样本（已去掉脚本/样式），不含账号信息；\n"
            "· API Key 用 Windows DPAPI 加密保存在本机配置中；\n"
            "· AI 结果必须经本地校验（结构 + 实测解析条数）才可采用，失败自动降级为本地推导。")
        tip.setStyleSheet("color:#64748b; font-size:11px;")
        tip.setWordWrap(True)
        form.addRow("", tip)
        return g

    def _ai_toggle(self, on: bool) -> None:
        for w in (self.ai_provider_combo, self.edit_ai_url, self.edit_ai_model,
                  self.edit_ai_key, self.btn_ai_test):
            w.setEnabled(bool(on))

    def _ai_provider_changed(self, _idx: int) -> None:
        from ..site.ai_client import provider_defaults

        key = self.ai_provider_combo.currentData()
        url, model, need_key = provider_defaults(key)
        if not (self.edit_ai_url.text() or "").strip():
            self.edit_ai_url.setText(url)
            self.edit_ai_url.setPlaceholderText(url)
        if not (self.edit_ai_model.text() or "").strip():
            self.edit_ai_model.setText(model)
            self.edit_ai_model.setPlaceholderText(model)
        self.edit_ai_key.setEnabled(need_key and self.chk_ai.isChecked())

    def _ai_test(self) -> None:
        from ..site.ai_client import test_connection

        cfg = dict(self.cfg.data)
        cfg["ai_enabled"] = True
        cfg["ai_base_url"] = self.edit_ai_url.text().strip()
        cfg["ai_model"] = self.edit_ai_model.text().strip()
        cfg["ai_api_key_enc"] = self._ai_key_token(self.edit_ai_key.text())
        ok, msg = test_connection(cfg, timeout=15)
        self.ai_status_lab.setText(("✓ " if ok else "✗ ") + msg)
        self.ai_status_lab.setStyleSheet(
            "font-size:12px; color:green;" if ok else "font-size:12px; color:red;")

    def _ai_key_token(self, plain: str) -> str:
        """明文 Key → 加密 token；留空表示沿用已保存的 Key。"""
        from ..dpapi import encrypt_text

        plain = (plain or "").strip()
        return encrypt_text(plain) if plain else \
            str(self.cfg.get("ai_api_key_enc", "") or "")

    def _ai_open_wizard(self) -> None:
        try:
            from .analyze_dialog import AnalyzeDialog

            dlg = AnalyzeDialog(self.ctl, self)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "无法打开向导", f"{type(e).__name__}: {e}")

    # ============================================================ 自定义模块
    def _modules_group(self) -> QWidget:
        g = QGroupBox("🧩 自定义模块与健康度")
        lay = QVBoxLayout(g)
        self.mods_table = QTableWidget(0, 4)
        self.mods_table.setHorizontalHeaderLabels(
            ["模块 ID", "名称", "来源", "健康度"])
        hh = self.mods_table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.mods_table.verticalHeader().setVisible(False)
        self.mods_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mods_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mods_table.setMinimumHeight(140)
        lay.addWidget(self.mods_table)

        row = QHBoxLayout()
        for text, fn in (("🧭 新建模块", self._ai_open_wizard),
                         ("删除模块", self._mod_delete),
                         ("打开规则目录", self._mod_open_dir),
                         ("重新加载", self._mod_reload)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        tip = QLabel(
            "· 用户规则放 data/modules/<id>.json，**同 ID 会覆盖内置模块**"
            "（站点改版时可先改规则应急）；\n"
            "· 健康度 = 最近一次解析的条目数与资源命中率；连续 0 条会黄字提示“可能已改版”，"
            "此时可用上方向导重新分析。")
        tip.setStyleSheet("color:#64748b; font-size:11px;")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return g

    def reload_modules(self) -> None:
        from ..site.modules import list_modules
        from ..site.modules.health import describe, load
        from ..site.modules.rule_store import list_rule_files, rules_dir

        user_files = {os.path.basename(p)[:-5].lower()
                      for p in list_rule_files(user_only=True)}
        mods = sorted(list_modules(), key=lambda m: (m.builtin, m.module_id))
        self.mods_table.setRowCount(0)
        self.mods_table.setRowCount(len(mods))
        for r, meta in enumerate(mods):
            src = "用户规则" if meta.module_id.lower() in user_files else "内置模块"
            info = load(self.db, meta.module_id)
            self.mods_table.setItem(r, 0, QTableWidgetItem(meta.module_id))
            self.mods_table.setItem(r, 1, QTableWidgetItem(meta.name or ""))
            self.mods_table.setItem(r, 2, QTableWidgetItem(src))
            lab = QTableWidgetItem(describe(info))
            if info.get("warn"):
                lab.setForeground(Qt.GlobalColor.darkYellow)
            self.mods_table.setItem(r, 3, lab)
        self._rules_dir = rules_dir()

    def _mod_selected_id(self) -> str:
        sel = self.mods_table.selectionModel().selectedRows()
        if not sel:
            return ""
        return (self.mods_table.item(sel[0].row(), 0).text() or "").strip()

    def _mod_delete(self) -> None:
        mid = self._mod_selected_id()
        if not mid:
            QMessageBox.information(self, "提示", "请先选中一个模块")
            return
        from ..site.modules.rule_store import delete_rule

        if not delete_rule(mid):
            QMessageBox.information(
                self, "提示",
                f"「{mid}」没有对应的用户规则文件（内置模块不能删除）")
            return
        self._mod_reload()

    def _mod_open_dir(self) -> None:
        path = getattr(self, "_rules_dir", "") or rules_dir()
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # noqa: S606  仅打开本机目录
        except Exception as e:
            QMessageBox.information(self, "规则目录", f"{path}\n（{e}）")

    def _mod_reload(self) -> None:
        from ..site.modules.registry import reload_external_modules

        n = reload_external_modules()
        self.reload_modules()
        self.reload_sites()
        self.mods_log_hint = f"已重新加载，用户规则模块 {n} 个"

    # ============================================================ 搜索
    def _search_group(self) -> QWidget:
        g = QGroupBox("🔍 关键词搜索")
        form = QFormLayout(g)

        self.spin_search_limit = QSpinBox()
        self.spin_search_limit.setRange(10, 500)
        self.spin_search_limit.setSingleStep(10)
        form.addRow("每站点结果上限", self.spin_search_limit)

        self.spin_search_pages = QSpinBox()
        self.spin_search_pages.setRange(1, 5)
        form.addRow("每站点翻页数", self.spin_search_pages)

        self.spin_search_conc = QSpinBox()
        self.spin_search_conc.setRange(1, 8)
        form.addRow("跨站点并发数", self.spin_search_conc)

        self.spin_search_hist = QSpinBox()
        self.spin_search_hist.setRange(0, 100)
        form.addRow("历史关键词保留条数", self.spin_search_hist)

        self.spin_search_auto = QSpinBox()
        self.spin_search_auto.setRange(0, 50)
        form.addRow("搜索后自动解析前 N 条详情", self.spin_search_auto)

        self.spin_search_delay = QDoubleSpinBox()
        self.spin_search_delay.setRange(0.0, 5.0)
        self.spin_search_delay.setSingleStep(0.1)
        self.spin_search_delay.setSuffix(" 秒")
        form.addRow("搜索请求间隔（越大越礼貌）", self.spin_search_delay)

        tip = QLabel(
            "· 搜索结果**不入库**；“自动解析前 N 条详情”会在搜索后自动抓取资源"
            "（磁力 / .torrent 附件 / 网盘），否则需手动点“解析所选详情”；\n"
            "· 站点对高频搜索敏感（返回“信息提示”短页），默认已开启会话预热；"
            "若仍频繁失败，请把并发调到 1 并增大间隔。")
        tip.setStyleSheet("color:#64748b; font-size:11px;")
        tip.setWordWrap(True)
        form.addRow(tip)
        return g

    # ============================================================ 通用
    def _general_group(self) -> QWidget:
        g = QGroupBox("⚙️ 通用偏好设置")
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
        self.chk_boot = QCheckBox("开机自动启动 6vdown")
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

        self.conc_spin = QSpinBox()
        self.conc_spin.setRange(1, 8)
        self.conc_spin.setSuffix(" 个")
        form.addRow("详情页并发抓取", self.conc_spin)
        conc_tip = QLabel(
            "同时抓取几个详情页：1=最礼貌（串行）；慢站点（如论坛）可调到 3-4 提速。"
            "相同详情页在同一次解析中只会抓一次（跨版块自动去重）。")
        conc_tip.setStyleSheet("color:#64748b; font-size:11px;")
        conc_tip.setWordWrap(True)
        form.addRow("", conc_tip)

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
            wb.load_items([], mark_new=[])
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
        c["detail_concurrency"] = self.conc_spin.value()
        c["enabled_blocks"] = [cb.text().replace("★ ", "")
                               for cb in self.block_checks if cb.isChecked()]
        # 订阅与 Emby
        c["sub_auto_on_startup"] = self.chk_sub_startup.isChecked()
        c["sub_auto_direct_download"] = self.chk_sub_direct.isChecked()
        c["sub_scheduler_enabled"] = self.chk_sub_sched.isChecked()
        c["sub_interval_hours"] = self.sub_sched_spin.value()
        c["quality_priority"] = [self.q_list.item(i).text()
                                 for i in range(self.q_list.count())]
        c["emby_enabled"] = self.chk_emby.isChecked()
        c["emby_server_url"] = self.edit_emby_url.text().strip()
        c["emby_api_key"] = self.edit_emby_key.text().strip()
        # AI 助手（Key 加密存储）
        c["ai_enabled"] = self.chk_ai.isChecked()
        c["ai_provider"] = self.ai_provider_combo.currentData() or "external"
        c["ai_base_url"] = self.edit_ai_url.text().strip()
        c["ai_model"] = self.edit_ai_model.text().strip()
        c["ai_api_key_enc"] = self._ai_key_token(self.edit_ai_key.text())
        # 搜索
        c["search_limit"] = self.spin_search_limit.value()
        c["search_max_pages"] = self.spin_search_pages.value()
        c["search_concurrency"] = self.spin_search_conc.value()
        c["search_history_size"] = self.spin_search_hist.value()
        c["search_auto_detail"] = self.spin_search_auto.value()
        c["search_polite_delay"] = round(self.spin_search_delay.value(), 2)
        c.save()
        self.ctl.apply_settings()
        self.ctl.notify_ok("设置已保存", "下载主机、订阅与 Emby 偏好已生效。")

    def reload(self) -> None:
        self.reload_hosts()
        self.reload_mirrors()
        self.reload_sites()
        self.reload_modules()
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
        self.conc_spin.setValue(int(c.get("detail_concurrency", 2) or 1))
        self.toast_spin.setValue(int(c["notify_seconds"]))
        enabled = set(c["enabled_blocks"])
        for cb in self.block_checks:
            cb.setChecked(cb.text().replace("★ ", "") in enabled)
        # 订阅与 Emby
        self.chk_sub_startup.setChecked(bool(c.get("sub_auto_on_startup", True)))
        self.chk_sub_direct.setChecked(bool(c.get("sub_auto_direct_download", False)))
        self.chk_sub_sched.setChecked(bool(c.get("sub_scheduler_enabled", True)))
        self.sub_sched_spin.setValue(int(c.get("sub_interval_hours", 4)))
        self._reload_quality_list(c.get("quality_priority"))
        self.chk_emby.setChecked(bool(c.get("emby_enabled", False)))
        self.edit_emby_url.setText(c.get("emby_server_url", ""))
        self.edit_emby_key.setText(c.get("emby_api_key", ""))
        # AI 助手（Key 不明文回填：已保存显示占位，留空=沿用）
        self.chk_ai.setChecked(bool(c.get("ai_enabled", False)))
        self._set_combo(self.ai_provider_combo, c.get("ai_provider", "external"))
        self.edit_ai_url.setText(c.get("ai_base_url", ""))
        self.edit_ai_model.setText(c.get("ai_model", ""))
        from ..dpapi import decrypt_text

        saved_key = decrypt_text(c.get("ai_api_key_enc", "") or "")
        self.edit_ai_key.setText(saved_key)
        self.edit_ai_key.setPlaceholderText(
            "已保存的 Key 已解密显示；本机 Ollama 可留空")
        self._ai_toggle(self.chk_ai.isChecked())
        # 搜索
        self.spin_search_limit.setValue(int(c.get("search_limit", 80) or 80))
        self.spin_search_pages.setValue(int(c.get("search_max_pages", 1) or 1))
        self.spin_search_conc.setValue(int(c.get("search_concurrency", 2) or 2))
        self.spin_search_hist.setValue(int(c.get("search_history_size", 20) or 20))
        self.spin_search_auto.setValue(int(c.get("search_auto_detail", 8) or 0))
        self.spin_search_delay.setValue(
            float(c.get("search_polite_delay", 0.3) or 0.0))

    @staticmethod
    def _set_combo(combo: QComboBox, key) -> None:
        i = combo.findData(key)
        combo.setCurrentIndex(i if i >= 0 else 0)



