"""站点解析模块基类与元信息。

每个站点一个模块（内置 Python 模块，或未来的 JSON 规则模块），
统一提供四类能力：
  1) 入口策略：镜像池（hao6v 家族）或实例自带入口列表（分类页站点）；
  2) 列表页解析：HTML → list[ParseItem]；
  3) 详情页解析：填充 item.magnets / item.desc；
  4) 关键词搜索（可选）：search_spec + parse_search。

SiteParseService 只依赖本接口编排，不关心具体站点结构。
"""
from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

_DETAIL_URL_RE = re.compile(r"(?:\.html?$|\.html?[?#]|thread-|/\d{3,})", re.I)


def looks_detail_url(url: str) -> bool:
    """粗略判断链接是否指向内容详情页（列表页/搜索结果页通用）。"""
    low = (url or "").strip().lower()
    if not low or low.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    return bool(_DETAIL_URL_RE.search(low))


def root_url(url: str, fallback: str = "") -> str:
    """取站点根地址（scheme://host/），用于补全搜索结果里的相对链接。"""
    raw = (url or "").strip() or (fallback or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urllib.parse.urlparse(raw)
    if not parts.netloc:
        return ""
    return f"{parts.scheme or 'https'}://{parts.netloc}/"


@dataclass
class ModuleMeta:
    """模块元信息（设置页/注册表展示用）。"""

    module_id: str                 # 唯一 ID，如 hao6v / dygang / dyg7 / lou1
    name: str                      # 展示名
    desc: str = ""                 # 适用站点说明
    # 入口模式：
    #   mirror  = 使用共享镜像池（mirror_sites），当前→其它可用 自动降级；
    #   entries = 使用站点实例自带的入口地址列表（分类页/版块页站点）。
    entry_mode: str = "mirror"
    default_entry_urls: tuple = ()  # 新建站点实例时的默认入口
    builtin: bool = True           # 是否内置模块（False = 外部 JSON 规则）
    encoding: str = "auto"         # 页面编码：auto / gb18030 / utf-8（POST 搜索等场景）


@dataclass
class SearchSpec:
    """一次搜索请求的描述（由模块按站点搜索接口给出）。"""

    url: str = ""                   # 完整请求地址（GET 时不含 data）
    method: str = "GET"             # GET / POST
    data: dict = field(default_factory=dict)   # POST 表单或 GET 附加参数
    encoding: str = ""              # 强制解码编码；空 = 自动探测
    referer: str = ""               # 部分 CMS 校验来源
    headers: dict = field(default_factory=dict)
    base: str = ""                  # 结果中相对链接的补全基址
    # 先访问 base 预热会话（拿 cookie），再发搜索请求；关闭则直接请求
    warmup: bool = True


def trim_search_items(items: list, limit: int) -> list:
    """搜索结果按上限截断：网盘标记条目优先保留并排在最前。

    站点搜索结果普遍按时间排序，网盘帖比例低、常被种子帖挤到上限之外；
    直接按顺序截断会让用户「搜不到网盘资源」。
    """
    if not limit or len(items) <= limit:
        return items
    from ..netdisk import looks_pan_title

    def _is_pan(it) -> bool:
        return looks_pan_title(getattr(it, "title", ""))

    pan = [it for it in items if _is_pan(it)]
    rest = [it for it in items if not _is_pan(it)]
    return (pan + rest)[:limit]


class SiteModule:
    """站点解析模块接口。子类实现 parse_list / parse_detail 即可。

    搜索为可选能力：置 ``supports_search = True`` 并实现 ``search_spec``
    与 ``parse_search`` 即可，分页/去重/取消由基类统一处理。
    """

    meta: ModuleMeta
    # 列表页默认抓取页数（1 = 只抓入口页）；需要翻页的模块可覆盖
    max_list_pages = 1
    # 搜索（可选能力）
    supports_search = False
    max_search_pages = 1
    search_result_limit = 0         # 0 = 不限制

    # ------------------------------------------------------------ 接口
    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        """列表页（首页/分类页/版块页）→ list[ParseItem]。

        base_url 用于把相对链接补全为详情页绝对地址；
        entry_url 为本次抓取的入口地址（多入口站点可按入口归区块）。
        """
        raise NotImplementedError

    def parse_list_pages(self, html: str, base_url: str, entry_url: str = "",
                         fetcher=None, max_pages: int = 1,
                         include_unknown: bool = True) -> list:
        """多页列表抓取（默认只抓入口页；需要翻页的模块覆盖本方法）。

        fetcher 由服务层注入；返回合并去重后的 list[ParseItem]。
        """
        return self.parse_list(html, base_url, entry_url, include_unknown)

    def parse_detail(self, html: str, item: ParseItem) -> None:  # noqa: F821
        """详情页解析：填充 item.magnets / item.desc（失败可留空由补抓兜底）。"""
        raise NotImplementedError

    # ------------------------------------------------------------ 搜索
    def search_spec(self, keyword: str, page: int = 1,
                    base: str = "") -> Optional[SearchSpec]:
        """第 page 页搜索请求描述；返回 None 表示不支持搜索。"""
        return None

    def parse_search(self, text: str, base_url: str) -> list:
        """搜索结果（HTML 或 JSON 文本）→ list[ParseItem]。"""
        return []

    def search(self, keyword: str, fetcher, max_pages: Optional[int] = None,
               base: str = "", polite_delay: float = 0.0,
               log_cb=None, cancel=None, page_html: Optional[list] = None
               ) -> list:
        """按关键词搜索：分页抓取 → 解析 → 按详情 URL 去重。

        子类只需实现 search_spec / parse_search；本方法负责分页、
        取消、礼貌延时与跨页去重。

        page_html：可选的**出参列表**，抓取到的每一页 HTML 会依次追加，
        供上层判断“响应过短/疑似被限流”（避免上层无法接触原始响应）。
        """
        if not self.supports_search:
            return []
        kw = (keyword or "").strip()
        if not kw:
            return []
        pages = max(1, int(max_pages or self.max_search_pages or 1))
        limit = int(getattr(self, "search_result_limit", 0) or 0)
        items: list = []
        seen: set = set()
        warmed = False
        for page in range(1, pages + 1):
            if cancel and cancel():
                break
            spec = self.search_spec(kw, page, base=base)
            if spec is None:
                break
            if not warmed and spec.warmup:
                # 先访问站点首页拿到会话 cookie，再发搜索请求
                try:
                    fetcher.warmup(spec.base or spec.url)
                except Exception:
                    pass
                if polite_delay > 0:
                    time.sleep(min(polite_delay, 1.5))
                warmed = True
            try:
                text, _ = self._request_search(fetcher, spec)
            except Exception as e:  # 单页失败不阻断其它页
                if log_cb:
                    log_cb(f"[搜索] “{kw}” 第 {page} 页请求失败："
                       f"{type(e).__name__}: {e}")
                break
            if page_html is not None:
                page_html.append(text or "")
            got = self.parse_search(text or "", spec.base or spec.url or base)
            added = 0
            for it in got:
                key = it.detail_url or it.title
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(it)
                added += 1
            if log_cb:
                log_cb(f"[搜索] “{kw}” 第 {page} 页：解析 {len(got)} 条，"
                       f"新增 {added} 条")
            if not added:
                break
            if polite_delay > 0:
                time.sleep(min(polite_delay, 1.5))
        return trim_search_items(items, limit)

    @staticmethod
    def _request_search(fetcher, spec: "SearchSpec") -> tuple:
        """按 spec 发请求；GET 时把 data 拼进 query。"""
        from ..fetcher import resolve_encoding

        enc = resolve_encoding(spec.encoding) or None
        if (spec.method or "get").strip().lower() == "post":
            return fetcher.post(spec.url, data=dict(spec.data or {}),
                                encoding=enc, referer=spec.referer,
                                headers=spec.headers)
        url = spec.url or ""
        if spec.data:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode(spec.data)
        return fetcher.get(url, encoding=enc)

    # ------------------------------------------------------------ 辅助
    def blocks(self) -> list:
        """该模块可能产出的区块 label（设置页勾选过滤用）。"""
        from ... import constants

        return list(constants.BLOCK_KEYWORDS.keys())

    def entry_mode(self) -> str:
        return self.meta.entry_mode
