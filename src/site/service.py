"""站点解析服务：镜像容灾 → 首页解析 → 增量比对 → 详情磁力抓取 → 落库。

纯线程安全（不依赖 Qt），供 GUI 后台线程或 CLI 复用。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .. import constants
from ..database import Database
from ..log import get_logger
from ..models import ParseItem
from . import mirrors as mirror_mod
from .fetcher import SiteFetcher
from .parser import HomeParser, parse_detail_desc, parse_detail_magnets

log = get_logger("site.service")


class SiteParseService:
    def __init__(self, db: Database, fetcher: SiteFetcher | None = None):
        self.db = db
        self.fetcher = fetcher or SiteFetcher()

    # ------------------------------------------------------------- 镜像容灾
    def ensure_mirrors(self) -> None:
        """首次运行时将默认镜像写入库。"""
        if self.db.list_mirrors():
            return
        first = True
        for url in constants.DEFAULT_MIRRORS:
            self.db.upsert_mirror(mirror_mod.normalize_url(url))
            if first:
                self.db.set_current_mirror(mirror_mod.normalize_url(url))
                first = False

    def resolve_site(self) -> tuple:
        """按优先级（当前 → 其它启用镜像）返回第一个可用的 (url, html)。
        全部失败返回 (None, None)。过程中更新镜像状态。"""
        self.ensure_mirrors()
        order = []
        for m in self.db.list_mirrors():
            if not m.enabled:
                continue
            order.append(m)
        # 当前置顶
        order.sort(key=lambda m: (0 if m.is_current else 1, m.id))
        for m in order:
            try:
                html, final = self.fetcher.get(m.url, timeout=14, cache=True)
                if len(html) < 3000:
                    self.db.mark_mirror(m.url, False, "内容过短")
                    continue
                self.db.mark_mirror(m.url, True, "可用")
                if not m.is_current:
                    self.db.set_current_mirror(m.url)
                return m.url, html
            except Exception as e:
                self.db.mark_mirror(m.url, False, f"{type(e).__name__}")
                log.info("镜像 %s 不可用: %s", m.url, e)
        return None, None

    # ------------------------------------------------------------- 解析入口
    def run(self,
            enabled_blocks: Optional[list] = None,
            fetch_detail: bool = True,
            include_unknown: bool = True,
            polite_delay: float = 0.3,
            log_cb: Optional[Callable[[str], None]] = None,
            progress_cb: Optional[Callable[[int, int], None]] = None,
            cancel: Optional[Callable[[], bool]] = None) -> dict:
        """执行一次完整解析。返回统计 summary。"""
        def emit(msg: str) -> None:
            if log_cb:
                try:
                    log_cb(msg)
                except Exception:
                    pass

        summary = {"ok": False, "site": "", "total": 0, "new": 0,
                   "failed": 0, "error": "", "new_urls": []}
        enabled = set(enabled_blocks) if enabled_blocks else set(
            constants.DEFAULT_ENABLED_BLOCKS)

        emit("== 开始解析（后台任务）==")
        site, html = self.resolve_site()
        if not site:
            summary["error"] = "所有备用镜像均不可用，请稍后重试或在设置中检查域名。"
            emit("[错误] " + summary["error"])
            return summary
        summary["site"] = site
        emit(f"[域名] 使用 {site}")

        # 首页解析
        parser = HomeParser(html, site)
        items: list = parser.parse(include_unknown=include_unknown)
        # 按设置过滤已勾选的区块（未识别区块归入“其他”并保留）
        if enabled:
            items = [it for it in items
                     if it.block in enabled or it.block == "其他"]
        summary["total"] = len(items)
        emit(f"[首页] 命中区块更新 {len(items)} 条（勾选区块 {len(enabled)} 个）")
        if not items:
            summary["ok"] = True
            cached = self.db.list_parse_items(site)
            summary["items"] = cached
            summary["all_items"] = cached
            emit("[完成] 首页未解析到更新记录（网站结构或区块变化？）"
                 + (f"，仍展示缓存 {len(cached)} 条" if cached else ""))
            return summary

        # 增量比对
        known = self.db.existing_detail_urls(site)
        new_items = [it for it in items if it.detail_url not in known]
        summary["new"] = len(new_items)
        emit(f"[增量] 本次新增 {len(new_items)} 条"
             + ("（首次解析为全量）" if not known else ""))

        # 详情抓取目标 = 本次新增 + 历史抓取失败/缺磁力的记录（补抓）
        new_detail = [it for it in new_items
                      if it.block in enabled or it.block == "其他"]
        refresh_items = self.db.incomplete_parse_items(site) if fetch_detail else []
        refresh_map = {it.detail_url: it for it in refresh_items}
        already = {it.detail_url for it in new_detail}
        fetch_list = list(new_detail) + [it for it in refresh_items
                                         if it.detail_url not in already]

        if fetch_detail and fetch_list:
            run_id = self.db.start_run(site)
            emit(f"[详情] 计划抓取 {len(fetch_list)} 个"
                 f"（新增 {len(new_detail)}，补抓 {len(refresh_items)}）")
            failed = 0
            for n, it in enumerate(fetch_list, 1):
                if cancel and cancel():
                    emit("[停止] 任务被用户取消")
                    break
                try:
                    detail_html, _ = self.fetcher.get(it.detail_url, timeout=14)
                    it.magnets = parse_detail_magnets(detail_html)
                    it.desc = parse_detail_desc(detail_html)
                    it.detail_ok = True
                    emit(f"[{n}/{len(fetch_list)}] √ {it.title[:34]}" +
                         (f" 磁力×{len(it.magnets)}" if it.magnets else " (无磁力)"))
                    if not it.magnets:
                        failed += 1
                except Exception as e:
                    it.error = f"{type(e).__name__}: {e}"
                    failed += 1
                    emit(f"[{n}/{len(fetch_list)}] × {it.title[:34]} -> {it.error}")
                # 历史补抓项即时更新到缓存
                if it.detail_url in refresh_map:
                    try:
                        self.db.update_parse_item(site, it)
                    except Exception:
                        pass
                if polite_delay > 0:
                    time.sleep(min(polite_delay, 1.5))

        # 落库新记录（含本次失败项，detail_ok=0 便于下次补抓）
        saved = self.db.insert_parse_records(site, new_detail)
        summary["new_urls"] = [it.detail_url for it in new_detail
                          if it.detail_url]
        summary["new"] = saved
        if fetch_detail and fetch_list:
            self.db.finish_run(run_id, len(items), saved, failed == 0)
            summary["failed"] = failed

        # 展示/缓存：整站全部记录（第二次起与首次同样完整）
        cached = self.db.list_parse_items(site)
        summary["ok"] = True
        summary["items"] = cached
        summary["all_items"] = cached
        emit(f"[完成] 新增入库 {saved} 条，缓存共 {len(cached)} 条（可直接查看/下载）")
        return summary
