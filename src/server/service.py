"""服务端核心业务逻辑层（无 Qt 依赖，供 Web API 与 Docker 容器复用）。"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import Config
from ..constants import DEFAULT_ENABLED_BLOCKS, app_data_dir
from ..database import Database
from ..downloader.manager import DownloaderManager
from ..emby_client import EmbyClient
from ..log import get_logger
from ..models import DownloadHost, MagnetLink, ParseItem, Subscription
from ..site.fetcher import SiteFetcher
from ..site.modules import get_module
from ..site.service import SiteParseService
from ..subscription_engine import (
    SubscriptionUpdate,
    analyze_subscription_updates,
    pick_best_magnet,
)

log = get_logger("server")


class ServerService:
    """全功能无头核心服务，驱动 Web 交互与定时自动化追剧。"""

    def __init__(self):
        self.db = Database()
        self.cfg = Config()
        self.fetcher = SiteFetcher()
        self.parse_service = SiteParseService(self.db, self.fetcher)
        self.downloader = DownloaderManager(self.db)

        self._parse_lock = threading.Lock()
        self._is_parsing = False
        self._parse_logs: list[str] = []
        self._parse_summary: dict = {}

        self._scheduler: Optional[BackgroundScheduler] = None
        self._init_scheduler()

    # ------------------------------------------------------------ 调度器
    def _init_scheduler(self) -> None:
        try:
            self._scheduler = BackgroundScheduler(daemon=True)
            interval_hours = max(1, int(self.cfg.get("sub_interval_hours", 4) or 4))
            self._scheduler.add_job(
                self.check_all_subscriptions,
                "interval",
                hours=interval_hours,
                id="sub_check_job",
                replace_existing=True,
            )
            if self.cfg.get("sub_scheduler_enabled", True):
                self._scheduler.start()
                log.info("ServerService 周期检查调度器已启动（每 %d 小时检查一次）", interval_hours)
        except Exception as e:
            log.warning("启动定时调度器失败: %s", e)

    def reload_scheduler(self) -> None:
        """配置变更后重载定时调度器。"""
        if not self._scheduler:
            return
        try:
            interval_hours = max(1, int(self.cfg.get("sub_interval_hours", 4) or 4))
            job = self._scheduler.get_job("sub_check_job")
            if job:
                job.reschedule("interval", hours=interval_hours)
            enabled = self.cfg.get("sub_scheduler_enabled", True)
            if enabled and not self._scheduler.running:
                self._scheduler.start()
            elif not enabled and self._scheduler.running:
                self._scheduler.pause()
            log.info("调度器重载成功，启用状态: %s，周期: %d 小时", enabled, interval_hours)
        except Exception as e:
            log.warning("重载调度器异常: %s", e)

    # ------------------------------------------------------------ 解析工作台
    def get_sites(self) -> list[dict]:
        cur = self.db.current_site()
        cur_id = cur.id if cur else None
        sites = self.db.list_sites()
        return [
            {
                "id": s.id,
                "module_id": s.module_id,
                "name": s.name,
                "entry_urls": s.entry_urls,
                "enabled": s.enabled,
                "is_current": (s.id == cur_id),
                "note": s.note,
            }
            for s in sites
        ]

    def set_current_site(self, site_id: int) -> bool:
        self.db.set_current_site(site_id)
        return True

    def get_workbench_items(self, site_ids: Optional[list[int]] = None) -> list[dict]:
        """获取工作台当前缓存的解析条目列表。"""
        if not site_ids:
            cur = self.db.current_site()
            sites = [cur] if cur else []
        else:
            all_sites = {s.id: s for s in self.db.list_sites()}
            sites = [all_sites[sid] for sid in site_ids if sid in all_sites]

        all_urls: list[str] = []
        for s in sites:
            all_urls.extend(s.entries() if s.entries() else [self.db.current_mirror_url() or ""])

        items = self.db.list_parse_items(all_urls) if all_urls else []
        return [
            {
                "title": it.title,
                "date": it.date,
                "block": it.block,
                "detail_url": it.detail_url,
                "is_red": it.is_red,
                "is_classic": it.is_classic,
                "desc": it.desc,
                "detail_ok": it.detail_ok,
                "magnets_count": len(it.magnets),
                "magnets": [
                    {"label": m.label, "url": m.url, "kind": getattr(m, "kind", "magnet")}
                    for m in it.magnets
                ],
            }
            for it in items
        ]

    def start_parse(self, site_ids: Optional[list[int]] = None) -> bool:
        """异步启动解析任务。"""
        with self._parse_lock:
            if self._is_parsing:
                return False
            self._is_parsing = True
            self._parse_logs = []

        def _runner():
            def log_cb(msg: str):
                self._parse_logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
                if len(self._parse_logs) > 500:
                    self._parse_logs.pop(0)

            try:
                log_cb("开始执行站点解析任务……")
                self.parse_service.ensure_mirrors()
                res = self.parse_service.run(
                    enabled_blocks=self.cfg.get("enabled_blocks", DEFAULT_ENABLED_BLOCKS),
                    fetch_detail=self.cfg.get("fetch_detail", True),
                    polite_delay=float(self.cfg.get("polite_delay", 0.3)),
                    log_cb=log_cb,
                    sites=site_ids,
                    concurrency=int(self.cfg.get("detail_concurrency", 2) or 1),
                )
                self._parse_summary = res
                log_cb(f"解析完成！获取新资源: {res.get('new', 0)} 条，更新: {res.get('updated', 0)} 条。")
            except Exception as e:
                log_cb(f"[错误] 解析发生异常: {e}")
            finally:
                with self._parse_lock:
                    self._is_parsing = False

        t = threading.Thread(target=_runner, daemon=True, name="WebParseWorker")
        t.start()
        return True

    def get_parse_status(self) -> dict:
        with self._parse_lock:
            return {
                "is_parsing": self._is_parsing,
                "logs": list(self._parse_logs),
                "summary": self._parse_summary,
            }

    def fetch_item_detail(self, detail_url: str, module_id: str = "") -> Optional[dict]:
        """抓取单条详情页磁力。"""
        module = get_module(module_id) if module_id else None
        if module is None:
            cur = self.db.current_site()
            module = get_module(getattr(cur, "module_id", "") or "")
        if module is None or not detail_url:
            return None

        item = ParseItem(detail_url=detail_url)
        try:
            html, _ = self.fetcher.get(detail_url, timeout=14)
            module.parse_detail(html, item)
            item.detail_ok = True
            # 更新到数据库
            cur_site = self.db.current_site()
            site_url = cur_site.entries()[0] if cur_site and cur_site.entries() else ""
            if site_url:
                self.db.update_parse_item_detail(site_url, item)
            return {
                "detail_url": item.detail_url,
                "desc": item.desc,
                "magnets": [
                    {"label": m.label, "url": m.url, "kind": getattr(m, "kind", "magnet")}
                    for m in item.magnets
                ],
            }
        except Exception as e:
            log.warning("抓取详情页异常 (%s): %s", detail_url, e)
            return None

    # ------------------------------------------------------------ 跨站搜索
    def search(self, keyword: str, site_ids: Optional[list[int]] = None, max_pages: int = 1) -> dict:
        results: list = []
        logs: list[str] = []

        def log_cb(msg: str):
            logs.append(msg)

        try:
            res = self.parse_service.search(
                keyword=keyword,
                sites=site_ids,
                max_pages=max_pages,
                log_cb=log_cb,
            )
            items = res.get("items", [])
            for it in items:
                results.append({
                    "title": it.title,
                    "date": it.date,
                    "block": it.block,
                    "detail_url": it.detail_url,
                    "site_key": getattr(it, "site_key", ""),
                    "magnets_count": len(it.magnets),
                    "magnets": [
                        {"label": m.label, "url": m.url, "kind": getattr(m, "kind", "magnet")}
                        for m in it.magnets
                    ],
                })
            return {"ok": True, "items": results, "logs": logs}
        except Exception as e:
            return {"ok": False, "error": str(e), "logs": logs}

    # ------------------------------------------------------------ 订阅追剧
    def list_subscriptions(self, status: str = "active") -> list[dict]:
        subs = self.db.list_subscriptions(status=status)
        return [
            {
                "id": s.id,
                "title": s.title,
                "detail_url": s.detail_url,
                "status": s.status,
                "last_ep": s.last_ep,
                "emby_series_id": s.emby_series_id,
                "site_key": s.site_key,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in subs
        ]

    def add_subscription(self, title: str, detail_url: str, site_key: str = "") -> int:
        sub = Subscription(
            title=title.strip(),
            detail_url=detail_url.strip(),
            status="active",
            last_ep=title.strip(),
            site_key=site_key.strip(),
        )
        sub_id = self.db.add_subscription(sub)
        log.info("已新增追剧订阅: %s (ID: %d)", title, sub_id)
        return sub_id

    def delete_subscription(self, sub_id: int) -> bool:
        self.db.delete_subscription(sub_id)
        log.info("已删除追剧订阅 ID: %d", sub_id)
        return True

    def _get_emby_existing(self, emby_cli: Optional[EmbyClient], sub: Subscription) -> Optional[set[tuple[int, int]]]:
        if not emby_cli or not emby_cli.is_configured():
            return None
        series_id = getattr(sub, "emby_series_id", "") or ""
        if series_id:
            eps = emby_cli.get_series_episodes_by_id(series_id)
            if eps is not None:
                return eps
        s_item = emby_cli.find_series(sub.title)
        if s_item:
            matched_id = str(s_item.get("Id", "")).strip()
            if matched_id:
                sub.emby_series_id = matched_id
                self.db.update_subscription(sub)
                return emby_cli.get_series_episodes_by_id(matched_id)
        return None

    def _check_one_sub(
        self,
        sub: Subscription,
        emby_cli: Optional[EmbyClient],
        priority: list[str],
        auto_download: bool = False,
    ) -> Optional[dict]:
        item = ParseItem(title=sub.title or "", detail_url=sub.detail_url or "")
        module_id = getattr(sub, "site_key", "") or ""
        module = get_module(module_id) if module_id else None
        if module is None:
            cur = self.db.current_site()
            module = get_module(getattr(cur, "module_id", "") or "")
        if not module:
            return None

        try:
            html, _ = self.fetcher.get(sub.detail_url, timeout=14)
            module.parse_detail(html, item)
            item.detail_ok = True
        except Exception as e:
            log.warning("订阅检查抓取详情页失败 (%s): %s", sub.detail_url, e)
            return None

        if item.title and item.title != sub.last_ep:
            sub.last_ep = item.title
            self.db.update_subscription(sub)

        emby_existing = self._get_emby_existing(emby_cli, sub)

        up = analyze_subscription_updates(
            sub=sub,
            item=item,
            is_magnet_pushed_fn=self.db.is_magnet_pushed,
            is_ep_pushed_fn=self.db.is_episode_pushed,
            priority_order=priority,
            emby_existing=emby_existing,
        )

        if not up or not up.has_any_update:
            return None

        res_dict = {
            "sub_id": sub.id,
            "title": sub.title,
            "detail_url": sub.detail_url,
            "has_emby": up.has_emby,
            "latest_candidate": None,
            "missing_history": [],
        }

        if up.latest_candidate:
            cand = up.latest_candidate
            res_dict["latest_candidate"] = {
                "ep_label": cand["ep_label"],
                "quality": cand["quality"],
                "magnet_label": cand["magnet_label"],
                "magnet_url": cand["magnet_url"],
            }
            # 如果配置了“发现新集自动直接下载”
            if auto_download and cand.get("magnet_url"):
                send_res = self.downloader.send(cand["magnet_url"])
                if send_res.ok:
                    self.db.record_subscription_push(
                        sub.id, cand["ep_label"], cand["magnet_url"], cand["quality"]
                    )
                    log.info("【自动追剧】已成功自动推送最新一集: %s (%s)", sub.title, cand["ep_label"])

        if up.missing_history:
            res_dict["missing_history"] = [
                {
                    "ep_label": m["ep_label"],
                    "quality": m["quality"],
                    "magnet_label": m["magnet_label"],
                    "magnet_url": m["magnet_url"],
                }
                for m in up.missing_history
            ]

        return res_dict

    def check_single_subscription(self, sub_id: int) -> Optional[dict]:
        subs = [s for s in self.db.list_subscriptions() if s.id == sub_id]
        if not subs:
            return None
        sub = subs[0]
        emby_cli = None
        if self.cfg.get("emby_enabled"):
            emby_cli = EmbyClient(self.cfg.get("emby_server_url", ""), self.cfg.get("emby_api_key", ""))
        priority = self.cfg.get("quality_priority", ["1080P", "4K", "720P", "OTHER"])
        return self._check_one_sub(sub, emby_cli, priority, auto_download=False)

    def check_all_subscriptions(self) -> list[dict]:
        active_subs = self.db.list_subscriptions(status="active")
        if not active_subs:
            return []

        emby_cli = None
        if self.cfg.get("emby_enabled"):
            emby_cli = EmbyClient(self.cfg.get("emby_server_url", ""), self.cfg.get("emby_api_key", ""))
        priority = self.cfg.get("quality_priority", ["1080P", "4K", "720P", "OTHER"])
        auto_download = self.cfg.get("sub_auto_direct_download", False)

        updates: list[dict] = []
        for sub in active_subs:
            up = self._check_one_sub(sub, emby_cli, priority, auto_download=auto_download)
            if up:
                updates.append(up)
        return updates

    # ------------------------------------------------------------ 发送下载
    def send_download(self, url: str, host_id: Optional[int] = None, sub_id: Optional[int] = None, ep_label: str = "", quality: str = "") -> dict:
        host = None
        if host_id:
            hosts = [h for h in self.db.list_hosts() if h.id == host_id]
            host = hosts[0] if hosts else None

        res = self.downloader.send(url, host=host)
        if res.ok and sub_id:
            self.db.record_subscription_push(sub_id, ep_label, url, quality)
        return {"ok": res.ok, "message": res.message}

    # ------------------------------------------------------------ 设置与连通性
    def get_config(self) -> dict:
        return self.cfg.all()

    def update_config(self, patch: dict) -> dict:
        self.cfg.update(patch)
        self.reload_scheduler()
        return self.cfg.all()

    def test_emby(self, server_url: str, api_key: str) -> dict:
        client = EmbyClient(server_url, api_key)
        ok, msg = client.test_connection()
        return {"ok": ok, "message": msg}

    def list_hosts(self) -> list[dict]:
        hosts = self.db.list_hosts()
        return [
            {
                "id": h.id,
                "type": h.type,
                "name": h.name,
                "address": h.address,
                "port": h.port,
                "username": h.username,
                "is_active": h.is_active,
                "has_password": bool(h.password),
            }
            for h in hosts
        ]

    def save_host(self, host_data: dict) -> int:
        host_id = host_data.get("id")
        password = str(host_data.get("password") or "").strip()
        # 如果未传入新密码，但有 host_id，保留已有密码
        if not password and host_id:
            existing = [h for h in self.db.list_hosts() if h.id == int(host_id)]
            if existing:
                password = existing[0].password

        h = DownloadHost(
            id=int(host_id) if host_id else None,
            type=host_data.get("type", "qb"),
            name=host_data.get("name", ""),
            address=host_data.get("address", ""),
            port=int(host_data.get("port", 8080) or 8080),
            username=host_data.get("username", ""),
            password=password,
            is_active=bool(host_data.get("is_active", False)),
        )
        if h.id:
            self.db.update_host(h)
            if h.is_active:
                self.db.set_active_host(h.id)
            return h.id
        else:
            new_id = self.db.add_host(h)
            if h.is_active:
                self.db.set_active_host(new_id)
            return new_id

    def activate_host(self, host_id: int) -> bool:
        self.db.set_active_host(host_id)
        return True

    def delete_host(self, host_id: int) -> bool:
        self.db.delete_host(host_id)
        return True

    def test_host(self, host_data: dict) -> dict:
        host_id = host_data.get("id")
        password = str(host_data.get("password") or "").strip()
        # 如果未传入新密码，但传入了已有 host_id，使用数据库内保存的密码测试
        if not password and host_id:
            existing = [h for h in self.db.list_hosts() if h.id == int(host_id)]
            if existing:
                password = existing[0].password

        h = DownloadHost(
            id=int(host_id) if host_id else None,
            type=host_data.get("type", "qb"),
            name=host_data.get("name", ""),
            address=host_data.get("address", ""),
            port=int(host_data.get("port", 8080) or 8080),
            username=host_data.get("username", ""),
            password=password,
        )
        res = self.downloader.test_host(h)
        return {"ok": res.ok, "message": res.message}

    def reset_cache(self) -> bool:
        """清空抓取缓存数据。"""
        self.db.clear_parse_data()
        return True
