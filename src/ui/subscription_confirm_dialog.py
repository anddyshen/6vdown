"""订阅更新汇聚确认对话框：汇聚新更新剧集、展示挑选出的最佳画质、批量选择与一键推送。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class SubscriptionConfirmDialog(QDialog):
    """弹出汇聚所有最新订阅资源的确认弹窗。"""

    def __init__(self, updates: list[dict], on_confirm, parent=None):
        super().__init__(parent)
        self.updates = updates
        self._on_confirm = on_confirm
        self.setWindowTitle("🔔 发现订阅剧集最新更新")
        self.resize(760, 460)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        tip = QLabel(f"本次共扫描发现 <b>{len(self.updates)}</b> 条最新的未下载剧集磁力，请确认是否推送到下载器：")
        tip.setStyleSheet("font-size: 13px;")
        lay.addWidget(tip)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "订阅剧名", "集数", "优选画质", "磁力标题 / 来源"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        self.table.setRowCount(len(self.updates))
        for row, u in enumerate(self.updates):
            # 勾选框
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk)

            # 剧名
            self.table.setItem(row, 1, QTableWidgetItem(u["sub_title"]))

            # 集数
            ep_item = QTableWidgetItem(u["ep_label"])
            ep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, ep_item)

            # 画质
            q_item = QTableWidgetItem(f"★ {u['quality']}")
            q_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            q_item.setForeground(Qt.GlobalColor.darkBlue)
            self.table.setItem(row, 3, q_item)

            # 磁力标题
            m_item = QTableWidgetItem(u["magnet_label"] or u["magnet_url"][:60])
            m_item.setToolTip(f"{u['magnet_label']}\n{u['magnet_url']}")
            self.table.setItem(row, 4, m_item)

        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        chk_all = QCheckBox("全选 / 取消全选")
        chk_all.setChecked(True)
        chk_all.stateChanged.connect(self._toggle_all)
        bottom.addWidget(chk_all)
        bottom.addStretch(1)

        btn_cancel = QPushButton("暂不下载")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        btn_send = QPushButton("一键全部推送到下载器")
        btn_send.setObjectName("primary")
        btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_send.clicked.connect(self._do_confirm)
        bottom.addWidget(btn_send)
        lay.addLayout(bottom)

    def _toggle_all(self, state: int) -> None:
        chk = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(chk)

    def _do_confirm(self) -> None:
        selected_tasks = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                selected_tasks.append(self.updates[r])
        if not selected_tasks:
            self.reject()
            return
        self._on_confirm(selected_tasks)
        self.accept()

