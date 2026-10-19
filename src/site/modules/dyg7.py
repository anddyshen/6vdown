"""电影港新版 dyg7.com 专用解析模块（EmpireCMS + 新模板 · utf-8）。

实测结构：
- 入口是分类列表页（不是首页）：``/dy/ /dsj/ /duanju/ /dongman/ /zyjm/``
  及子分类 ``/dsj/dlj|rhj|omj/``；列表按“最新”排序；
- 列表项：``<li class="p1 m1"><a class="link-hover" href="/dy/jqp/25355.html"
  title="片名"><p class="name">片名</p>...<p class="other"><i>正片</i></p></a>``；
- 分页：``{入口}index_N.html``（第 2 页起）；
- 列表页与详情页均无日期字段 → date 留空，剧集更新靠“标题+状态”变更识别
  （``<i>更新至18集</i>`` 等状态会并入标题，状态前进即判定为更新）；
- 详情页磁力在下载区（通用正则），简介取 meta description（◎ 格式）。

区块归属按入口路径映射（见 _ENTRY_BLOCKS，长前缀优先）。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ...models import ParseItem
from ..parser import clean_html
from .base import ModuleMeta, SearchSpec, SiteModule, root_url

# 入口路径 → 区块 label（长前缀在前，优先匹配）
_ENTRY_BLOCKS = (
    ("/dsj/dlj/", "国剧"),
    ("/dsj/rhj/", "日韩剧"),
    ("/dsj/omj/", "美剧"),
    ("/dsj/", "更新电视剧"),
    ("/duanju/", "短剧"),
    ("/dongman/", "动画"),
    ("/zyjm/", "综艺"),
    ("/dy/", "最新电影"),
)

_LI_RE = re.compile(r'<li class="p1 m1">(.*?)</li>', re.S)
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
_TITLE_ATTR_RE = re.compile(r'\btitle\s*=\s*["\']([^"\']*)["\']', re.I)
_NAME_RE = re.compile(r'<p class="name">(.*?)</p>', re.S)
_STATUS_RE = re.compile(r'<p class="other">\s*<i>(.*?)</i>', re.S)
_ALT_RE = re.compile(r"alt\s*=\s*[\"']([^\"']+)[\"']", re.I)


_SEARCH_PATH = "e/search/index.php"      # EmpireCMS 搜索入口（全站共用）
_DEFAULT_ROOT = "https://www.dyg7.com/"


class Dyg7Module(SiteModule):
    """电影港新版（dyg7.com 及其同模板镜像）。"""

    max_list_pages = 2  # 入口页 + 1 页翻页（列表无日期，靠翻页补增量）

    # 搜索：EmpireCMS 通用 /e/search/index.php（POST · utf-8）
    supports_search = True
    max_search_pages = 1
    search_result_limit = 80

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="dyg7",
            name="电影港新版（dyg7.com）",
            desc=("EmpireCMS 新模板分类列表页；utf-8；.html 详情页；"
                  "列表无日期；支持站内搜索"),
            entry_mode="entries",
            encoding="utf-8",
            default_entry_urls=(
                "https://www.dyg7.com/dy/",
                "https://www.dyg7.com/dsj/dlj/",
                "https://www.dyg7.com/dsj/rhj/",
                "https://www.dyg7.com/dsj/omj/",
                "https://www.dyg7.com/dsj/",
                "https://www.dyg7.com/duanju/",
                "https://www.dyg7.com/dongman/",
                "https://www.dyg7.com/zyjm/",
            ),
        )

    # ------------------------------------------------------------ 列表
    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        return parse_list(html, base_url, entry_url)

    def parse_list_pages(self, html: str, base_url: str, entry_url: str = "",
                         fetcher=None, max_pages: int = 1,
                         include_unknown: bool = True) -> list:
        items = self.parse_list(html, base_url, entry_url, include_unknown)
        if fetcher is None or max_pages <= 1:
            return items
        seen = {it.detail_url for it in items}
        for page in range(2, max_pages + 1):
            url = page_url(entry_url, page)
            if not url:
                break
            try:
                html2, _ = fetcher.get(url, timeout=14)
            except Exception:
                break
            more = self.parse_list(html2, url, entry_url, include_unknown)
            if not more:
                break
            added = 0
            for it in more:
                if it.detail_url not in seen:
                    seen.add(it.detail_url)
                    items.append(it)
                    added += 1
            if not added:
                break  # 整页无新条目 → 停止翻页
        return items

    # ------------------------------------------------------------ 详情
    # ------------------------------------------------------------ 搜索
    def search_spec(self, keyword: str, page: int = 1,
                    base: str = "") -> SearchSpec:
        root = root_url(base, _DEFAULT_ROOT)
        data = {"keyboard": keyword, "show": "title,zhuyan", "tempid": "1"}
        if page > 1:
            data["page"] = str(page)
        return SearchSpec(url=urljoin(root, _SEARCH_PATH), method="POST",
                          data=data, encoding="utf-8", referer=root,
                          base=root)

    def parse_search(self, text: str, base_url: str) -> list:
        """搜索结果页的 li.p1 m1 结构与分类列表页一致 → 直接复用。"""
        return parse_list(text, base_url, "")

    def parse_detail(self, html: str, item: ParseItem) -> None:
        # 磁力/简介与 6v 家族同构：磁力在下载区，简介取 meta description（◎）
        from ..netdisk import extract_pan_links
        from ..parser import parse_detail_desc, parse_detail_magnets

        item.magnets = parse_detail_magnets(html)
        # 详情页也可能给出网盘分享（含提取码），一并收录为“仅复制”资源
        item.magnets += extract_pan_links(html, item.detail_url or "",
                                         item.title or "")
        if not item.desc:
            item.desc = parse_detail_desc(html)


# ---------------------------------------------------------------- 工具
def page_url(entry_url: str, page: int) -> str:
    """分类页第 N 页地址：``{入口}index_N.html``。"""
    if not entry_url or page < 2:
        return ""
    return entry_url.rstrip("/") + f"/index_{page}.html"


def block_for_entry(entry_url: str) -> str:
    path = urlparse(entry_url or "").path or "/"
    for prefix, label in _ENTRY_BLOCKS:
        if prefix in path:
            return label
    return "其他"


def _title_of(inner: str) -> str:
    """优先 title 属性（完整片名），其次 p.name / img alt。"""
    m = _TITLE_ATTR_RE.search(inner)
    if m:
        t = clean_html(m.group(1))
        if t:
            return t
    m = _NAME_RE.search(inner)
    if m:
        t = clean_html(m.group(1))
        if t:
            return t
    m = _ALT_RE.search(inner)
    if m:
        return clean_html(m.group(1))
    return ""


def parse_list(html: str, base_url: str, entry_url: str = "") -> list:
    """分类列表页 → list[ParseItem]（按入口归区块；状态并入标题）。"""
    block = block_for_entry(entry_url)
    items: dict = {}
    for lm in _LI_RE.finditer(html or ""):
        inner = lm.group(1)
        am = _A_RE.search(inner)
        if not am:
            continue
        hm = _HREF_RE.search(am.group(1))
        if not hm:
            continue
        href = hm.group(1).strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if not href.lower().endswith((".htm", ".html")):
            continue
        name = _title_of(inner)
        if len(name) < 2:
            continue
        status = ""
        sm = _STATUS_RE.search(inner)
        if sm:
            status = clean_html(sm.group(1))
        # “正片”是电影的常态不并入标题；更新至N集/全集等状态并入，
        # 使同一详情页的剧集前进能被识别为“更新”。
        title = name if (not status or status == "正片") else f"{name}（{status}）"
        detail = urljoin(base_url, href)
        if detail in items:
            continue
        items[detail] = ParseItem(
            title=title, date="", block=block, detail_url=detail,
            is_classic=("经典" in name))
    return list(items.values())
