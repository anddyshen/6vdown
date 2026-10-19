"""应用控制器：托盘、剪贴板监听、任务发送、解析编排。"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QThreadPool
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon,
)

from . import autostart as boot
from .config import Config
from .database import Database
from .downloader import DownloaderManager
from .downloader.manager import TYPE_LABELS
from .emby_client import EmbyClient
from .linkparse import magnet_hash, parse_text
from .log import get_logger
from .models import ParseItem, Subscription, TaskRecord
from .scheduler_iface import AutoParseController
from .site import mirrors as mirror_mod
from .site.modules import get_module
from .site.fetcher import SiteFetcher
from .site.service import SiteParseService
from .subscription_engine import filter_subscription_updates
from .ui import theme as theme_mod
from .ui.drop_window import DropWindow
from .ui.history_page import HistoryPage
from .ui.icons import app_icon
from .ui.main_window import MainWindow
from .ui.notify import NotifyManager
from .ui.search_page import SearchPage
from .ui.settings_page import SettingsPage
from .ui.subscription_confirm_dialog import SubscriptionConfirmDialog
from .ui.subscription_page import SubscriptionPage
from .ui.workers import (MirrorProbeWorker, ParseWorker, SearchWorker,
                         SendRunnable)
from .ui.workbench import MagnetDialog

log = get_logger("controller")


def title_for(pl) -> str:
    if pl.kind == "magnet":
        return "磁力任务"
    if pl.sub == "torrent":
        return "种子文件"
    if pl.sub == "pt":
        return "PT 任务"
    return "网页链接"


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.quitting = False
        self._disabled = False
        self.db = Database()
        self.cfg = Config()
        self.manager = DownloaderManager(self.db)
        self.fetcher = SiteFetcher()
        self.service = SiteParseService(self.db, self.fetcher)
        self.notify = NotifyManager()
        self._pool = QThreadPool.globalInstance()

        self.sub_page = SubscriptionPage(self)
        self.history_page = HistoryPage(self.db)
        self.settings_page = SettingsPage(self)
        self.search_page = SearchPage(self)
        self.window = MainWindow(self)
        self.drop = DropWindow(self.cfg)

        self._parse = None
        self._probe = None
        self._last_clip = ""
        self._recent_sent = {}
        self.scheduler = AutoParseController(
            callback=self.run_subscription_check,
            interval_minutes=int(self.cfg.get("sub_interval_hours", 4)) * 60,
        )

        self._wire()
        self.apply_settings()
        self._apply_startup_state()

    # ------------------------------------------------------------ 装配
    def _wire(self) -> None:
        wb = self.window.workbench
        wb.parse_clicked.connect(self.ask_start_parse)
        wb.stop_clicked.connect(self.stop_parse)
        try:
            wb.sites_changed.connect(lambda _ids: self.refresh_source_label())
        except Exception:
            pass
        wb.on_magnet_list = self.open_magnet_dialog
        wb.on_add_single = self.add_item_to_downloader
        wb.on_subscribe = self.subscribe_item
        self.sub_page.check_all_clicked.connect(self.run_subscription_check)
        self.history_page.on_re_send = self.re_send_task
        sp = self.search_page
        sp.search_clicked.connect(self.start_search)
        sp.stop_clicked.connect(self.stop_search)
        sp.on_add_single = self.add_item_to_downloader
        sp.on_open_detail = self.open_magnet_dialog
        sp.on_subscribe = self.subscribe_item
        sp.on_fetch_detail = self.fetch_item_detail
        self.drop.dropped.connect(self.on_dropped)
        self._setup_tray()
        try:
            QGuiApplication.clipboard().dataChanged.connect(self.on_clipboard_changed)
        except Exception as e:
            log.warning("剪贴板监听不可用: %s", e)

    # ------------------------------------------------------------ 托盘
    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.window.windowIcon(), self)
        self.menu = QMenu()
        a1 = QAction("显示主窗口", self.menu)
        a1.triggered.connect(self.window.switch_workbench)
        self.menu.addAction(a1)
        a2 = QAction("显示 / 隐藏拖拽小窗", self.menu)
        a2.triggered.connect(self.drop.toggle_visible)
        self.menu.addAction(a2)
        a3 = QAction("开始解析站点更新", self.menu)
        a3.triggered.connect(self.ask_start_parse)
        self.menu.addAction(a3)
        self.menu.addSeparator()
        self.act_enable = QAction("剪贴板监听", self.menu)
        self.act_enable.setCheckable(True)
        self.act_enable.setChecked(True)
        self.act_enable.toggled.connect(
            lambda checked: self.set_disabled(not checked))
        self.menu.addAction(self.act_enable)
        self.act_notify = QAction("弹窗提示", self.menu)
        self.act_notify.setCheckable(True)
        self.act_notify.setChecked(bool(self.cfg["notify_enabled"]))
        self.act_notify.toggled.connect(self._set_notify_enabled)
        self.menu.addAction(self.act_notify)
        self.host_menu = self.menu.addMenu("下载服务器")
        self.host_menu.aboutToShow.connect(self._refresh_host_menu)
        self.menu.addSeparator()
        aq = QAction("退出 6vdown", self.menu)
        aq.triggered.connect(self.quit)
        self.menu.addAction(aq)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setToolTip("6vdown · 电影站下载解析器")
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.window.switch_workbench()

    def _host_display_name(self, h) -> str:
        return (h.name or "") if (h.name or "").strip() else \
            f"{h.address}:{h.port}" if h.port else (h.address or str(h.id))

    def _refresh_host_menu(self) -> None:
        self.host_menu.clear()
        hosts = self.db.list_hosts()
        if not hosts:
            na = QAction("（未配置下载服务器）", self.host_menu)
            na.setEnabled(False)
            self.host_menu.addAction(na)
            return
        for h in hosts:
            act = QAction(self._host_display_name(h), self.host_menu)
            act.setCheckable(True)
            act.setChecked(bool(h.is_active))
            act.setEnabled(not bool(h.is_active))
            act.triggered.connect(
                lambda _=False, hid=h.id: self._activate_host_from_tray(hid))
            self.host_menu.addAction(act)

    def _activate_host_from_tray(self, hid) -> None:
        self.db.set_active_host(hid)
        h = next((x for x in self.db.list_hosts() if x.id == hid), None)
        try:
            self.settings_page.reload_hosts()
        except Exception:
            pass
        self.notify_tip("下载服务器已切换",
                        f"当前发送目标：{self._host_display_name(h) if h else hid}")

    def set_disabled(self, flag: bool) -> None:
        flag = bool(flag)
        if flag == self._disabled:
            return
        self._disabled = flag
        self.cfg["clipboard_monitor"] = not flag
        if self.act_enable.isChecked() == flag:
            self.act_enable.blockSignals(True)
            self.act_enable.setChecked(not flag)
            self.act_enable.blockSignals(False)
        # 仅托盘图标在禁用时灰显；窗口/任务栏图标始终保持正常蓝色
        self.tray.setIcon(app_icon(gray=flag))
        self.tray.setToolTip("6vdown · 已禁用（图标灰色）" if flag
                             else "6vdown · 电影站下载解析器")

    # ------------------------------------------------------------ 剪贴板
    def on_clipboard_changed(self) -> None:
        if self._disabled or not self.cfg["clipboard_monitor"]:
            return
        try:
            text = QGuiApplication.clipboard().text()
        except Exception:
            return
        if not text or text == self._last_clip:
            return
        self._last_clip = text
        for pl in parse_text(text)[:20]:
            self.process_link(pl, "clipboard")

    def on_dropped(self, text: str) -> None:
        links = parse_text(text)
        if not links:
            self.notify_tip("拖入内容未识别到链接", "仅支持磁力 / http(s) 链接文本。")
            return
        for pl in links[:30]:
            self.process_link(pl, "drop")

    # ------------------------------------------------------------ 分发
    def process_link(self, pl, source: str) -> None:
        if pl.kind == "magnet":
            if self.cfg["auto_send_magnet"]:
                self.send(pl.url, title_for(pl), source)
            else:
                self._ask_send(pl, source)
        elif pl.kind == "http":
            if pl.sub in ("torrent", "pt") or self.cfg["http_mode"] == "send":
                self.send(pl.url, title_for(pl), source)
            elif self.cfg["http_mode"] == "ask":
                self._ask_send(pl, source)
        elif pl.kind in ("ed2k", "thunder"):
            self.notify_tip("暂不支持的链接类型",
                            f"{pl.kind.upper()} 链接无法发送到 BT 下载器。")

    def _ask_send(self, pl, source: str) -> None:
        if self._disabled or not self.cfg["notify_enabled"]:
            return
        desc = (pl.note or pl.kind) + "\n" + (pl.url[:140])
        self.notify.show(
            "检测到链接，是否发送到下载器？", desc, seconds=15,
            buttons=[("发送", lambda: self.send(pl.url, title_for(pl), source))],
        )

    # ------------------------------------------------------------ 发送
    def send(self, url: str, title: str, source: str) -> None:
        if not url:
            return
        auto = source in ("clipboard", "drop")
        if auto:
            key = magnet_hash(url)
            now = time.time()
            if key in self._recent_sent and now - self._recent_sent[key] < 120:
                return
            self._recent_sent[key] = now
            if len(self._recent_sent) > 200:
                self._recent_sent.clear()
        host = self.db.active_host()
        if not host:
            self.notify_tip("未配置下载主机",
                            "请到“设置 → 下载主机”添加并激活一台下载器。")
            return
        runnable = SendRunnable(self.manager, url, title, host=host, source=source)
        runnable.signals.done.connect(
            lambda ok, msg, t, u: self._on_send_done(ok, msg, t, u, source, host))
        self._pool.start(runnable)

    def _on_send_done(self, ok, msg, title, link, source, host) -> None:
        rec = TaskRecord(title=title or link[:80], link=link, source=source,
                         host_name=self._host_label(host), host_type=host.type,
                         status="ok" if ok else "fail", message=msg)
        self.db.add_task(rec)
        try:
            self.history_page.refresh()
        except Exception:
            pass
        if ok:
            self.window.set_status(f"已添加：{title or link[:60]}")
            self.notify_ok("任务已发送",
                           f"{title or '下载任务'} → {self._host_label(host)}")
        else:
            self.window.set_status(f"发送失败：{msg}")
            self.notify_err("发送失败", f"{title or link[:60]}\n{msg}")

    def _host_label(self, h) -> str:
        return (TYPE_LABELS.get(h.type, h.type)
                + ("/" + h.name if h.name else "")) or "下载器"

    def re_send_task(self, rec) -> None:
        if rec.link:
            self.send(rec.link, rec.title or "", "history")

    def add_item_to_downloader(self, item, magnet_url=None) -> None:
        if magnet_url:
            self.send(magnet_url, item.title or "", "site")
            return
        if not item.magnets:
            self.notify_tip("无磁力可添加", f"{item.title} 暂未解析到磁力链接。")
            return
        sendable = [m for m in item.magnets
                    if getattr(m, "kind", "magnet") in ("magnet", "torrent")]
        if not sendable:
            self.notify_tip("无可发送资源",
                            f"{item.title} 仅含网盘/附件链接（可在详情中复制）。")
            return
        for m in sendable:
            self.send(m.url, item.title or "", "site")

    def open_magnet_dialog(self, item) -> None:
        dlg = MagnetDialog(
            item,
            on_send=lambda it, u: self.send(u, it.title or "", "site"),
            on_copy=lambda u: self.copy_link(u),
            on_subscribe=self.subscribe_item,
            parent=self.window,
        )
        dlg.exec()

    def copy_link(self, url: str) -> None:
        try:
            QGuiApplication.clipboard().setText(url)
            self.notify_tip("已复制", url[:120])
        except Exception:
            pass

    # ------------------------------------------------------------ 解析
    def ask_start_parse(self) -> None:
        if self._parse and self._parse.isRunning():
            return
        mode = str(self.cfg.get("parse_default", "ask"))
        if mode == "bg":
            self.start_parse(show_console=False)
            return
        if mode == "view":
            self.start_parse(show_console=True)
            return
        box = QMessageBox(self.window)
        box.setWindowTitle("站点解析")
        box.setText("已就绪，是否开始解析站点更新？\n\n"
                    "选择“后台执行”：静默运行，完成后右下角提醒；\n"
                    "选择“查看过程”：展开控制台实时滚动解析日志。")
        b_bg = box.addButton("后台执行", QMessageBox.ButtonRole.AcceptRole)
        b_view = box.addButton("查看过程", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_bg:
            self.start_parse(show_console=False)
        elif clicked is b_view:
            self.start_parse(show_console=True)

    def refresh_source_label(self) -> None:
        """按工作台勾选的站点刷新“解析源”显示（支持多选）。"""
        try:
            wb = self.window.workbench
        except Exception:
            return
        try:
            sites = self.db.list_sites(enabled_only=True)
        except Exception:
            sites = []
        sel = []
        for x in (self.cfg.get("enabled_sites") or []):
            try:
                sel.append(int(x))
            except (TypeError, ValueError):
                continue
        picked = ([s for s in sites if s.id in sel] if sel else list(sites))
        if not picked:
            wb.mirror_label.setText("解析源：无可用站点（请到设置页启用）")
            return
        if len(picked) == 1:
            s = picked[0]
            wb.mirror_label.setText(
                f"解析源：{s.name}" + (f"（{s.entries()[0]}）" if s.entries() else ""))
            return
        names = "、".join(s.name for s in picked[:3])
        wb.mirror_label.setText(
            f"解析源：{len(picked)} 个站点（{names}"
            + (" 等" if len(picked) > 3 else "") + "）")

    def start_parse(self, show_console: bool = False) -> None:
        if self._parse and self._parse.isRunning():
            return
        self.service.ensure_mirrors()
        self.refresh_source_label()
        worker = ParseWorker(
            self.service,
            enabled_blocks=self.cfg["enabled_blocks"],
            include_unknown=True,
            fetch_detail=self.cfg["fetch_detail"],
            polite_delay=float(self.cfg["polite_delay"]),
            sites=list(self.cfg.get("enabled_sites") or []),
            concurrency=int(self.cfg.get("detail_concurrency", 2) or 1),
        )
        worker.log_line.connect(self.window.workbench.append_log)
        worker.done.connect(self._on_parse_done)
        self._parse = worker
        wb = self.window.workbench
        wb.set_running(True)
        if show_console:
            wb.btn_console.setChecked(True)
        wb.append_log("任务已提交……")
        worker.start()

    def stop_parse(self) -> None:
        if self._parse:
            self._parse.cancel()
            self.window.workbench.append_log("正在停止解析……")

    # ------------------------------------------------------------ 搜索
    def start_search(self, keyword: str) -> None:
        """按关键词跨站点搜索（后台线程，日志实时回传）。"""
        sp = self.search_page
        if self._parse and self._parse.isRunning():
            sp.status_lab.setText("解析任务正在运行，请稍候")
            return
        sites = list(self.cfg.get("search_sites") or [])
        worker = SearchWorker(
            self.service, keyword=keyword, sites=sites,
            max_pages=max(1, int(self.cfg.get("search_max_pages", 1) or 1)),
            polite_delay=float(self.cfg.get("search_polite_delay", 0.3)),
            concurrency=max(1, int(self.cfg.get("search_concurrency", 2) or 1)),
            history_limit=int(self.cfg.get("search_history_size", 20) or 20),
            limit=int(sp.current_limit() or 0),
            auto_detail=int(self.cfg.get("search_auto_detail", 8) or 0),
        )
        worker.log_line.connect(sp.append_log)
        worker.done.connect(self._on_search_done)
        self._parse = worker          # 与解析任务互斥，共用一个取消入口
        sp.set_busy(True)
        sp.append_log(f"开始搜索：{keyword}")
        worker.start()

    def stop_search(self) -> None:
        if self._parse:
            self._parse.cancel()
            self.search_page.append_log("正在停止搜索……")

    def fetch_item_detail(self, item, module_id: str = "") -> bool:
        """按需抓取单个条目的详情页磁力/简介（用于未入库的搜索结果）。

        返回是否成功；失败时把原因写进 item.error。
        """
        module = get_module(module_id) if module_id else None
        if module is None and self.db is not None:
            cur = self.db.current_site()
            module = get_module(getattr(cur, "module_id", "") or "")
        if module is None or not getattr(item, "detail_url", ""):
            return False
        try:
            html, _ = self.fetcher.get(item.detail_url, timeout=14)
            module.parse_detail(html, item)
            item.detail_ok = True
            return True
        except Exception as e:
            item.error = f"{type(e).__name__}: {e}"
            return False

    def _on_search_done(self, summary: dict) -> None:
        sp = self.search_page
        sp.set_busy(False)
        if self._parse:
            self._parse.deleteLater()
        self._parse = None
        sp.load_results(summary)
        if not summary.get("ok"):
            errs = [e for e in (summary.get("errors") or []) if e]
            self.notify_err("搜索失败", errs[0] if errs else "没有搜索到结果")
            return
        self.notify_tip("搜索完成",
                        f"“{summary.get('keyword', '')}” 命中 "
                        f"{summary.get('total', 0)} 条")

    def _on_parse_done(self, summary: dict) -> None:
        import traceback as _tb

        wb = self.window.workbench
        wb.set_running(False)
        if self._parse:
            self._parse.deleteLater()
        self._parse = None
        ok = bool(summary.get("ok"))
        site_rows = summary.get("sites") or []
        if site_rows:
            names = [r.get("name") or r.get("site") or "" for r in site_rows]
            names = [n for n in names if n]
            if names:
                self.window.workbench.mirror_label.setText(
                    f"解析源：{'、'.join(names[:3])}"
                    + (" 等" if len(names) > 3 else ""))
        items = summary.get("items") or summary.get("all_items") or []
        n = summary.get("new", 0)
        u = summary.get("updated", 0)
        new_urls = summary.get("new_urls") or []
        upd_urls = summary.get("updated_urls") or []
        if not ok:
            wb.set_status("解析失败：" + str(summary.get("error", "")))
            self.notify_err("站点解析失败", str(summary.get("error", "未知错误")))
            return
        if items:
            try:
                wb.load_items(items, summary,
                              mark_new=new_urls, mark_update=upd_urls)
            except Exception as e:
                wb.append_log("结果填充失败：" + repr(e))
                wb.append_log(_tb.format_exc())
                self.notify_err("结果填充失败", str(e))
                return
        if not n and not u and not items:
            wb.set_status("无新增更新 · 表格保留上次结果")
            self.notify_tip("站点解析完成", "没有新的更新，已保留上次结果。")
            return
        if n or u:
            parts = []
            if n:
                parts.append(f"新增 {n} 条")
            if u:
                parts.append(f"更新 {u} 条")
            msg = "解析完成，" + "、".join(parts) + "，已填入列表"
        else:
            msg = f"解析完成 · 无新增更新 · 已展示缓存 {len(items)} 条"
        self.notify.show(
            "站点解析完成", msg,
            seconds=10, accent="#22c55e",
            buttons=[("打开结果页", self.window.switch_workbench)],
        )

    # ------------------------------------------------------------ 镜像检测
    def detect_mirrors(self, discover: bool = False) -> None:
        if self._probe and self._probe.isRunning():
            return
        self.service.ensure_mirrors()
        if discover:
            self.settings_page.set_mirror_log("正在访问地址发布页 6v123.com ……")
            found = mirror_mod.discover_from_publish(fetcher=self.fetcher)
            existing = {m.url for m in self.db.list_mirrors()}
            added = 0
            for u in found:
                if u not in existing:
                    self.db.upsert_mirror(mirror_mod.normalize_url(u))
                    added += 1
            self.settings_page.set_mirror_log(
                f"发布页发现 {len(found)} 个地址，新增 {added} 个（将逐一检测）")
            self.settings_page.reload_mirrors()
        urls = [m.url for m in self.db.list_mirrors() if m.enabled]
        if not urls:
            return
        worker = MirrorProbeWorker(self.db, urls)
        worker.log.connect(self.settings_page.set_mirror_log)
        worker.done.connect(self._on_probe_done)
        self._probe = worker
        self.settings_page.set_mirror_busy(True)
        worker.start()

    def _on_probe_done(self, result: dict) -> None:
        self._probe = None
        ok_count = sum(1 for ok, _, _ in result.values() if ok)
        cur = self.db.current_mirror_url()
        if not result.get(cur, (False, "", 0))[0]:
            for url, (ok, _, _) in result.items():
                if ok:
                    self.db.set_current_mirror(url)
                    break
        self.settings_page.reload_mirrors()
        cur = self.db.current_mirror_url()
        self.settings_page.set_mirror_log(
            f"检测完成：可用 {ok_count}/{len(result)}。当前解析源：{cur}")
        self.settings_page.set_mirror_busy(False)
        self.notify_tip("镜像检测完成",
                        f"可用 {ok_count}/{len(result)}，已自动选择可用域名。")

    # ------------------------------------------------------------ 通知 / 设置
    def notify_ok(self, title: str, msg: str) -> None:
        if not self.cfg["notify_enabled"]:
            return
        self.notify.show(title, msg, seconds=int(self.cfg["notify_seconds"]),
                         accent="#22c55e")

    def notify_err(self, title: str, msg: str) -> None:
        if not self.cfg["notify_enabled"]:
            return
        self.notify.show(title, msg, seconds=10, accent="#ef4444")

    def notify_tip(self, title: str, msg: str) -> None:
        if not self.cfg["notify_enabled"]:
            return
        self.notify.show(title, msg, seconds=int(self.cfg["notify_seconds"]),
                         accent="#3b82f6")

    def _set_notify_enabled(self, checked: bool) -> None:
        self.cfg["notify_enabled"] = bool(checked)

    def apply_settings(self) -> None:
        theme_mod.apply_theme(self.app, self.cfg["theme"])
        if boot.is_frozen_app():
            boot.set_enabled(bool(self.cfg["start_on_boot"]))
        if getattr(self, "act_enable", None) is not None:
            self.act_enable.blockSignals(True)
            self.act_enable.setChecked(bool(self.cfg["clipboard_monitor"]))
            self.act_enable.blockSignals(False)
        if getattr(self, "act_notify", None) is not None:
            self.act_notify.blockSignals(True)
            self.act_notify.setChecked(bool(self.cfg["notify_enabled"]))
            self.act_notify.blockSignals(False)

    def subscribe_item(self, item) -> None:
        """从工作台或详情页订阅某部剧。"""
        sub = Subscription(
            title=item.title,
            detail_url=item.detail_url,
            status="active",
            last_ep=item.title,
        )
        self.db.add_subscription(sub)
        self.sub_page.reload()
        self.notify_ok("已加入追剧订阅", f"《{item.title}》已纳入自动更新检查清单。")

    def run_subscription_check(self) -> None:
        """后台拉取所有订阅剧集的更新，并在 Emby 差量对比及画质挑选后汇聚。"""
        active_subs = self.db.list_subscriptions(status="active")
        if not active_subs:
            return

        log.info("开始检查 %d 部订阅剧集...", len(active_subs))
        emby_cli = None
        if self.cfg.get("emby_enabled"):
            emby_cli = EmbyClient(self.cfg.get("emby_server_url", ""), self.cfg.get("emby_api_key", ""))

        priority = self.cfg.get("quality_priority", ["1080P", "4K", "720P", "OTHER"])
        collected_updates: list[dict] = []

        for sub in active_subs:
            # 抓取详情页（SiteFetcher 无 fetch_detail，统一走 fetch_item_detail）
            item = ParseItem(title=sub.title or "",
                             detail_url=sub.detail_url or "")
            if not self.fetch_item_detail(item):
                continue

            # 更新最新集标识
            if item.title and item.title != sub.last_ep:
                sub.last_ep = item.title
                self.db.update_subscription(sub)

            # 查询 Emby 本地已入库剧集
            emby_existing = None
            if emby_cli and emby_cli.is_configured():
                emby_existing = emby_cli.find_series_episodes(sub.title)

            # 筛选待下载更新
            updates = filter_subscription_updates(
                sub=sub,
                item=item,
                is_pushed_fn=self.db.is_magnet_pushed,
                priority_order=priority,
                emby_existing=emby_existing,
            )
            collected_updates.extend(updates)

        if not collected_updates:
            log.info("订阅检查完毕：无新增待下载集数。")
            self.sub_page.reload()
            return

        log.info("订阅发现 %d 条新剧集更新！", len(collected_updates))
        self.sub_page.reload()

        # 是否开启了“直接下载无需同意”
        if self.cfg.get("sub_auto_direct_download", False):
            self._push_subscription_tasks(collected_updates)
            self.notify_ok("订阅剧集已自动开始下载", f"已直接推送 {len(collected_updates)} 条最新剧集磁力。")
        else:
            # 弹出汇聚确认对话框
            dlg = SubscriptionConfirmDialog(
                collected_updates,
                on_confirm=self._push_subscription_tasks,
                parent=self.window,
            )
            dlg.exec()

    def _push_subscription_tasks(self, tasks: list[dict]) -> None:
        for t in tasks:
            self.send(t["magnet_url"], f"[{t['sub_title']}] {t['ep_label']} ({t['quality']})", "site")
            self.db.record_pushed_magnet(
                sub_id=t["sub_id"],
                episode_label=t["ep_label"],
                magnet_url=t["magnet_url"],
                quality=t["quality"],
            )

    def _apply_startup_state(self) -> None:
        # startup clipboard-monitor state: enable / disable / last-closed
        mode = str(self.cfg.get("clip_start", "last"))
        if mode == "enable":
            self.cfg["clipboard_monitor"] = True
            if self._disabled:
                self.set_disabled(False)
        elif mode == "disable":
            self.cfg["clipboard_monitor"] = False
            if not self._disabled:
                self.set_disabled(True)
        else:
            self.set_disabled(not bool(self.cfg.get("clipboard_monitor", True)))

        # 启动定时调度器
        if self.cfg.get("sub_scheduler_enabled", True):
            self.scheduler.set_interval(int(self.cfg.get("sub_interval_hours", 4)) * 60)
            self.scheduler.start()

        # 启动后延迟 15 秒检查一次订阅更新（避免开机网络未就绪）
        if self.cfg.get("sub_auto_on_startup", True):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(15000, self.run_subscription_check)

    def quit(self) -> None:
        self.quitting = True
        self.cfg.save()
        try:
            if self._parse and self._parse.isRunning():
                self._parse.cancel()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        self.window.close()
        self.app.quit()




