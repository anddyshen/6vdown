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
from ..linkparse import format_download_name, make_download_tag
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
        self._latest_incremental: dict = {
            "run_time": "",
            "is_scheduled": False,
            "new_count": 0,
            "updated_count": 0,
            "urls": [],
        }

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
            # 定时自动解析（默认每 2 小时自动抓取一次全站增量）
            parse_hours = max(1, int(self.cfg.get("parse_interval_hours", 2) or 2))
            self._scheduler.add_job(
                self.run_scheduled_parse,
                "interval",
                hours=parse_hours,
                id="site_parse_job",
                replace_existing=True,
            )
            if self.cfg.get("sub_scheduler_enabled", True) or self.cfg.get("parse_enabled", True):
                self._scheduler.start()
                log.info(
                    "ServerService 周期调度器已启动（追剧巡检: %d 小时，定时解析: %d 小时）",
                    interval_hours,
                    parse_hours,
                )
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

            parse_hours = max(1, int(self.cfg.get("parse_interval_hours", 2) or 2))
            pjob = self._scheduler.get_job("site_parse_job")
            if pjob:
                pjob.reschedule("interval", hours=parse_hours)

            sub_enabled = self.cfg.get("sub_scheduler_enabled", True)
            parse_enabled = self.cfg.get("parse_enabled", True)
            any_enabled = sub_enabled or parse_enabled

            if any_enabled and not self._scheduler.running:
                self._scheduler.start()
            elif not any_enabled and self._scheduler.running:
                self._scheduler.pause()
            log.info("调度器重载成功，启用状态: %s，追剧周期: %d 小时，解析周期: %d 小时", any_enabled, interval_hours, parse_hours)
        except Exception as e:
            log.warning("重载调度器异常: %s", e)

    def run_scheduled_parse(self) -> None:
        """后台定时自动解析。"""
        log.info("后台触发定时自动解析任务……")
        self.start_parse(is_scheduled=True)

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

        def _date_sort_key(d: str):
            if not d:
                return (0, 0, 0)
            parts = str(d).strip().split("-")
            try:
                if len(parts) == 3:
                    return (int(parts[0]), int(parts[1]), int(parts[2]))
                if len(parts) == 2:
                    from datetime import datetime
                    return (datetime.now().year, int(parts[0]), int(parts[1]))
            except Exception:
                pass
            return (0, 0, 0)

        # 默认按更新日期倒序（最新排最前），同日期按最新入库记录倒序
        items.sort(key=lambda it: (_date_sort_key(it.date), getattr(it, "last_seen", 0) or 0), reverse=True)

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

    def start_parse(
        self, site_ids: Optional[list[int]] = None, is_scheduled: bool = False
    ) -> bool:
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
                new_urls = list(res.get("new_urls", []))
                updated_urls = list(res.get("updated_urls", []))
                all_incr = list(set(new_urls + updated_urls))
                self._latest_incremental = {
                    "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_scheduled": is_scheduled,
                    "new_count": res.get("new", 0),
                    "updated_count": res.get("updated", 0),
                    "urls": all_incr,
                }
                log_cb(f"解析完成！获取新资源: {res.get('new', 0)} 条，更新: {res.get('updated', 0)} 条。")
                self.db.add_operation_log(
                    category="parse",
                    action="定时自动解析" if is_scheduled else "手动站点解析",
                    detail=f"命中 {res.get('total', 0)} 条，新增入库 {res.get('new', 0)} 条，分集更新 {res.get('updated', 0)} 条",
                    status="success" if res.get("ok") else "fail",
                )
            except Exception as e:
                log_cb(f"[错误] 解析发生异常: {e}")
                self.db.add_operation_log(
                    category="parse",
                    action="定时自动解析" if is_scheduled else "手动站点解析",
                    detail=f"解析异常: {e}",
                    status="fail",
                )
            finally:
                with self._parse_lock:
                    self._is_parsing = False

        t = threading.Thread(target=_runner, daemon=True, name="WebParseWorker")
        t.start()
        return True

    def get_latest_incremental(self) -> dict:
        return dict(self._latest_incremental)

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
            "site_key": getattr(sub, "site_key", "") or "",
            "block": getattr(item, "block", "") or "",
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
                sub_block = getattr(item, "block", "") or ""
                send_res = self.send_download(
                    url=cand["magnet_url"],
                    sub_id=sub.id,
                    ep_label=cand.get("ep_label", ""),
                    quality=cand.get("quality", ""),
                    title=sub.title,
                    raw_label=cand.get("magnet_label", ""),
                    block=sub_block,
                    site_key=getattr(sub, "site_key", "") or "",
                )
                if send_res.get("ok"):
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
        if updates:
            titles = "、".join(f"《{u['title']}》" for u in updates[:3])
            self.db.add_operation_log(
                category="subscription",
                action="追剧周期巡检",
                detail=f"巡检完成，发现 {len(updates)} 部剧集有新更新（{titles} 等）",
                status="info",
            )
        return updates

    # ------------------------------------------------------------ 发送下载
    def send_download(
        self,
        url: str,
        host_id: Optional[int] = None,
        sub_id: Optional[int] = None,
        ep_label: str = "",
        quality: str = "",
        title: str = "",
        raw_label: str = "",
        block: str = "",
        site_key: str = "",
    ) -> dict:
        host = None
        if host_id:
            hosts = [h for h in self.db.list_hosts() if h.id == host_id]
            host = hosts[0] if hosts else None

        # 智能补全影视标题、区块分类与站点信息
        if sub_id:
            try:
                subs = [s for s in self.db.list_subscriptions() if s.id == sub_id]
                if subs:
                    sub_obj = subs[0]
                    if not title:
                        title = sub_obj.title
                    if not site_key:
                        site_key = getattr(sub_obj, "site_key", "")
                    if not block and sub_obj.detail_url:
                        with self.db._lock, self.db._conn() as c:
                            r_b = c.execute(
                                "SELECT block FROM parse_records WHERE detail_url=? LIMIT 1",
                                (sub_obj.detail_url,),
                            ).fetchone()
                            if r_b and r_b["block"]:
                                block = r_b["block"].strip()
            except Exception:
                pass

        if not title or not block or not site_key:
            try:
                with self.db._lock, self.db._conn() as c:
                    row = c.execute(
                        "SELECT title, block, site_key FROM parse_records WHERE magnets_json LIKE ? LIMIT 1",
                        (f"%{url[:40]}%",),
                    ).fetchone()
                    if row:
                        if not title and row["title"]:
                            title = row["title"].strip()
                        if not block and row["block"]:
                            block = row["block"].strip()
                        if not site_key and row["site_key"]:
                            site_key = row["site_key"].strip()
            except Exception:
                pass

        if not site_key:
            cur = self.db.current_site()
            site_key = getattr(cur, "module_id", "") or "6vdown"

        # 生成下载器标签：[解析的网站简称]+[区块名]，如 6vdown+美剧
        tag = make_download_tag(site_name=site_key, block=block)

        res = self.downloader.send(url, host=host, tag=tag)
        if res.ok and sub_id:
            self.db.record_subscription_push(sub_id, ep_label, url, quality)

        download_name = format_download_name(
            url=url,
            title=title,
            ep_label=ep_label,
            quality=quality,
            raw_label=raw_label,
        )

        active_host = host or self.db.active_host()
        h_name = active_host.name if active_host else "默认下载器"
        h_type = active_host.type if active_host else ""

        from ..models import TaskRecord
        self.db.add_task(
            TaskRecord(
                title=download_name,
                link=url,
                source="web",
                host_name=h_name,
                host_type=h_type,
                status="success" if res.ok else "fail",
                message=res.message,
            )
        )
        self.db.add_operation_log(
            category="download",
            action="推送到下载器",
            detail=f"{download_name} [标签: {tag}] -> 目标主机: {h_name} [{h_type}] | 结果: {res.message}",
            status="success" if res.ok else "fail",
        )
        return {"ok": res.ok, "message": res.message, "tag": tag}

    # ------------------------------------------------------------ 设置与连通性
    def get_config(self) -> dict:
        return self.cfg.all()

    def update_config(self, patch: dict) -> dict:
        self.cfg.update(patch)
        self.reload_scheduler()
        keys_str = ", ".join(patch.keys())
        self.db.add_operation_log(
            category="system",
            action="修改系统配置",
            detail=f"已更新配置项: {keys_str}",
            status="info",
        )
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
        self.db.add_operation_log(
            category="system",
            action="重置抓取缓存",
            detail="已清空全部历史站点解析缓存数据",
            status="info",
        )
        return True
