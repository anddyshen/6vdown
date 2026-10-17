"""『我的订阅』管理页面：展示所有订阅剧集、状态切换、手动检查、删除与历史查看。"""
from __future__ import annotations

import time
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Subscription
from ..pinyin_search import match as py_match


def _fmt_ts(ms: int) -> str:
    if not ms:
        return "-"
    return time.strftime("%m-%d %H:%M", time.localtime(ms / 1000))


class SubscriptionPage(QWidget):
    check_all_clicked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.db = controller.db
        self._subs: list[Subscription] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # 顶部工具栏
        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索已订阅剧集（支持拼音首字母）……")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search)
        bar.addWidget(self.search_edit, 1)

        self.btn_check_all = QPushButton("⚡ 立即检查全部更新")
        self.btn_check_all.setObjectName("primary")
        self.btn_check_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_all.clicked.connect(self.check_all_clicked.emit)
        bar.addWidget(self.btn_check_all)

        self.btn_refresh = QPushButton("刷新列表")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.reload)
        bar.addWidget(self.btn_refresh)
        root.addLayout(bar)

        # 订阅表格
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["剧名 / 订阅项目", "状态", "最近检测进度", "Emby联动", "更新时间", "操作"]
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 180)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        # 底部状态
        bottom = QHBoxLayout()
        self.count_label = QLabel("共订阅 0 部剧集")
        self.count_label.setStyleSheet("color: #64748b; font-weight: 500;")
        bottom.addWidget(self.count_label)
        bottom.addStretch(1)
        root.addLayout(bottom)

    def reload(self) -> None:
        self._subs = self.db.list_subscriptions()
        self._render(self._subs)

    def _render(self, subs: list[Subscription]) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(subs))
        for row, sub in enumerate(subs):
            # 剧名
            t_item = QTableWidgetItem(sub.title)
            t_item.setToolTip(f"{sub.title}\n详情: {sub.detail_url}")
            self.table.setItem(row, 0, t_item)

            # 状态
            st_text = {"active": "追剧中", "paused": "已暂停", "completed": "已完结"}.get(sub.status, sub.status)
            st_item = QTableWidgetItem(st_text)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if sub.status == "active":
                st_item.setForeground(Qt.GlobalColor.darkGreen)
            elif sub.status == "completed":
                st_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 1, st_item)

            # 最新进度
            ep_item = QTableWidgetItem(sub.last_ep or "未检测")
            ep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, ep_item)

            # Emby 状态
            emby_text = "已关联" if sub.emby_series_id else "自动匹配"
            emby_item = QTableWidgetItem(emby_text)
            emby_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, emby_item)

            # 更新时间
            time_item = QTableWidgetItem(_fmt_ts(sub.updated_at))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, time_item)

            # 操作按钮
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(4, 2, 4, 2)
            h.setSpacing(6)

            b_toggle = QPushButton("暂停" if sub.status == "active" else "启用")
            b_toggle.setFixedSize(54, 26)
            b_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            b_toggle.clicked.connect(lambda _=False, s=sub: self._toggle_status(s))
            h.addWidget(b_toggle)

            b_check = QPushButton("检查")
            b_check.setFixedSize(50, 26)
            b_check.setCursor(Qt.CursorShape.PointingHandCursor)
            b_check.clicked.connect(lambda _=False, s=sub: self.ctl.check_single_subscription(s))
            h.addWidget(b_check)

            b_del = QPushButton("删除")
            b_del.setObjectName("danger")
            b_del.setFixedSize(50, 26)
            b_del.setCursor(Qt.CursorShape.PointingHandCursor)
            b_del.clicked.connect(lambda _=False, sid=sub.id, name=sub.title: self._delete(sid, name))
            h.addWidget(b_del)
            h.addStretch(1)

            self.table.setCellWidget(row, 5, cell)
            self.table.setRowHeight(row, 38)

        self.count_label.setText(f"共订阅 {len(subs)} 部剧集")

    def _on_search(self, text: str) -> None:
        q = (text or "").strip().lower()
        if not q:
            self._render(self._subs)
            return
        filtered = [s for s in self._subs if py_match([s.title], q)]
        self._render(filtered)

    def _toggle_status(self, sub: Subscription) -> None:
        sub.status = "paused" if sub.status == "active" else "active"
        self.db.update_subscription(sub)
        self.reload()

    def _delete(self, sub_id: int, name: str) -> None:
        if QMessageBox.question(self, "确认删除", f"确定取消对《{name}》的更新订阅？") == QMessageBox.StandardButton.Yes:
            self.db.delete_subscription(sub_id)
            self.reload()

