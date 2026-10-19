"""新模块向导：输入站点 URL → 本地/AI 推导规则 → 预览试解析 → 保存为解析模块。

流程：
  1) 抓取入口页（后台线程，礼貌单次请求）；
  2) 本地 AutoProfile 推导（默认）或调用 AI（失败自动降级本地）；
  3) 规则 JSON 可在编辑框里手动微调，点“试解析”预览前 N 条；
  4) 保存 → data/modules/<id>.json（同 ID 覆盖内置模块）+ 自动创建站点实例，
     之后即可在“解析工作台 → 🗺 解析站点”里勾选。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ..log import get_logger
from ..site.fetcher import SiteFetcher
from ..site.modules import analyzer
from ..site.modules.registry import reload_external_modules
from ..site.modules.rule_store import save_rule, validate_rule

log = get_logger("ui.analyze")

PREVIEW_LIMIT = 12


class _AnalyzeRunner(QThread):
    """后台分析：抓入口页 → 推导规则（本地/AI）。"""

    log_line = Signal(str)
    done = Signal(object)      # dict: {"rule":..., "html":..., "error":...}

    def __init__(self, url: str, cfg, use_ai: bool, parent=None):
        super().__init__(parent)
        self.url = url
        self.cfg = cfg
        self.use_ai = use_ai
        self.fetcher = SiteFetcher()

    def run(self) -> None:  # noqa: D102
        try:
            self.log_line.emit(f"[抓取] {self.url}")
            html, _final = self.fetcher.get(self.url, timeout=25)
            self.log_line.emit(f"[抓取] 完成，{len(html)} 字符")
            res = analyzer.derive_rule(self.url, html, cfg=self.cfg,
                                       use_ai=self.use_ai,
                                       log_cb=lambda s: self.log_line.emit(s))
            res["html"] = html
            self.done.emit(res)
        except Exception as e:
            log.exception("分析失败")
            self.done.emit({"rule": None, "html": "",
                            "error": f"{type(e).__name__}: {e}"})


class AnalyzeDialog(QDialog):
    """新模块向导对话框。"""

    def __init__(self, ctl, parent=None, url: str = ""):
        super().__init__(parent)
        self.ctl = ctl
        self.cfg = ctl.cfg
        self.db = ctl.db
        self._html = ""
        self._runner = None
        self.setWindowTitle("新解析模块向导")
        self.resize(820, 720)
        self._build()
        if url:
            self.edit_url.setText(url)
            self._sync_module_id(url)

    # ------------------------------------------------------------ 布局
    def _build(self) -> None:
        v = QVBoxLayout(self)

        box = QGroupBox("① 站点入口")
        form = QFormLayout(box)
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("https://example.com/dy/")
        self.edit_url.textChanged.connect(self._sync_module_id)
        form.addRow("入口地址", self.edit_url)

        row_id = QHBoxLayout()
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("英文小写唯一 ID，如 mysite")
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("显示名，如 我的站点")
        row_id.addWidget(QLabel("模块 ID"))
        row_id.addWidget(self.edit_id, 1)
        row_id.addWidget(QLabel("名称"))
        row_id.addWidget(self.edit_name, 1)
        form.addRow("", row_id)
        v.addWidget(box)

        box2 = QGroupBox("② 分析方式")
        h = QHBoxLayout(box2)
        self.rb_local = QRadioButton("本地自动推导（无需联网 AI，永远可用）")
        self.rb_ai = QRadioButton("AI 生成（需在设置页「AI 助手」中配置）")
        self.rb_local.setChecked(True)
        ai_ok = bool(self.cfg.get("ai_enabled", False))
        self.rb_ai.setEnabled(ai_ok)
        if not ai_ok:
            self.rb_ai.setToolTip("尚未启用 AI 助手：设置页 → 🤖 AI 助手")
        h.addWidget(self.rb_local)
        h.addWidget(self.rb_ai)
        h.addStretch(1)
        self.btn_run = QPushButton("开始分析")
        self.btn_run.setObjectName("primary")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.clicked.connect(self._run)
        h.addWidget(self.btn_run)
        v.addWidget(box2)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        v.addWidget(self.bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        self.log_view.setPlaceholderText("分析日志")
        v.addWidget(self.log_view)

        box3 = QGroupBox("③ 规则 JSON（可手动微调，改完点“试解析”）")
        v3 = QVBoxLayout(box3)
        self.rule_edit = QPlainTextEdit()
        self.rule_edit.setPlaceholderText("点击“开始分析”后自动生成；也可粘贴已有规则")
        self.rule_edit.setMinimumHeight(180)
        v3.addWidget(self.rule_edit)
        h3 = QHBoxLayout()
        self.btn_preview = QPushButton("试解析（抓取到的页面）")
        self.btn_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview.clicked.connect(self._preview)
        h3.addWidget(self.btn_preview)
        self.rule_msg = QLabel("")
        self.rule_msg.setStyleSheet("color:#64748b; font-size:12px;")
        self.rule_msg.setWordWrap(True)
        h3.addWidget(self.rule_msg, 1)
        v3.addLayout(h3)
        v.addWidget(box3, 1)

        box4 = QGroupBox("④ 解析预览")
        v4 = QVBoxLayout(box4)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["区块", "日期", "标题", "详情页"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(150)
        v4.addWidget(self.table)
        v.addWidget(box4, 1)

        foot = QHBoxLayout()
        self.btn_save = QPushButton("保存并创建站点")
        self.btn_save.setObjectName("primary")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self._save)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        foot.addStretch(1)
        foot.addWidget(self.btn_save)
        foot.addWidget(self.btn_close)
        v.addLayout(foot)

    # ------------------------------------------------------------ 辅助
    def _sync_module_id(self, text: str) -> None:
        if self.edit_id.text().strip():
            return
        host = urlparse(text or "").netloc
        slug = re.sub(r"[^a-z0-9]+", "_", (host or "").lower()).strip("_")
        if slug:
            self.edit_id.setText(slug)

    def _append(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)

    def _current_rule(self):
        text = self.rule_edit.toPlainText().strip()
        if not text:
            return None, "规则为空"
        try:
            data = json.loads(text)
        except Exception as e:
            return None, f"JSON 语法错误：{e}"
        errors = validate_rule(data)
        if errors:
            return None, "；".join(errors[:4])
        return data, ""

    # ------------------------------------------------------------ 分析
    def _run(self) -> None:
        url = (self.edit_url.text() or "").strip()
        if not url:
            QMessageBox.information(self, "提示", "请先填写入口地址")
            return
        if "://" not in url:
            url = "https://" + url
            self.edit_url.setText(url)
        self.btn_run.setEnabled(False)
        self.bar.show()
        self.log_view.clear()
        self._runner = _AnalyzeRunner(url, self.cfg,
                                      self.rb_ai.isChecked(), self)
        self._runner.log_line.connect(self._append)
        self._runner.done.connect(self._on_done)
        self._runner.start()

    def _on_done(self, res: dict) -> None:
        self.btn_run.setEnabled(True)
        self.bar.hide()
        self._html = res.get("html") or ""
        if res.get("error"):
            self._append("[错误] " + res["error"])
            QMessageBox.warning(self, "分析失败", res["error"])
            return
        rule = res.get("rule")
        if not rule:
            self._append("[错误] 未能推导出规则（页面可能需登录或为 JS 渲染）")
            QMessageBox.warning(
                self, "分析失败",
                "未能从该页面推导出解析规则。\n"
                "可能原因：需要登录、页面由 JS 渲染、或结构过于特殊。\n"
                "可尝试换一个列表页/分类页地址，或手动编写规则 JSON。")
            return
        for note in (res.get("notes") or []):
            self._append("[提示] " + note)
        if self.edit_id.text().strip():
            rule["module_id"] = self.edit_id.text().strip()
        if self.edit_name.text().strip():
            rule["name"] = self.edit_name.text().strip()
        self.rule_edit.setPlainText(
            json.dumps(rule, ensure_ascii=False, indent=2))
        self._preview()

    # ------------------------------------------------------------ 预览
    def _preview(self) -> None:
        data, err = self._current_rule()
        if err:
            self.rule_msg.setText("✗ " + err)
            self.rule_msg.setStyleSheet("color:#ef4444; font-size:12px;")
            return
        if not self._html:
            self.rule_msg.setText("（请先“开始分析”抓取页面后再试解析）")
            return
        module = analyzer.rule_to_module(data)
        if module is None:
            self.rule_msg.setText("✗ 规则无法通过引擎加载")
            return
        try:
            items = module.parse_list(self._html, data["entry_urls"][0],
                                      entry_url=data["entry_urls"][0])
        except Exception as e:
            self.rule_msg.setText(f"✗ 试解析失败：{type(e).__name__}: {e}")
            return
        self.table.setRowCount(0)
        self.table.setRowCount(min(len(items), PREVIEW_LIMIT))
        for r, it in enumerate(items[:PREVIEW_LIMIT]):
            self.table.setItem(r, 0, QTableWidgetItem(it.block or ""))
            self.table.setItem(r, 1, QTableWidgetItem(it.date or ""))
            self.table.setItem(r, 2, QTableWidgetItem(it.title or ""))
            self.table.setItem(r, 3, QTableWidgetItem(it.detail_url or ""))
        self.rule_msg.setStyleSheet("color:#16a34a; font-size:12px;")
        self.rule_msg.setText(
            f"✓ 试解析成功：共 {len(items)} 条"
            + (f"（预览前 {PREVIEW_LIMIT} 条）" if len(items) > PREVIEW_LIMIT
               else ""))

    # ------------------------------------------------------------ 保存
    def _save(self) -> None:
        data, err = self._current_rule()
        if err:
            QMessageBox.warning(self, "无法保存", err)
            return
        module_id = str(data.get("module_id") or "").strip()
        name = str(data.get("name") or "").strip() or module_id
        try:
            path = save_rule(data)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e)[:400])
            return
        reload_external_modules()
        # 站点实例：同名模块已存在则更新入口，否则新建
        try:
            exist = [s for s in self.db.list_sites() if s.module_id == module_id]
            if exist:
                site = exist[0]
                site.entry_urls = list(data.get("entry_urls") or [])
                site.name = name
                self.db.upsert_site(site)
            else:
                from ..models import SiteInstance

                self.db.upsert_site(SiteInstance(
                    module_id=module_id, name=name,
                    entry_urls=list(data.get("entry_urls") or []),
                    enabled=True, note="由新模块向导创建（规则文件可编辑）"))
        except Exception as e:
            log.warning("创建站点实例失败：%s", e)
        try:
            self.ctl.refresh_source_label()
        except Exception:
            pass
        QMessageBox.information(
            self, "已保存",
            f"规则已保存到：\n{path}\n\n"
            f"已创建/更新解析站点「{name}」，可在工作台“🗺 解析站点”中勾选使用。")
        self.accept()
