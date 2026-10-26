"""站点解析服务：站点实例 → 模块解析 → 镜像容灾 → 增量 → 详情磁力抓取 → 落库。

纯线程安全（不依赖 Qt），供 GUI 后台线程或 CLI 复用。
每个站点一个解析模块（src/site/modules/），本服务只负责编排：
  入口解析（resolve_site）→ 列表解析（module.parse_list）→ 增量比对
  → 详情抓取（module.parse_detail）→ 落库。
"""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from .. import constants
from ..database import Database
from ..log import get_logger
from ..models import MirrorSite, ParseItem, SiteInstance
from . import mirrors as mirror_mod
from .fetcher import SiteFetcher
from .modules import get_module
from .modules.base import trim_search_items

log = get_logger("site.service")


def _throttle_hint(text: str) -> str:
    """识别站点返回的“信息提示/限流”页；空串表示响应正常。

    帝国 CMS 搜索接口对同一 IP 有最小间隔限制，超限时会返回一张很短的
    “信息提示”页（正文含“系统限制的搜索时间间隔为 N 秒”），此时解析
    结果必然为空，需要等待后重试而不是当作“无结果”。
    """
    raw = text or ""
    if not raw.lstrip().startswith("<"):
        return ""              # JSON 接口按正常空结果处理
    m = re.search(r"系统限制的搜索时间间隔为\s*(\d+)\s*秒", raw)
    if m:
        return f"站点限制搜索间隔 {m.group(1)} 秒，请稍后再试"
    if "<title>信息提示</title>" in raw and len(raw) < 6000:
        return "站点返回提示页（可能触发访问频率限制）"
    return ""


def _throttle_seconds(text: str) -> float:
    """从限流提示里解析出需要等待的秒数。"""
    m = re.search(r"系统限制的搜索时间间隔为\s*(\d+)\s*秒", text or "")
    if not m:
        return 0.0
    try:
        return float(m.group(1)) + 1.0       # 多等 1 秒留余量
    except (TypeError, ValueError):
        return 0.0


def _resource_key(url: str) -> str:
    """跨站点资源指纹（忽略 scheme / www / query / 大小写），用于搜索结果去重。"""
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlparse(raw)
    except Exception:
        return raw
    host = (parts.netloc or "").split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{(parts.path or '/').rstrip('/')}"


class SiteParseService:
    def __init__(self, db: Database, fetcher: SiteFetcher | None = None):
        self.db = db
        self.fetcher = fetcher or SiteFetcher()
        self._instance: Optional[SiteInstance] = None  # 本次解析使用的站点实例
        # 运行内详情缓存：detail_url -> (magnets, desc)，跨入口/版块去重抓取
        self._detail_cache: dict = {}
        # 搜索结果缓存：(keyword, sites) -> (时间戳, summary)
        self._search_cache: dict = {}
        self._last_search_at: float = 0.0        # 上次搜索请求时刻（全局节流）

    # ------------------------------------------------------------- 镜像容灾
    def ensure_mirrors(self) -> None:
        """首次运行时将默认镜像写入库。"""
        if self.db.list_mirrors():
            return
        first = True
        for url in constants.DEFAULT_MIRRORS:
            u = mirror_mod.normalize_url(url)
            if not u:
                continue
            self.db.upsert_mirror(MirrorSite(url=u, enabled=True,
                                             is_current=first))
            if first:
                self.db.set_current_mirror(u)
                first = False

    def _entry_targets(self, inst: SiteInstance) -> list:
        """入口目标列表 [(url, MirrorSite|None)]。

        - 实例自带入口（分类页/版块页站点）：逐项尝试，不走镜像池；
        - 入口为空（hao6v 家族）：共享镜像池，当前 → 其它启用镜像。
        """
        entries = inst.entries()
        if entries:
            return [(u, None) for u in entries]
        order = [m for m in self.db.list_mirrors() if m.enabled]
        order.sort(key=lambda m: (0 if m.is_current else 1, m.id))
        return [(m.url, m) for m in order]

    def resolve_site(self) -> tuple:
        """兼容入口：返回第一个可用入口的 (url, html)（多站点时取第一个可解析的）。"""
        for inst in self._pick_instances(None):
            site, html = self._resolve_site(inst)
            if site:
                return site, html
        return None, None

    def _pick_instances(self, sites) -> list:
        """按工作台勾选（站点 id 列表）取站点实例；空选择 = 全部启用站点。"""
        enabled = self.db.list_sites(enabled_only=True)
        if not enabled:
            return []
        ids = []
        for x in (sites or []):
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        if not ids:
            cur = self.db.current_site()
            if cur is not None and cur.enabled:
                enabled.sort(key=lambda s: (0 if s.id == cur.id else 1, s.id))
            return enabled
        by_id = {s.id: s for s in enabled}
        picked, seen = [], set()
        for i in ids:  # 保持用户勾选顺序
            if i in by_id and i not in seen:
                seen.add(i)
                picked.append(by_id[i])
        return picked

    def _resolve_site(self, inst: SiteInstance) -> tuple:
        """解析单个站点实例的入口 → (url, html)；失败 (None, None)。"""
        module = get_module(inst.module_id)
        if module is None:
            log.warning("站点 %s 绑定的模块 %s 不存在，已跳过",
                        inst.name, inst.module_id)
            return None, None
        for url, mirror in self._entry_targets(inst):
            try:
                html, final = self.fetcher.get(url, timeout=14, cache=True)
                if len(html) < 3000:
                    if mirror:
                        self.db.mark_mirror(url, False, "内容过短")
                    continue
                if mirror:
                    self.db.mark_mirror(url, True, "可用")
                    if not mirror.is_current:
                        self.db.set_current_mirror(url)
                self._instance = inst
                return url, html
            except Exception as e:
                if mirror:
                    self.db.mark_mirror(url, False, f"{type(e).__name__}")
                log.info("入口 %s 不可用: %s", url, e)
        return None, None

    # ------------------------------------------------------------- 解析入口
    def run(self,
            enabled_blocks: Optional[list] = None,
            fetch_detail: bool = True,
            include_unknown: bool = True,
            polite_delay: float = 0.3,
            log_cb: Optional[Callable[[str], None]] = None,
            progress_cb: Optional[Callable[[int, int], None]] = None,
            cancel: Optional[Callable[[], bool]] = None,
            sites: Optional[list] = None,
            concurrency: int = 1) -> dict:
        """执行一次完整解析（可多站点）。返回统计 summary。

        sites = 工作台勾选的站点 id 列表；为空/None = 全部启用站点。
        concurrency = 详情页并发抓取数（1=串行最礼貌）。
        summary["sites"] 为各站点分解结果；items 为合并后的缓存列表。
        """
        def emit(msg: str) -> None:
            if log_cb:
                try:
                    log_cb(msg)
                except Exception:
                    pass

        self._detail_cache = {}  # 每次解析清空：保证增量更新拿到新数据
        summary = {"ok": False, "site": "", "total": 0, "new": 0,
                   "updated": 0, "failed": 0, "error": "",
                   "new_urls": [], "updated_urls": [], "sites": []}
        enabled = set(enabled_blocks) if enabled_blocks else set(
            constants.DEFAULT_ENABLED_BLOCKS)

        emit("== 开始解析（后台任务）==")
        self.ensure_mirrors()
        self.db.ensure_default_site()
        instances = self._pick_instances(sites)
        if not instances:
            summary["error"] = ("没有可解析的站点：请在工作台勾选站点，"
                                "或在设置页启用/添加站点。")
            emit("[错误] " + summary["error"])
            return summary
        emit(f"[站点] 本次解析 {len(instances)} 个："
             + "、".join(i.name for i in instances))

        merged: list = []
        seen_urls: set = set()
        for inst in instances:
            if cancel and cancel():
                emit("[停止] 任务被用户取消")
                break
            res = self._run_one(inst, enabled, fetch_detail, include_unknown,
                                polite_delay, emit, cancel, concurrency)
            self._mark_health(inst.module_id, res)
            summary["sites"].append(res)
            summary["total"] += res["total"]
            summary["new"] += res["new"]
            summary["updated"] += res["updated"]
            summary["failed"] += res["failed"]
            summary["new_urls"] += res["new_urls"]
            summary["updated_urls"] += res["updated_urls"]
            for it in res["items"]:
                if it.detail_url and it.detail_url not in seen_urls:
                    seen_urls.add(it.detail_url)
                    merged.append(it)
            if res.get("error"):
                summary["error"] = ((summary["error"] + "；")
                                    if summary["error"] else "") + \
                    f"{inst.name}: {res['error']}"

        ok_sites = [r for r in summary["sites"] if r.get("ok")]
        summary["ok"] = bool(ok_sites)
        summary["site"] = "、".join(r["name"] for r in summary["sites"])
        summary["items"] = merged
        summary["all_items"] = merged
        emit(f"[完成] {len(ok_sites)}/{len(summary['sites'])} 个站点解析成功，"
             f"新增 {summary['new']} 条，更新 {summary['updated']} 条，"
             f"合并缓存 {len(merged)} 条")
        return summary

    # ------------------------------------------------------------ 搜索入口
    def search(self, keyword: str, sites: Optional[list] = None,
               max_pages: int = 1, polite_delay: float = 0.3,
               log_cb: Optional[Callable[[str], None]] = None,
               cancel: Optional[Callable[[], bool]] = None,
               concurrency: int = 2,
               history_limit: int = 20,
               limit: int = 0,
               auto_detail: int = 0,
               cache_ttl: int = 300,
               min_interval: float = 10.5) -> dict:
        """按关键词跨站点搜索（各站并发，站内分页串行）。

        返回与 run() 同构的 summary：ok / keyword / total / items /
        sites[] / errors[] / elapsed，便于 UI 复用同一套渲染逻辑。
        搜索结果不落库（避免污染增量比对），可直接发送/复制/订阅。
        limit：每站点结果上限（0 = 不限制）。
        auto_detail：搜索后自动抓取前 N 条详情页资源（0 = 不自动抓）。
        """
        def emit(msg: str) -> None:
            if log_cb:
                try:
                    log_cb(msg)
                except Exception:
                    pass

        kw = (keyword or "").strip()
        summary = {"ok": False, "keyword": kw, "total": 0, "items": [],
                   "sites": [], "errors": [], "elapsed": 0.0}
        if not kw:
            summary["errors"].append("请输入搜索关键词")
            emit("[搜索] 关键词为空")
            return summary

        t0 = time.time()
        self.ensure_mirrors()
        self.db.ensure_default_site()

        # 短期缓存：同关键词/同站点组合在 TTL 内直接复用，
        # 站点（尤其 EmpireCMS）对高频搜索有节流，重复搜索只会拿到空页。
        try:
            ttl = max(0, int(cache_ttl))
        except (TypeError, ValueError):
            ttl = 0
        cache_key = (kw, tuple(str(x) for x in (sites or [])))
        if ttl:
            hit = self._search_cache.get(cache_key)
            if hit and (time.time() - hit[0]) < ttl:
                cached = dict(hit[1])
                cached["cached"] = True
                emit(f"[搜索] “{kw}” 命中缓存"
                     f"（{int(time.time() - hit[0])}s 前的结果）")
                return cached

        instances = self._pick_instances(sites)
        if not instances:
            summary["errors"].append("没有可搜索的站点")
            emit("[搜索] 没有可搜索的站点")
            return summary

        targets, unsupported = [], []
        for inst in instances:
            module = get_module(inst.module_id)
            if module is None:
                unsupported.append(f"{inst.name}：模块 {inst.module_id} 不存在")
                continue
            if not getattr(module, "supports_search", False):
                unsupported.append(f"{inst.name}：该模块暂不支持搜索")
                continue
            targets.append((inst, module))
        if unsupported:
            summary["errors"] += unsupported
            for msg in unsupported:
                emit("[搜索] " + msg)
        if not targets:
            emit("[搜索] 没有支持搜索的站点")
            return summary

        emit(f"[搜索] “{kw}” → {len(targets)} 个站点："
             + "、".join(i.name for i, _m in targets))

        results: list = []
        lock = threading.Lock()
        workers = max(1, int(concurrency or 1))

        def _wait_gap(seconds: float) -> bool:
            """等待到满足最小间隔；返回是否被取消。"""
            end = time.time() + max(0.0, seconds)
            while time.time() < end:
                if cancel and cancel():
                    return True
                time.sleep(0.2)
            return False

        def _run_once(inst, module, root):
            """执行一次搜索，返回 (items, err, pages, throttled)。"""
            pages: list = []
            try:
                items = module.search(
                    kw, self.fetcher, max_pages=max_pages, base=root,
                    polite_delay=polite_delay, log_cb=log_cb, cancel=cancel,
                    page_html=pages)
                if limit and len(items) > limit:
                    items = trim_search_items(items, limit)
                hint = ""
                for p in pages:
                    hint = _throttle_hint(p)
                    if hint:
                        break
                if items or not hint:
                    return items, "", pages, False
                return items, hint, pages, True
            except Exception as e:
                return [], f"{type(e).__name__}: {e}", pages, False

        def _work(order, inst, module) -> None:
            root = (inst.entries() or [self._current_mirror_url()])[0]
            err = ""
            items: list = []
            for attempt in range(3):
                if cancel and cancel():
                    emit("[停止] 任务被用户取消")
                    break
                with lock:                       # 全局最小间隔（IP 级节流）
                    gap = time.time() - self._last_search_at
                    wait = max(0.0, min_interval - gap)
                    self._last_search_at = time.time() + wait
                if wait > 0:
                    emit(f"[搜索] 等待 {wait:.1f}s（站点限制搜索间隔）")
                    if _wait_gap(wait):
                        break
                items, err, pages, throttled = _run_once(inst, module, root)
                if not throttled:
                    break
                wait = 0.0
                for p in pages:
                    wait = _throttle_seconds(p)
                    if wait:
                        break
                wait = wait or max(1.0, min_interval)
                emit(f"[搜索] {inst.name} 触发站点搜索间隔限制，"
                     f"{wait:.0f}s 后自动重试（{attempt + 1}/2）")
                if _wait_gap(wait):
                    break
            with lock:
                results.append({
                    "_order": order, "site": root, "name": inst.name,
                    "module": inst.module_id, "total": len(items),
                    "items": items, "ok": not err, "error": err})
            if err:
                emit(f"[搜索] {inst.name} 失败：{err}")
            else:
                emit(f"[搜索] {inst.name} 命中 {len(items)} 条")

        # 站点对同一 IP 的搜索有最小间隔限制（帝国 CMS 默认 10 秒），
        # 并发只会互相挤占配额，因此这里始终串行，并在每次请求前补齐间隔。
        packed = [(i, inst, mod) for i, (inst, mod) in enumerate(targets)]
        for t in packed:
            if cancel and cancel():
                break
            _work(*t)

        results.sort(key=lambda r: r.get("_order", 0))
        merged: list = []
        pairs: list = []                 # [(module_id, ParseItem)]
        seen: set = set()
        for res in results:
            mid = res.get("module") or ""
            for it in res["items"]:
                key = _resource_key(it.detail_url)
                if not key or key in seen:
                    continue
                seen.add(key)
                if not getattr(it, "site_key", ""):
                    it.site_key = mid
                merged.append(it)
                pairs.append((mid, it))
        # 结果缓存：同关键词短期内复用，避免反复触发站点节流
        if kw:
            self._search_cache[cache_key] = (time.time(), summary)
        summary["sites"] = results
        summary["items"] = merged
        summary["total"] = len(merged)
        summary["ok"] = any(r.get("ok") for r in results)
        summary["elapsed"] = round(time.time() - t0, 1)
        emit(f"[搜索] 完成：{len(merged)} 条（跨站去重后），"
             f"耗时 {summary['elapsed']}s")

        # 自动抓取前 N 条详情页资源（搜索结果本身通常不含磁力/网盘）。
        # 顺序必须与界面一致：按发布日期倒序取最上面的 N 条，
        # 否则会出现“上面的最新条目没解析、下面的却解析了”。
        if auto_detail and pairs:
            ordered = sorted(
                pairs, key=lambda p: (getattr(p[1], "date", "") or ""),
                reverse=True)[:max(0, int(auto_detail))]
            ok = fail = 0
            for mid, it in ordered:
                if cancel and cancel():
                    break
                self._fetch_search_detail(mid, it, polite_delay, emit)
                if it.magnets:
                    ok += 1
                else:
                    fail += 1
            emit(f"[搜索] 自动解析详情：成功 {ok} 条，无资源 {fail} 条")
        try:
            self.db.add_search_history(
                kw, site_ids=[i.id for i, _m in targets],
                result_count=summary["total"], limit=history_limit)
        except Exception:
            pass
        return summary

    def _fetch_search_detail(self, module_id: str, item,
                             polite_delay: float, emit) -> bool:
        """抓取单条搜索结果的详情页资源（磁力/网盘/附件）。"""
        module = get_module(module_id)
        if module is None or not getattr(item, "detail_url", ""):
            return False
        last = ""
        for attempt in range(2):          # 论坛站偶发超时，重试一次
            try:
                html, _ = self.fetcher.get(item.detail_url, timeout=25)
                module.parse_detail(html, item)
                item.detail_ok = True
                item.error = ""
                break
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
                item.error = last
                if attempt == 0:
                    time.sleep(1.5)
        else:
            emit(f"[搜索] 详情抓取失败 {item.title[:20]}：{last}")
            return False
        if polite_delay > 0:
            time.sleep(min(polite_delay, 1.5))
        return bool(item.magnets)

    def _current_mirror_url(self) -> str:
        """镜像池模式下的当前镜像地址（搜索入口基准）。"""
        try:
            for m in self.db.list_mirrors():
                if m.enabled and m.is_current:
                    return m.url
            for m in self.db.list_mirrors():
                if m.enabled:
                    return m.url
        except Exception:
            pass
        return (constants.DEFAULT_MIRRORS[0]
                if constants.DEFAULT_MIRRORS else "")

    # ------------------------------------------------------------ 健康度
    def _mark_health(self, module_id: str, res: dict) -> None:
        """记录站点模块本次解析健康度（连续异常 → 设置页提示可能改版）。"""
        try:
            from .modules.health import mark as health_mark

            total = int(res.get("detail_total") or 0)
            ratio = None
            if total:
                ratio = max(0.0, (total - int(res.get("failed") or 0)) / total)
            health_mark(self.db, module_id, int(res.get("total") or 0), ratio)
        except Exception:
            pass

    # ------------------------------------------------------------ 详情抓取
    def _fetch_details(self, fetch_list: list, module, site: str,
                       refresh_map: dict, polite_delay: float, emit, cancel,
                       concurrency: int = 1) -> int:
        """抓取详情页列表。

        - 运行内缓存：同一 detail_url 只抓一次（跨版块/入口的内容重复直接复用）；
        - 并发：concurrency>1 时用线程池并行抓取（请求间隔仍受 polite_delay 限制）。
        返回失败数量（含无磁力的条目）。
        """
        total = len(fetch_list)
        state = {"done": 0, "failed": 0}
        lock = threading.Lock()

        def _log_ok(it) -> None:
            emit(f"[{state['done']}/{total}] √ "
                 + ("· 更新 " if it.is_update else "")
                 + f"{it.title[:34]}"
                 + (f" 磁力×{len(it.magnets)}" if it.magnets else " (无磁力)"))
            if not it.magnets:
                state["failed"] += 1

        def _reuse(it) -> bool:
            cached = self._detail_cache.get(it.detail_url)
            if cached is None:
                return False
            mags, desc = cached
            it.magnets = list(mags)
            if desc and not it.desc:
                it.desc = desc
            it.detail_ok = True
            with lock:
                state["done"] += 1
            emit(f"[{state['done']}/{total}] ↷ {it.title[:34]}"
                 f"（跨入口复用，磁力×{len(it.magnets)}）")
            return True

        def _persist(it) -> None:
            if it.detail_url in refresh_map:
                try:
                    self.db.update_parse_item(site, it)
                except Exception:
                    pass

        def _work(it) -> None:
            html, _ = self.fetcher.get(it.detail_url, timeout=14)
            module.parse_detail(html, it)
            it.detail_ok = True

        pending = []
        for it in fetch_list:
            if cancel and cancel():
                emit("[停止] 任务被用户取消")
                break
            if _reuse(it):
                _persist(it)
                continue
            pending.append(it)

        if not pending:
            return state["failed"]

        def _run_serial() -> None:
            for n, it in enumerate(pending, 1):
                if cancel and cancel():
                    emit("[停止] 任务被用户取消")
                    break
                try:
                    _work(it)
                    self._detail_cache[it.detail_url] = (list(it.magnets),
                                                         it.desc)
                    with lock:
                        state["done"] += 1
                    _log_ok(it)
                except Exception as e:
                    it.error = f"{type(e).__name__}: {e}"
                    with lock:
                        state["done"] += 1
                        state["failed"] += 1
                    emit(f"[{state['done']}/{total}] × {it.title[:34]}"
                         f" -> {it.error}")
                _persist(it)
                if polite_delay > 0:
                    time.sleep(min(polite_delay, 1.5))

        def _run_concurrent(workers: int) -> None:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {}
                for it in pending:
                    if cancel and cancel():
                        emit("[停止] 任务被用户取消")
                        break
                    futs[pool.submit(_work, it)] = it
                    if polite_delay > 0:
                        time.sleep(min(polite_delay, 1.5))
                for fut in as_completed(futs):
                    it = futs[fut]
                    try:
                        fut.result()
                        self._detail_cache[it.detail_url] = (
                            list(it.magnets), it.desc)
                        with lock:
                            state["done"] += 1
                        _log_ok(it)
                    except Exception as e:
                        it.error = f"{type(e).__name__}: {e}"
                        with lock:
                            state["done"] += 1
                            state["failed"] += 1
                        emit(f"[{state['done']}/{total}] × {it.title[:34]}"
                             f" -> {it.error}")
                    _persist(it)

        workers = max(1, int(concurrency or 1))
        if workers > 1 and len(pending) > 1:
            _run_concurrent(workers)
        else:
            _run_serial()
        return state["failed"]

    # ------------------------------------------------------------ 单站点
    def _run_one(self, inst: SiteInstance, enabled: set, fetch_detail: bool,
                 include_unknown: bool, polite_delay: float, emit, cancel,
                 concurrency: int = 1) -> dict:
        """解析单个站点实例。

        - 入口模式（entry_urls 非空）：逐入口抓取解析，互不影响；
        - 镜像池模式（entry_urls 为空）：按 当前→其它 容灾取第一个可用入口。
        """
        res = {"site": "", "name": inst.name, "module": inst.module_id,
               "total": 0, "new": 0, "updated": 0, "failed": 0,
               "new_urls": [], "updated_urls": [], "items": [],
               "ok": False, "error": "", "entries": []}
        targets = self._entry_targets(inst)
        if not targets:
            res["error"] = "入口不可用"
            emit(f"[跳过] {inst.name}：没有可用入口")
            return res
        module = get_module(inst.module_id)
        if module is None:
            res["error"] = f"模块 {inst.module_id} 不存在"
            emit(f"[错误] {inst.name}：{res['error']}")
            return res

        if inst.entries():
            # 入口模式：逐入口解析（单入口失败不影响其它入口）
            for url, _mirror in targets:
                if cancel and cancel():
                    emit("[停止] 任务被用户取消")
                    break
                html = self._fetch_entry(url, None)
                if html is None:
                    emit(f"[跳过] {inst.name} 入口 {url} 抓取失败")
                    res["entries"].append({"site": url, "ok": False,
                                           "error": "抓取失败"})
                    continue
                sub = self._run_entry(inst, module, url, html, enabled,
                                      fetch_detail, include_unknown,
                                      polite_delay, emit, cancel, concurrency)
                res["entries"].append(sub)
                self._merge_entry(res, sub)
            if res["entries"]:
                res["ok"] = any(e.get("ok") for e in res["entries"])
                if not res["ok"]:
                    res["error"] = "全部入口解析失败"
                ok_sites = [e["site"] for e in res["entries"] if e.get("ok")]
                res["site"] = (ok_sites[0] if ok_sites
                               else res["entries"][0].get("site", ""))
        else:
            # 镜像池模式：容灾取第一个可用入口
            for url, mirror in targets:
                html = self._fetch_entry(url, mirror)
                if html is not None:
                    sub = self._run_entry(inst, module, url, html, enabled,
                                          fetch_detail, include_unknown,
                                          polite_delay, emit, cancel,
                                          concurrency)
                    res["entries"].append(sub)
                    self._merge_entry(res, sub)
                    res["ok"] = sub.get("ok", False)
                    res["site"] = url
                    break
            else:
                res["error"] = "入口不可用"
                emit(f"[跳过] {inst.name}：所有入口均不可用")
        return res

    @staticmethod
    def _merge_entry(res: dict, sub: dict) -> None:
        res["total"] += sub.get("total", 0)
        res["new"] += sub.get("new", 0)
        res["updated"] += sub.get("updated", 0)
        res["failed"] += sub.get("failed", 0)
        res["new_urls"] += sub.get("new_urls", [])
        res["updated_urls"] += sub.get("updated_urls", [])
        res["items"] += sub.get("items", [])

    def _fetch_entry(self, url: str, mirror) -> Optional[str]:
        """抓取入口页；长度不足或异常返回 None（镜像池入口会更新状态）。"""
        try:
            html, _final = self.fetcher.get(url, timeout=14, cache=True)
            if len(html) < 3000:
                if mirror:
                    self.db.mark_mirror(url, False, "内容过短")
                return None
            if mirror:
                self.db.mark_mirror(url, True, "可用")
                if not mirror.is_current:
                    self.db.set_current_mirror(url)
            return html
        except Exception as e:
            if mirror:
                self.db.mark_mirror(url, False, f"{type(e).__name__}")
            log.info("入口 %s 不可用: %s", url, e)
            return None

    def _run_entry(self, inst: SiteInstance, module, site: str, html: str,
                   enabled: set, fetch_detail: bool, include_unknown: bool,
                   polite_delay: float, emit, cancel,
                   concurrency: int = 1) -> dict:
        """解析单个入口：列表（可翻页）→ 增量 → 详情 → 落库 → 读缓存。"""
        res = {"site": site, "name": inst.name, "module": inst.module_id,
               "total": 0, "new": 0, "updated": 0, "failed": 0,
               "new_urls": [], "updated_urls": [], "items": [],
               "ok": False, "error": ""}
        self._instance = inst
        emit(f"[站点] {inst.name} → {site}（模块 {inst.module_id}）")

        items: list = module.parse_list_pages(
            html, site, entry_url=site, fetcher=self.fetcher,
            max_pages=getattr(module, "max_list_pages", 1),
            include_unknown=include_unknown)
        # 按设置过滤已勾选的区块（未识别区块归入“其他”并保留）
        if enabled:
            items = [it for it in items
                     if it.block in enabled or it.block == "其他"]
        res["total"] = len(items)
        emit(f"[列表] 命中区块更新 {len(items)} 条（勾选区块 {len(enabled)} 个）")
        if not items:
            res["ok"] = True
            cached = self.db.list_parse_items(site)
            res["items"] = cached
            emit(f"[完成] 未解析到更新记录（网站结构或区块变化？）"
                 + (f"，仍展示缓存 {len(cached)} 条" if cached else ""))
            return res

        # 增量比对：新增（URL 不在库）+ 更新（同一详情页标题/日期前进）
        # 连续剧/动画“更新到第 N 集/全集”时详情页 URL 不变，必须靠标题比对识别。
        known = self.db.existing_parse_map(site)
        new_items, updated_items = [], []
        for it in items:
            old = known.get(it.detail_url)
            if old is None:
                new_items.append(it)
                continue
            if ((old.title or "") != (it.title or "")
                    or (old.date or "") != (it.date or "")):
                it.is_update = True
                it.prev_title = old.title or ""
                updated_items.append(it)
        res["new"] = len(new_items)
        res["updated"] = len(updated_items)
        emit(f"[增量] 新增 {len(new_items)} 条，更新 {len(updated_items)} 条"
             + ("（首次解析为全量）" if not known else ""))

        def _keep(it) -> bool:
            return it.block in enabled or it.block == "其他"

        # 详情抓取目标 = 新增 + 更新 + 历史抓取失败/缺磁力的记录（补抓）
        new_detail = [it for it in new_items if _keep(it)]
        upd_detail = [it for it in updated_items if _keep(it)]
        refresh_items = self.db.incomplete_parse_items(site) if fetch_detail else []
        refresh_map = {it.detail_url: it for it in refresh_items}
        already = {it.detail_url for it in new_detail + upd_detail}
        fetch_list = list(new_detail) + list(upd_detail) + [
            it for it in refresh_items if it.detail_url not in already]

        res["detail_total"] = len(fetch_list) if (fetch_detail and fetch_list) else 0
        if fetch_detail and fetch_list:
            run_id = self.db.start_run(site)
            emit(f"[详情] 计划抓取 {len(fetch_list)} 个"
                 f"（新增 {len(new_detail)}，更新 {len(upd_detail)}，"
                 f"补抓 {len(refresh_items)}）")
            t0 = time.time()
            failed = self._fetch_details(
                fetch_list, module, site, refresh_map, polite_delay,
                emit, cancel, concurrency)
            emit(f"[详情] 抓取完成，耗时 {time.time() - t0:.1f}s"
                 f"（失败 {failed} 个，下次解析自动补抓）")

        # 落库：新增 + 更新（含本次失败项，detail_ok=0 便于下次补抓）
        saved, changed = self.db.upsert_parse_records(
            site, list(new_detail) + list(upd_detail))
        res["new_urls"] = [it.detail_url for it in new_detail
                           if it.detail_url]
        res["updated_urls"] = [it.detail_url for it in upd_detail
                               if it.detail_url]
        res["new"] = saved
        res["updated"] = changed
        res["failed"] = failed if (fetch_detail and fetch_list) else 0
        if fetch_detail and fetch_list:
            self.db.finish_run(run_id, len(items), saved + changed, failed == 0)

        # 展示/缓存：整站全部记录（第二次起与首次同样完整）
        cached = self.db.list_parse_items(site)
        res["ok"] = True
        res["items"] = cached
        emit(f"[完成] 新增入库 {saved} 条，更新 {changed} 条，"
             f"缓存共 {len(cached)} 条（可直接查看/下载）")
        return res
