"""🔍 搜索标签页：按关键词跨站点搜索，结果可直接解析/发送/复制/订阅。

与工作台（定时增量解析）职责分离：
- 工作台：入口页 → 增量 → 落库；
- 搜索页：关键词 → 各站搜索接口 → 结果列表（**不入库**）→ 按需抓详情页取磁力。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..site.modules import get_module
from ..site.netdisk import looks_pan_title
from .workers import DetailFetchWorker

COL_SEL, COL_SITE, COL_TITLE, COL_DATE, COL_MAG, COL_OP = range(6)

# 资源类型展示顺序与中文名（1LOU 附件多为 .torrent 种子，可直接发送）
_KIND_LABELS = (("magnet", "磁力"), ("torrent", "种子"), ("pan", "网盘"))


def _is_pan(title: str) -> bool:
    """标题是否标识为网盘资源（与搜索排序/详情解析共用同一套判定）。"""
    return looks_pan_title(title)


def _resource_text(item) -> str:
    """资源列文案：磁力2·种子1·网盘3 / 无资源 / 失败 / 待解析。

    “待解析”= 详情页还没抓（搜索结果只带标题），不是解析失败；
    抓取后才可能显示磁力/种子/网盘，或确认“无资源”。
    """
    counts = {k: 0 for k, _l in _KIND_LABELS}
    for m in (item.magnets or []):
        counts[m.kind] = counts.get(m.kind, 0) + 1
    parts = ["%s%d" % (label, counts[kind])
             for kind, label in _KIND_LABELS if counts.get(kind)]
    if parts:
        return "·".join(parts)
    if getattr(item, "error", ""):
        return "失败"
    if getattr(item, "detail_ok", False):
        return "无资源"
    return "待解析"


def _resource_tooltip(item) -> str:
    """资源列悬浮提示：逐条列出名称与地址。"""
    lines = []
    for m in (item.magnets or []):
        label = {"magnet": "磁力", "torrent": "种子", "pan": "网盘"}.get(
            m.kind, m.kind)
        lines.append("[%s] %s" % (label, m.label))
        lines.append("    " + (m.url or ""))
    if getattr(item, "error", ""):
        lines.append("错误：" + item.error)
    if not (item.magnets or []) and not getattr(item, "detail_ok", False):
        lines.append("详情页尚未抓取：双击该行，或点“解析全部”"
                     "（设置页可调“搜索后自动解析前 N 条”）")
    return "\n".join(lines)


class SearchPage(QWidget):
    """关键词搜索页：关键词 + 站点多选 + 结果表 + 按需抓磁力。"""

    search_clicked = Signal(str)     # 关键词
    stop_clicked = Signal()
    sites_changed = Signal(list)

    def __init__(self, ctl=None, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.db = getattr(ctl, "db", None)
        self.cfg = getattr(ctl, "cfg", None)
        # 回调式挂钩（与工作台一致，由 Controller 赋值）
        self.on_add_single = None
        self.on_open_detail = None
        self.on_subscribe = None
        self.on_fetch_detail = None
        self._rows: list = []         # [(site_name, module_id, ParseItem)]
        self._fetch_worker = None
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入影片名 / 演员名，回车搜索……")
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self._start)
        # 搜索历史下拉：输入即补全，点“历史 ▾”可展开全部
        self.history_model = QStringListModel([], self)
        self.completer = QCompleter(self.history_model, self.edit)
        self.completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setMaxVisibleItems(12)
        self.edit.setCompleter(self.completer)
        bar.addWidget(self.edit, 1)

        self.btn_history = QPushButton("历史 ▾")
        self.btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history.clicked.connect(self._show_history)
        bar.addWidget(self.btn_history)

        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("primary")
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.clicked.connect(self._start)
        bar.addWidget(self.btn_search)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        bar.addWidget(self.btn_stop)

        self.btn_sites = QPushButton("站点 ▾")
        self.btn_sites.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sites.clicked.connect(self._open_site_menu)
        bar.addWidget(self.btn_sites)

        bar.addWidget(QLabel("上限"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(10, 500)
        self.spin_limit.setSingleStep(10)
        self.spin_limit.setFixedWidth(72)
        self.spin_limit.setValue(int((self.cfg.get("search_limit") or 80))
                                 if self.cfg else 80)
        bar.addWidget(self.spin_limit)

        self.chk_magnet = QCheckBox("仅显示已解析资源")
        bar.addWidget(self.chk_magnet)
        root.addLayout(bar)

        self.table = QTableWidget(0, COL_OP + 1)
        self.table.setHorizontalHeaderLabels(
            ["", "站点", "标题", "日期", "资源", "操作"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col, w in ((COL_SEL, 38), (COL_SITE, 104), (COL_DATE, 92),
                       (COL_MAG, 132), (COL_OP, 216)):
            self.table.setColumnWidth(col, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._double_click)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.chk_all = QCheckBox("全选")
        self.chk_all.toggled.connect(self._toggle_all)
        bottom.addWidget(self.chk_all)
        self.status_lab = QLabel("输入关键词开始搜索")
        self.status_lab.setStyleSheet("color: #64748b; font-weight: 500;")
        bottom.addWidget(self.status_lab, 1)

        self.btn_detail = QPushButton("解析所选详情")
        self.btn_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail.clicked.connect(self._fetch_selected)
        bottom.addWidget(self.btn_detail)

        self.btn_detail_all = QPushButton("解析全部")
        self.btn_detail_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail_all.setToolTip(
            "抓取所有“待解析”行的详情页资源（逐条串行，可随时点“停止”中断）")
        self.btn_detail_all.clicked.connect(self._fetch_all)
        bottom.addWidget(self.btn_detail_all)

        self.btn_send = QPushButton("发送所选")
        self.btn_send.setObjectName("primary")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._send_selected)
        bottom.addWidget(self.btn_send)

        self.btn_copy = QPushButton("复制磁力")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_selected)
        bottom.addWidget(self.btn_copy)

        self.btn_pan = QPushButton("复制网盘")
        self.btn_pan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pan.clicked.connect(self._copy_pan)
        bottom.addWidget(self.btn_pan)

        self.btn_clear = QPushButton("清空历史")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_history)
        bottom.addWidget(self.btn_clear)
        root.addLayout(bottom)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2000)
        self.console.setFixedHeight(96)
        self.console.setVisible(False)
        root.addWidget(self.console)

        self._load_history()
        # 启动即同步“站点”按钮文字，避免配置里只勾了部分站点时
        # 按钮仍显示“站点 ▾”，让人误以为在搜全部站点
        self._refresh_site_label()

    # ------------------------------------------------------------ 历史
    def _load_history(self) -> None:
        try:
            size = int(self.cfg.get("search_history_size") or 20)
        except Exception:
            size = 20
        if self.db is None:
            return
        try:
            words = self.db.list_search_history(limit=size)
        except Exception:
            return
        self.history_model.setStringList(words)
        base = "输入影片名 / 演员名，回车搜索……"
        if words:
            base = ("输入影片名 / 演员名，回车搜索"
                    "（最近：" + "、".join(words[:3]) + "）")
        self.edit.setPlaceholderText(base)

    def _show_history(self) -> None:
        """展开历史下拉（等价于在输入框里直接看到历史列表）。"""
        if not self.history_model.stringList():
            self.append_log("暂无搜索历史")
            return
        self.edit.setFocus()
        self.completer.setCompletionPrefix("")
        self.completer.complete()

    def _clear_history(self) -> None:
        if self.db is None:
            return
        try:
            self.db.clear_search_history()
        except Exception:
            return
        self.append_log("已清空搜索历史")
        self._load_history()

    # ------------------------------------------------------------ 交互
    def _start(self) -> None:
        kw = self.edit.text().strip()
        if not kw:
            self.status_lab.setText("请输入搜索关键词")
            return
        self.search_clicked.emit(kw)

    def _open_site_menu(self) -> None:
        sites = []
        if self.db is not None:
            try:
                sites = [s for s in self.db.list_sites(enabled_only=True)
                         if _supports(s.module_id)]
            except Exception:
                sites = []
        if not sites:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self, "提示",
                "没有支持搜索的站点：当前内置模块中电影港/电影港新版/"
                "1LOU/6v电影支持站内搜索。")
            return
        selected = self._selected_site_ids()
        default_site = None
        if self.db is not None:
            try:
                default_site = self.db.current_site()
            except Exception:
                default_site = None
        # 默认站点若本身不支持搜索，则该项置灰（避免选了却 0 结果）
        default_id = getattr(default_site, "id", 0) or 0
        if default_id not in {s.id for s in sites}:
            default_id = 0
        default_name = getattr(default_site, "name", "") or ""
        menu = QMenu(self)
        tip = menu.addAction("勾选后立即生效；不勾任何项 = 搜索全部站点")
        tip.setEnabled(False)
        menu.addSeparator()
        act_all = menu.addAction("全选（全部站点）")
        act_default = menu.addAction(
            f"仅默认站点（{default_name}）" if default_name else "仅默认站点")
        act_default.setEnabled(bool(default_id))
        menu.addSeparator()
        pairs = []
        for s in sites:
            act = menu.addAction(f"{s.name}（{s.module_id}）")
            act.setCheckable(True)
            act.setChecked((s.id in selected) if selected else True)
            pairs.append((s.id, act))
        chosen = menu.exec(self.btn_sites.mapToGlobal(
            QPoint(0, self.btn_sites.height())))
        if chosen is None:
            return
        if chosen is act_all:
            ids = [s.id for s in sites]
        elif chosen is act_default:
            ids = [default_id] if default_id else []
        else:
            ids = [sid for sid, act in pairs if act.isChecked()]
        if self.cfg is not None:
            self.cfg["search_sites"] = ids
            try:
                self.cfg.save()
            except Exception:
                pass
        self.sites_changed.emit(ids)
        self._refresh_site_label(ids)

    def _refresh_site_label(self, ids=None) -> None:
        if self.db is None:
            return
        try:
            sites = [s for s in self.db.list_sites(enabled_only=True)
                     if _supports(s.module_id)]
        except Exception:
            sites = []
        picked = set(ids if ids is not None else self._selected_site_ids())
        names = [s.name for s in sites if s.id in picked]
        # 空选择 = 参与全部支持搜索的站点，按钮文字要写清楚
        if not picked:
            text = f"站点：全部 {len(sites)} 个" if sites else "站点 ▾"
        elif not names:
            text = "站点：0 个"
        else:
            text = "站点：" + (names[0] if len(names) == 1
                              else f"{len(names)} 个")
        self.btn_sites.setText(text + (" ▾" if text != "站点 ▾" else ""))
        tip = ("参与搜索的站点：\n· " + "\n· ".join(
            names or [s.name for s in sites])
            if (names or sites) else "没有可搜索的站点")
        self.btn_sites.setToolTip(tip + "\n（点开可勾选/全选）")

    def _selected_site_ids(self) -> list:
        raw = self.cfg.get("search_sites") if self.cfg else None
        out = []
        for x in (raw or []):
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------ 渲染
    def load_results(self, summary: dict) -> None:
        """按 summary['sites'] 渲染结果行（每行附带来源站点与模块）。"""
        self._rows = []
        for res in summary.get("sites") or []:
            for it in res.get("items") or []:
                self._rows.append((res.get("name") or "",
                                   res.get("module") or "", it))
        if self.chk_magnet.isChecked():
            self._rows = [r for r in self._rows if r[2].magnets]
        # 时间近的排最上面（日期格式 YYYY-MM-DD；无日期的排最后，同级保持原顺序）
        self._rows.sort(key=lambda r: (r[2].date or ""), reverse=True)
        self._render()
        self._load_history()          # 刷新历史下拉（新关键词已入库）
        ok = summary.get("ok")
        if ok:
            with_res = sum(1 for r in self._rows if r[2].magnets)
            empty = [str(res.get("name") or res.get("module") or "?")
                     for res in (summary.get("sites") or [])
                     if not (res.get("items") or [])]
            text = (f"“{summary.get('keyword', '')}” 命中 "
                    f"{len(self._rows)} 条，已解析资源 {with_res} 条"
                    f"（耗时 {summary.get('elapsed', 0)}s）")
            if empty:
                text += "　无结果：" + "、".join(empty)
            self.status_lab.setText(text)
            self.status_lab.setToolTip(
                "各站点：\n" + "\n".join(
                    f"· {res.get('name') or res.get('module')}："
                    f"{len(res.get('items') or [])} 条"
                    + (f"（{res.get('error')}）" if res.get("error") else "")
                    for res in (summary.get("sites") or [])))
        else:
            errs = [e for e in (summary.get("errors") or []) if e]
            self.status_lab.setText(
                "搜索失败：" + (errs[0] if errs else "无结果"))

    def _render(self) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows))
        for row, (site_name, module_id, it) in enumerate(self._rows):
            c0 = QTableWidgetItem("")
            c0.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled)
            c0.setCheckState(Qt.CheckState.Unchecked)
            c0.setData(Qt.ItemDataRole.UserRole, it.detail_url or "")
            self.table.setItem(row, COL_SEL, c0)
            self.table.setItem(row, COL_SITE, QTableWidgetItem(site_name))
            title_item = QTableWidgetItem(
                ("🅟 " if _is_pan(it.title or "") else "") + (it.title or ""))
            if it.is_red:
                title_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, COL_TITLE, title_item)
            self.table.setItem(row, COL_DATE, QTableWidgetItem(it.date or ""))
            mag_item = QTableWidgetItem(_resource_text(it))
            mag_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mag_item.setToolTip(_resource_tooltip(it))
            self.table.setItem(row, COL_MAG, mag_item)
            self.table.setCellWidget(row, COL_OP, self._op_widget(row))
        self.chk_all.blockSignals(True)
        self.chk_all.setChecked(bool(self._rows)
                                and all(self._checked(r) for r in
                                        range(len(self._rows))))
        self.chk_all.blockSignals(False)

    def _op_widget(self, row: int):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(6)
        b1 = QPushButton("详情")
        b1.setCursor(Qt.CursorShape.PointingHandCursor)
        b1.clicked.connect(lambda _=False, r=row: self._open_detail(r))
        lay.addWidget(b1)
        b2 = QPushButton("发送")
        b2.setObjectName("primary")
        b2.setCursor(Qt.CursorShape.PointingHandCursor)
        b2.clicked.connect(lambda _=False, r=row: self._send_row(r))
        lay.addWidget(b2)
        b3 = QPushButton("订阅")
        b3.setCursor(Qt.CursorShape.PointingHandCursor)
        b3.clicked.connect(lambda _=False, r=row: self._subscribe_row(r))
        lay.addWidget(b3)
        return w

    # ------------------------------------------------------------ 选择
    def _checked(self, row: int) -> bool:
        it = self.table.item(row, COL_SEL)
        return bool(it and it.checkState() == Qt.CheckState.Checked)

    def _toggle_all(self, on: bool) -> None:
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_SEL)
            if it is not None:
                it.setCheckState(Qt.CheckState.Checked if on
                                 else Qt.CheckState.Unchecked)

    def selected_items(self) -> list:
        """[(site_name, module_id, ParseItem)] 当前勾选的行。"""
        out = []
        for r in range(self.table.rowCount()):
            if self._checked(r) and r < len(self._rows):
                out.append(self._rows[r])
        return out

    # ------------------------------------------------------------ 动作
    def _open_detail(self, row: int) -> None:
        if row >= len(self._rows):
            return
        _site, _mid, it = self._rows[row]
        if self.on_open_detail:
            self.on_open_detail(it)

    def _send_row(self, row: int) -> None:
        if row >= len(self._rows) or self.on_add_single is None:
            return
        _site, _mid, it = self._rows[row]
        self.on_add_single(it, None)

    def _subscribe_row(self, row: int) -> None:
        if row >= len(self._rows) or self.on_subscribe is None:
            return
        _site, _mid, it = self._rows[row]
        self.on_subscribe(it)

    def _fetch_rows(self, rows: list) -> None:
        """后台抓取指定行的详情页资源（搜索结果本身不含磁力/网盘）。"""
        if self.ctl is None or not hasattr(self.ctl, "fetcher"):
            return
        jobs = []
        for row in rows:
            if row >= len(self._rows):
                continue
            _site, mid, it = self._rows[row]
            if not it.magnets:
                jobs.append((row, mid, it))
        if not jobs:
            self.status_lab.setText("所选条目已有资源，无需重复解析")
            return
        self._fetch_worker = DetailFetchWorker(
            self.ctl.fetcher, jobs,
            polite_delay=float((self.cfg or {}).get(
                "search_polite_delay", 0.3) or 0.3), parent=self)
        self._fetch_worker.row_done.connect(self._on_detail_row)
        self._fetch_worker.finished_all.connect(self._on_detail_done)
        self.btn_detail.setEnabled(False)
        self.btn_detail_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_lab.setText(f"正在解析 {len(jobs)} 条详情……")
        self._fetch_worker.start()

    def _stop(self) -> None:
        """停止：优先中断详情抓取，其次中断搜索。"""
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self.status_lab.setText("正在停止详情解析……")
        self.stop_clicked.emit()

    def _fetch_selected(self) -> None:
        """解析所选行（勾选框）。"""
        picked = self.selected_items()
        if not picked:
            self.status_lab.setText("请先勾选要解析的条目")
            return
        rows = [r for r in range(len(self._rows))
                if any(p[2] is self._rows[r][2] for p in picked)]
        self._fetch_rows(rows)

    def _fetch_all(self) -> None:
        """解析所有待解析行（论坛站较慢，串行进行）。"""
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self.status_lab.setText("正在解析中，请稍候")
            return
        rows = [r for r in range(len(self._rows))
                if not self._rows[r][2].magnets]
        if not rows:
            self.status_lab.setText("所有条目都已解析")
            return
        self._fetch_rows(rows)

    def _double_click(self, row: int, _col: int) -> None:
        """双击「待解析」行 → 解析该行；已有资源则打开详情弹窗。"""
        if row >= len(self._rows):
            return
        _site, _mid, it = self._rows[row]
        if it.magnets:
            self._open_detail(row)
        else:
            self._fetch_rows([row])

    def _on_detail_row(self, row: int) -> None:
        """单条详情抓取完成 → 只刷新该行的资源列。"""
        if row >= len(self._rows):
            return
        _site, _mid, it = self._rows[row]
        mag = self.table.item(row, COL_MAG)
        if mag is not None:
            mag.setText(_resource_text(it))
            mag.setToolTip(_resource_tooltip(it))
        self.append_log(
            "%s：%s" % (it.title[:26],
                         ("磁力/资源 ×%d" % len(it.magnets)) if it.magnets
                         else ("无资源" + ("（%s）" % it.error if it.error
                                         else ""))))

    def _on_detail_done(self, ok: int, fail: int) -> None:
        self.btn_detail.setEnabled(True)
        self.btn_detail_all.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._fetch_worker = None
        self._render()
        self.status_lab.setText(
            f"详情解析完成：有资源 {ok} 条，无资源/失败 {fail} 条")

    @staticmethod
    def _all_magnets(items: list) -> list:
        urls = []
        for _s, _m, it in items:
            for m in (it.magnets or []):
                if m.url and m.url not in urls:
                    urls.append(m.url)
        return urls

    def _send_selected(self) -> None:
        picked = self.selected_items()
        if not picked:
            self.status_lab.setText("请先勾选要发送的条目")
            return
        if self.on_add_single is None:
            return
        for _site, _mid, it in picked:
            if not it.magnets and self.on_fetch_detail:
                self.on_fetch_detail(it, _mid)
            self.on_add_single(it, None)

    @staticmethod
    def _urls_of(items: list, kinds: tuple) -> list:
        urls = []
        for _s, _m, it in items:
            for m in (it.magnets or []):
                if m.kind in kinds and m.url and m.url not in urls:
                    urls.append(m.url)
        return urls

    def _copy_selected(self) -> None:
        """复制磁力 + 种子（可发送资源）。"""
        picked = self.selected_items()
        urls = self._urls_of(picked, ("magnet", "torrent"))
        if not urls:
            self.status_lab.setText("所选条目暂无磁力/种子，可先点“解析所选详情”")
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(urls))
        self.status_lab.setText(f"已复制 {len(urls)} 条资源到剪贴板")

    def _copy_pan(self) -> None:
        """复制网盘链接（不可发送，仅复制）。"""
        picked = self.selected_items()
        urls = self._urls_of(picked, ("pan",))
        if not urls:
            self.status_lab.setText("所选条目没有网盘链接")
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(urls))
        self.status_lab.setText(f"已复制 {len(urls)} 条网盘链接到剪贴板")

    # ------------------------------------------------------------ 状态
    def set_busy(self, busy: bool) -> None:
        self.btn_search.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        self.edit.setEnabled(not busy)

    def reload_history(self) -> None:
        """刷新搜索历史下拉（外部搜索完成后调用）。"""
        self._load_history()

    def append_log(self, line: str) -> None:
        from .workbench import fmt_time

        self.console.setVisible(True)
        self.console.appendPlainText(f"[{fmt_time()}] {line}")

    def current_limit(self) -> int:
        return int(self.spin_limit.value() or 80)


def _supports(module_id: str) -> bool:
    """模块是否支持站内搜索。"""
    try:
        return bool(getattr(get_module(module_id), "supports_search", False))
    except Exception:
        return False
