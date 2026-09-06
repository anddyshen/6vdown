"""解析工作台：解析控制 + 结果列表 + 分集磁力对话框。"""
from __future__ import annotations

import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ParseItem
from ..pinyin_search import match as py_match
from .icons import star_pixmap

COL_SEL, COL_STAR, COL_TITLE, COL_BLOCK, COL_DATE, COL_MAG, COL_OP = range(7)


def fmt_time() -> str:
    return time.strftime("%H:%M:%S")


class SortItem(QTableWidgetItem):
    """带排序键的表格项：日期按时间、磁力数按数值、文字按忽略大小写比较。"""

    def __init__(self, text: str = "", key=None):
        super().__init__(text)
        self._key = key if key is not None else text

    def __lt__(self, other) -> bool:
        if isinstance(other, SortItem):
            return self._key < other._key
        return super().__lt__(other)


def date_sort_key(d: str):
    if not d:
        return (9999, 0, 0)
    parts = str(d).split("-")
    try:
        if len(parts) == 3:
            y, mo, dd = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            y, mo, dd = 2099, int(parts[0]), int(parts[1])
    except Exception:
        return (9999, 0, 0)
    return (y, mo, dd)


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _cn_int(s: str):
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    total = 0
    num = 0
    for ch in str(s):
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (num or 1) * unit
            num = 0
        else:
            num = 0
    return total + num


def _ep_meta(name: str):
    """从组名提取 (季, 集)。如 S01E05 / 第1季第5集 / 第156集。"""
    text = (name or "").strip()
    s = e = None
    m = re.search(r"[Ss](\d{1,3})\s*[Ee](\d{1,4})", text)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"第\s*([0-9]{1,3}|[一二三四五六七八九十百千两零]+)\s*季", text)
        if m:
            s = _cn_int(m.group(1))
        m = re.search(r"[Ee](\d{1,4})", text)
        if m:
            e = int(m.group(1))
        if e is None:
            m = re.search(r"第\s*([0-9]{1,4}|[一二三四五六七八九十百千两零]+)\s*集", text)
            if m:
                e = _cn_int(m.group(1))
    return s, e


def sort_episode_groups(groups: dict) -> list:
    """多集排序：同一季相邻；季号大在前；同季最新一集（集号大）在前；
    无季号但带集号的按集号倒序；最终尽量保证第一条是“最新一集”。"""
    items = list(groups.items())
    metas = [(nm, *_ep_meta(nm)) for nm, _ in items]
    any_season = any(s is not None for _, s, _ in metas)

    def tier(i):
        s = metas[i][1]
        return 0 if s is not None else (1 if any_season else 0)

    def has_num(i):
        s, e = metas[i][1], metas[i][2]
        return s is not None or e is not None

    if any_season:
        # 有季：先按季降序，再按该季集数降序；无季但带集数者随后（集倒序）
        def key(i):
            s, e = metas[i][1], metas[i][2]
            if s is not None:
                return (0, -s, -(e if e is not None else 0), i)
            if e is not None:
                return (1, 0, -e, i)
            return (2, 0, 0, i)
    else:
        def key(i):
            s, e = metas[i][1], metas[i][2]
            if e is not None:
                return (0, -e, i)
            if s is not None:
                return (0, 0, i)
            return (1, 0, i)

    ordered_idx = sorted(range(len(items)), key=key)
    ordered = [items[i] for i in ordered_idx]

    # 保险：若存在可解析集号且第一条不是“最新候选”，把最新的一条移到最上
    numbered = [i for i in ordered_idx if has_num(i)]
    if numbered and ordered_idx:
        def metric(i):
            s, e = metas[i][1], metas[i][2]
            # 有季者优先按季，其次集号；无季按集号（视作较新的连续更新）
            if s is not None:
                return (0, s, e if e is not None else 0)
            return (1, 0, e if e is not None else 0)
        best = max(numbered, key=metric)
        first_metric = metric(ordered_idx[0])
        if metric(best) != first_metric:
            # 把 best 项移到最前（保持其余相对顺序）
            ordered = [items[best]] + [items[i] for i in ordered_idx if i != best]
    return ordered


class ClickableLabel(QLabel):
    """支持双击触发复制等操作的可点击文本。"""

    double_clicked = Signal(str)

    def __init__(self, text: str = "", url: str = ""):
        super().__init__(text)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D102
        if self._url:
            self.double_clicked.emit(self._url)
        super().mouseDoubleClickEvent(event)


class MagnetDialog(QDialog):
    """按分集列出某资源全部磁力，可逐条发送/复制。"""

    def __init__(self, item: ParseItem, on_send, on_copy, parent=None):
        super().__init__(parent)
        self._item = item
        self._on_send = on_send
        self._on_copy = on_copy
        self.setWindowTitle("磁力链接")
        self.setMinimumSize(640, 420)
        lay = QVBoxLayout(self)
        head = QLabel(f"{item.title}   [{item.date}]")
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: 600;")
        lay.addWidget(head)
        desc = QLabel((item.desc or "")[:300])
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 12px;")
        lay.addWidget(desc)
        if not item.magnets:
            lay.addWidget(QLabel("（此资源暂未解析到磁力链接）"))
            btn = QPushButton("关闭")
            btn.clicked.connect(self.accept)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
            return
        groups = item.episode_groups()
        # 按季排序：同一季相邻 → 季号大在前 → 同季集号大在前（最新一集在最上）
        ordered = sort_episode_groups(groups)

        all_btn = QPushButton("发送全部磁力到下载器")
        all_btn.setObjectName("primary")
        all_btn.clicked.connect(lambda: self._send_all())
        lay.addWidget(all_btn, 0, Qt.AlignmentFlag.AlignRight)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 4, 4)
        for group_name, magnets in ordered:
            v.addWidget(QLabel(f"▸ {group_name}  （{len(magnets)} 个）"))
            for ml in magnets:
                row = QHBoxLayout()
                full = (ml.label or "").strip()
                name_text = full if len(full) <= 160 else full[:157] + "…"
                name_lab = QLabel(name_text if name_text else ml.url[:60])
                name_lab.setToolTip(full or ml.url)
                name_lab.setWordWrap(False)
                name_lab.setStyleSheet("font-size:12px;")
                # 链接只显示前一小段，双击可复制完整链接
                link_show = (ml.url[:46] + "…") if len(ml.url) > 46 else ml.url
                link_lab = ClickableLabel(link_show, ml.url)
                link_lab.setToolTip(f"{ml.url}\n双击复制")
                link_lab.setStyleSheet("color:#7f8ea3; font-size:11px;")
                link_lab.double_clicked.connect(self._copy)
                b_send = QPushButton("发送")
                b_send.setFixedWidth(54)
                b_send.clicked.connect(lambda _=False, u=ml.url: self._send(u))
                b_copy = QPushButton("复制")
                b_copy.setFixedWidth(54)
                b_copy.clicked.connect(lambda _=False, u=ml.url: self._copy(u))
                row.addWidget(name_lab, 1)
                row.addWidget(link_lab, 0)
                row.addWidget(b_send)
                row.addWidget(b_copy)
                v.addLayout(row)
            v.addSpacing(6)
        v.addStretch(1)
        inner.setLayout(v)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _send(self, url: str) -> None:
        self._on_send(self._item, url)

    def _copy(self, url: str) -> None:
        self._on_copy(url)

    def _send_all(self) -> None:
        for m in list(self._item.magnets):
            self._on_send(self._item, m.url)


class WorkbenchPage(QWidget):
    parse_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._base_items: list = []
        self._row_index: dict = {}
        self._mark_new: set = set()
        self.on_magnet_list = None
        self.on_add_single = None
        self.on_open_detail = None
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.mirror_label = QLabel("解析源：-")
        self.mirror_label.setStyleSheet("font-weight:600;")
        bar.addWidget(self.mirror_label)
        bar.addStretch(1)
        self.status_label = QLabel("待激活 · 尚未解析")
        self.status_label.setStyleSheet("color:#888;")
        bar.addWidget(self.status_label)
        self.btn_console = QPushButton("控制台")
        self.btn_console.setCheckable(True)
        self.btn_console.setChecked(False)
        bar.addWidget(self.btn_console)
        self.btn_parse = QPushButton("▶ 开始解析")
        self.btn_parse.setObjectName("primary")
        self.btn_parse.clicked.connect(self._on_parse)
        bar.addWidget(self.btn_parse)
        root.addLayout(bar)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("筛选："))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "输入标题关键词或拼音首字母过滤（如 dy = 电影）……")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_edit, 1)
        root.addLayout(search_row)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, COL_OP + 1)
        self.table.setHorizontalHeaderLabels(
            ["", "星", "电影名称 / 简介", "区块", "日期", "磁力", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(
            COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col, w in ((COL_SEL, 34), (COL_STAR, 30), (COL_BLOCK, 92),
                       (COL_DATE, 76), (COL_MAG, 54), (COL_OP, 128)):
            self.table.setColumnWidth(col, w)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self._sort_col = -1
        self._sort_asc = True
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        self.splitter.addWidget(self.table)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1500)
        self.console.setStyleSheet(
            "QPlainTextEdit{background:#14151a; color:#cfd6e4;"
            "font-family:Consolas,'Courier New',monospace; font-size:12px;"
            "border:1px solid #222;}")
        self.console.hide()
        self.splitter.addWidget(self.console)
        self.splitter.setStretchFactor(0, 6)
        self.splitter.setStretchFactor(1, 3)
        root.addWidget(self.splitter, 1)
        self.btn_console.toggled.connect(self.console.setVisible)
        self.btn_console.toggled.connect(self._on_console_toggled)

        bottom = QHBoxLayout()
        self.chk_all = QCheckBox("全选")
        self.chk_all.stateChanged.connect(self._toggle_all)
        bottom.addWidget(self.chk_all)
        self.sum_label = QLabel("共 0 条")
        bottom.addWidget(self.sum_label)
        bottom.addStretch(1)
        self.btn_restore_new = QPushButton("恢复新增排序")
        self.btn_restore_new.clicked.connect(self.restore_new_first)
        bottom.addWidget(self.btn_restore_new)
        self.btn_add_selected = QPushButton("添加选中到下载器 (0)")
        self.btn_add_selected.setObjectName("primary")
        self.btn_add_selected.clicked.connect(self._add_selected)
        bottom.addWidget(self.btn_add_selected)
        root.addLayout(bottom)

    # ------------------------------------------------------------ 运行控制
    def _on_parse(self) -> None:
        if self.btn_parse.text().startswith("■"):
            self.stop_clicked.emit()
        else:
            self.parse_clicked.emit()

    def set_running(self, running: bool, site: str = "") -> None:
        if site:
            self.mirror_label.setText(f"解析源：{site}")
        if running:
            self.btn_parse.setText("■ 停止解析")
            self.status_label.setText("解析进行中……")
        else:
            self.btn_parse.setText("▶ 开始解析")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def append_log(self, line: str) -> None:
        self.console.appendPlainText(f"[{fmt_time()}] {line}")

    def _on_console_toggled(self, visible: bool) -> None:
        if visible:
            self.append_log("控制台视图已展开，解析输出实时刷新中……")
    # ------------------------------------------------------------ 数据展示
    def load_items(self, items: list, summary: dict | None = None,
                   mark_new=None) -> None:
        """items: list[ParseItem]（展示数据）。

        mark_new: 本次解析新增 detail_url 集合。传入时：
        - 新增记录置顶显示（内部按日期倒序，最新在最上）；
        - 新增行高亮 + 标题加“〔新〕”标识。
        未传入（如表头排序重载）则沿用上一次的新增标识。
        """
        if mark_new is not None:
            self._mark_new = {str(u) for u in mark_new if u}
            self._base_items = list(items)
            q = (self.search_edit.text() or "").strip().lower()
            if q:
                items = [it for it in items if self._match_item(it, q)]
        new_set = self._mark_new
        if mark_new is not None and new_set:
            def is_fresh(it):
                return bool(it.detail_url and it.detail_url in new_set)
            fresh = [it for it in items if is_fresh(it)]
            if fresh:
                fresh.sort(key=lambda it: date_sort_key(it.date), reverse=True)
                items = fresh + [it for it in items if not is_fresh(it)]
        self._items = list(items)
        self._row_index = {}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._items))
        star = QIcon(star_pixmap(16))
        dark = self.palette().color(QPalette.ColorRole.Window).lightnessF() < 0.5
        bg_hex, fg_hex = ("#3d3105", "#fcd34d") if dark else ("#fff3cd", "#92400e")
        bg_brush, fg_brush = QBrush(QColor(bg_hex)), QBrush(QColor(fg_hex))
        flagged = 0
        for row, it in enumerate(self._items):
            is_new = bool(it.detail_url and it.detail_url in new_set)
            if is_new:
                flagged += 1
            self._row_index[it.detail_url or row] = row
            # 勾选列
            c0 = QTableWidgetItem()
            c0.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            c0.setCheckState(Qt.CheckState.Unchecked)
            c0.setData(Qt.ItemDataRole.UserRole, it.detail_url or "")
            if is_new:
                c0.setBackground(bg_brush)
            self.table.setItem(row, COL_SEL, c0)
            # 星标列
            if it.is_red or it.is_classic:
                cs = QTableWidgetItem()
                cs.setIcon(star)
                cs.setToolTip("重要资源：" + ("红链推荐 " if it.is_red else "") +
                              ("含“经典”" if it.is_classic else ""))
                if is_new:
                    cs.setBackground(bg_brush)
                self.table.setItem(row, COL_STAR, cs)
            # 标题列
            title = it.title or "(无标题)"
            if it.error:
                title += "  ⚠"
            show_title = ("〔新〕 " + title) if is_new else title
            desc_line = (it.desc or "").replace("\n", " ")[:160]
            if it.magnets:
                desc_line += f"（{len(it.magnets)} 个磁力）"
            text = show_title if not desc_line else f"{show_title}\n{desc_line}"
            ct = SortItem(text, key=title.lower())
            ct.setToolTip(f"{title}\n{it.desc or ''}\n详情: {it.detail_url}")
            f = ct.font()
            f.setPointSize(10)
            ct.setFont(f)
            if is_new:
                ct.setBackground(bg_brush)
                ct.setForeground(fg_brush)
            self.table.setItem(row, COL_TITLE, ct)
            # 区块 / 日期 / 磁力数
            b_item = SortItem(it.block or "其他")
            d_item = SortItem(it.date or "", key=date_sort_key(it.date))
            mag_text = (str(len(it.magnets)) if it.detail_ok or it.magnets
                        else ("-" if not it.detail_url else "?"))
            m_item = SortItem(mag_text,
                              key=int(mag_text) if mag_text.isdigit() else 0)
            if is_new:
                for _i in (b_item, d_item, m_item):
                    _i.setBackground(bg_brush)
            self.table.setItem(row, COL_BLOCK, b_item)
            self.table.setItem(row, COL_DATE, d_item)
            self.table.setItem(row, COL_MAG, m_item)
            # 操作按钮
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(2, 0, 2, 0)
            b_mag = QPushButton("详情")
            b_mag.setFixedSize(56, 24)
            b_mag.clicked.connect(lambda _=False, r=row: self._open_magnet(r))
            b_add = QPushButton("发送")
            b_add.setObjectName("primary")
            b_add.setFixedSize(56, 24)
            b_add.clicked.connect(lambda _=False, r=row: self._add_row(r))
            h.addWidget(b_mag)
            h.addWidget(b_add)
            h.addStretch(1)
            if is_new:
                cell.setObjectName("rowcell")
                cell.setStyleSheet(f"QWidget#rowcell{{background:{bg_hex}; border:none;}}")
            self.table.setCellWidget(row, COL_OP, cell)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        extra = f" · 本次新增 {flagged} 条已置顶并高亮" if flagged else ""
        self.sum_label.setText(f"共 {len(self._items)} 条{extra}")
        self._update_selected_count()
        if summary:
            self._show_summary(summary)

    @staticmethod
    def _visible_text(it) -> str:
        """构造与该行“电影名称/简介”单元格完全一致的可见文本。"""
        title = it.title or "(无标题)"
        if it.error:
            title += "  ⚠"
        desc_line = (it.desc or "").replace("\n", " ")[:160]
        if it.magnets:
            desc_line += f"（{len(it.magnets)} 个磁力）"
        return title if not desc_line else f"{title}\n{desc_line}"

    def _match_item(self, it, q: str) -> bool:
        return py_match([self._visible_text(it)], q)

    def _on_search_changed(self, text: str) -> None:
        q = (text or "").strip().lower()
        base = getattr(self, "_base_items", None)
        if base is None:
            return
        items = [it for it in base if self._match_item(it, q)] if q else list(base)
        self.load_items(items)

    def restore_new_first(self) -> None:
        """Restore display to fresh-first highlighted order."""
        if not self._items:
            return
        if not self._mark_new:
            self.set_status("当前没有“新增”标识，列表已按常规顺序显示")
            return
        fresh = [it for it in self._items
                 if it.detail_url and it.detail_url in self._mark_new]
        fresh.sort(key=lambda it: date_sort_key(it.date), reverse=True)
        rest = [it for it in self._items
                if not (it.detail_url and it.detail_url in self._mark_new)]
        self.load_items(fresh + rest)
        self.set_status("已按本次新增置顶恢复排序（新增 " + str(len(fresh)) + " 条）")


    # ------------------------------------------------------------ 自定义排序
    _COLUMN_KEYS = {
        COL_STAR: ("_star", False),
        COL_TITLE: ("title", False),
        COL_BLOCK: ("block", False),
        COL_DATE: ("date", True),
        COL_MAG: ("_mag_count", True),
    }

    def _on_header_clicked(self, col: int) -> None:
        if col not in self._COLUMN_KEYS:
            return
        attr, is_date = self._COLUMN_KEYS[col]
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        def keyfunc(it):
            if attr == "_mag_count":
                return len(getattr(it, "magnets", []) or [])
            if attr == "_star":
                return int(bool(getattr(it, "is_red", False))
                           or bool(getattr(it, "is_classic", False)))
            v = getattr(it, attr, "")
            if is_date:
                return date_sort_key(v)
            return (v or "").lower()

        ordered = sorted(self._items, key=keyfunc, reverse=not self._sort_asc)
        self.load_items(ordered)
        order = (Qt.SortOrder.AscendingOrder if self._sort_asc
                 else Qt.SortOrder.DescendingOrder)
        self.table.horizontalHeader().setSortIndicator(col, order)

    def _show_summary(self, s: dict) -> None:
        if s.get("ok"):
            n = s.get("new", 0)
            self.set_status(f"解析完成 · 新增 {n} 条 · 详见下方列表")
        else:
            self.set_status("解析失败：" + str(s.get("error", "未知错误")))

    def _items_checked(self) -> list:
        out = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, COL_SEL)
            if it and it.checkState() == Qt.CheckState.Checked:
                key = it.data(Qt.ItemDataRole.UserRole) or ""
                idx = self._row_index.get(key)
                if idx is not None and 0 <= idx < len(self._items):
                    out.append(self._items[idx])
        return out

    def _toggle_all(self, state: int) -> None:
        chk = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            it = self.table.item(row, COL_SEL)
            if it:
                it.setCheckState(chk)
        self._update_selected_count()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == COL_SEL:
            self._update_selected_count()

    def _update_selected_count(self) -> None:
        n = len(self._items_checked())
        self.btn_add_selected.setText(f"添加选中到下载器 ({n})")

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() == COL_SEL:
            self._update_selected_count()

    def _add_selected(self) -> None:
        items = self._items_checked()
        if not items:
            self.set_status("请先勾选要添加的条目")
            return
        for it in items:
            if self.on_add_single:
                self.on_add_single(it, None)  # None = 全部磁力

    def _add_row(self, row: int) -> None:
        key = (self.table.item(row, COL_SEL).data(Qt.ItemDataRole.UserRole) or "")
        idx = self._row_index.get(key)
        if idx is None or idx >= len(self._items):
            return
        it = self._items[idx]
        if self.on_add_single:
            self.on_add_single(it, None)

    def _open_magnet(self, row: int) -> None:
        key = (self.table.item(row, COL_SEL).data(Qt.ItemDataRole.UserRole) or "")
        idx = self._row_index.get(key)
        if idx is None or idx >= len(self._items):
            return
        it = self._items[idx]
        if self.on_magnet_list:
            self.on_magnet_list(it)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        """双击：若该资源含 ≥2 个磁力则打开细分选择（分集/版本）。"""
        if item.column() in (COL_SEL, COL_OP):
            return
        row = item.row()
        key = (self.table.item(row, COL_SEL).data(Qt.ItemDataRole.UserRole) or "")
        idx = self._row_index.get(key)
        if idx is None or idx >= len(self._items):
            return
        it = self._items[idx]
        if len(it.magnets or []) >= 2:
            if self.on_magnet_list:
                self.on_magnet_list(it)


