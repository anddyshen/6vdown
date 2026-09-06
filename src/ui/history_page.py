"""操作历史记录：查询 / 删除 / 再次触发添加。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import now_str, task_from_row


class HistoryPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self.on_re_send = None
        self.on_delete = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题 / 链接 / 主机……")
        self.search.returnPressed.connect(self.refresh)
        bar.addWidget(self.search, 1)
        btn_find = QPushButton("查询")
        btn_find.clicked.connect(self.refresh)
        bar.addWidget(btn_find)
        self.count_label = QLabel("")
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        btn_retry = QPushButton("再次发送选中")
        btn_retry.clicked.connect(self._retry)
        bar.addWidget(btn_retry)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._delete)
        bar.addWidget(btn_del)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_refresh)
        root.addLayout(bar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "时间", "标题", "来源", "目标主机", "状态", "链接"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for col, w in ((0, 46), (1, 150), (3, 88), (4, 120), (5, 90)):
            self.table.setColumnWidth(col, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(lambda _it: self._retry())
        root.addWidget(self.table, 1)
        self.refresh()

    # -------------------------------------------------------------
    def refresh(self) -> None:
        kw = self.search.text().strip()
        tasks = self._db.list_tasks(limit=800, keyword=kw)
        self._tasks = tasks
        self.table.setRowCount(0)
        self.table.setRowCount(len(tasks))
        for row, t in enumerate(tasks):
            self.table.setItem(row, 0, QTableWidgetItem(str(t.id or "")))
            self.table.setItem(row, 1, QTableWidgetItem(_ts(t)))
            self.table.setItem(row, 2, QTableWidgetItem(t.title or ""))
            self.table.setItem(row, 3, QTableWidgetItem(_src(t.source)))
            self.table.setItem(row, 4, QTableWidgetItem(t.host_name or ""))
            s = "成功" if t.status == "ok" else ("失败" if t.status == "fail" else t.status)
            item = QTableWidgetItem(s)
            item.setForeground(Qt.GlobalColor.darkGreen if t.status == "ok"
                               else Qt.GlobalColor.red if t.status == "fail"
                               else Qt.GlobalColor.gray)
            self.table.setItem(row, 5, item)
            link_item = QTableWidgetItem(t.link[:120] if t.link else "")
            link_item.setToolTip(f"{t.link}\n{t.message}")
            self.table.setItem(row, 6, link_item)
        self.count_label.setText(f"{len(tasks)} 条")
        if not tasks:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("（暂无记录）"))
            self.table.setSpan(0, 0, 1, 7)

    def selected_tasks(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self._tasks[r] for r in rows if r < len(self._tasks)]

    def _retry(self) -> None:
        for t in self.selected_tasks():
            if self.on_re_send:
                self.on_re_send(t)

    def _delete(self) -> None:
        tasks = self.selected_tasks()
        if not tasks:
            return
        for t in tasks:
            self._db.delete_task(t.id)
            if self.on_delete:
                self.on_delete(t)
        self.refresh()


def _ts(t) -> str:
    import time

    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.created_at / 1000))
    except Exception:
        return ""


def _src(s: str) -> str:
    return {"clipboard": "剪贴板", "drop": "拖拽", "site": "网站解析",
            "manual": "手动", "history": "历史重发"}.get(s, s or "")
