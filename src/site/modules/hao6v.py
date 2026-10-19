"""hao6v / 6v520 老模板站点模块。

把原有 HomeParser + parse_detail_magnets/parse_detail_desc 原样包装成模块，
保证重构后行为零变化。适用：hao6v.cc、6v520.net/cc 及其同模板镜像。

搜索：站点用 EmpireCMS ``/e/search/index.php``（POST · gb2312），
结果页结构与首页不同（无 <li> 行，标题链接在 <span class="blue14"> 内），
故单独解析。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ...models import ParseItem
from ..netdisk import extract_pan_links
from ..parser import (HomeParser, clean_html, parse_detail_desc,
                      parse_detail_magnets)
from .base import ModuleMeta, SearchSpec, SiteModule, looks_detail_url, root_url

_SEARCH_PATH = "e/search/index.php"
_DEFAULT_ROOT = "https://www.hao6v.cc/"

_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
# 该站搜索结果里的 href 不带引号，三种写法都要支持
_HREF_RE = re.compile(
    r"href\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
_BLUE_RE = re.compile(r'<span class="blue14">(.*?)</span>', re.S | re.I)
_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_RED_RE = re.compile(r"color\s*[:=]\s*['\"]?#?[Ff][Ff]0000", re.I)

# 详情路径前缀 → 区块 label（长前缀在前）
_PATH_BLOCKS = (
    ("/dsj/", "更新电视剧"),
    ("/dm/", "动画"),
    ("/dh/", "动画"),
    ("/zy/", "综艺"),
    ("/gq/", "国剧"),
    ("/dy/", "最新电影"),
)


class Hao6vModule(SiteModule):
    """6v520/hao6v 家族：首页 tab 区块 + <li> 行 + 日期，详情页磁力/◎简介。"""

    # 搜索：EmpireCMS 通用 /e/search/index.php（POST · gb2312）
    supports_search = True
    max_search_pages = 1
    search_result_limit = 80

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="hao6v",
            name="6v电影（hao6v / 6v520 模板）",
            desc="首页标签页区块更新列表；详情页提取磁力与◎简介；支持站内搜索",
            entry_mode="mirror",
            encoding="gb2312",
        )

    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        return HomeParser(html, base_url).parse(include_unknown=include_unknown)

    def parse_detail(self, html: str, item) -> None:
        item.magnets = parse_detail_magnets(html)
        item.desc = parse_detail_desc(html)
        # 详情页也可能给出网盘分享（含提取码），一并收录为“仅复制”资源
        item.magnets += extract_pan_links(html, item.detail_url or "",
                                         item.title or "")

    # ------------------------------------------------------------ 搜索
    def search_spec(self, keyword: str, page: int = 1,
                    base: str = "") -> SearchSpec:
        root = root_url(base, _DEFAULT_ROOT)
        data = {"show": "title,smalltext", "tempid": "1",
                "tbname": "article", "keyboard": keyword}
        if page > 1:
            data["page"] = str(page)
        return SearchSpec(url=urljoin(root, _SEARCH_PATH), method="POST",
                          data=data, encoding="gb2312", referer=root,
                          base=root)

    def parse_search(self, text: str, base_url: str) -> list:
        """搜索结果页 → list[ParseItem]。"""
        return parse_search_results(text, base_url)


# ---------------------------------------------------------------- 搜索解析
def parse_search_results(html: str, base_url: str) -> list:
    """解析 hao6v 搜索结果页。

    实测片段（href 无引号、标题包在 <font> 里、日期在随后的单元格）：

    ``<td width="41%" height="25"><font color="#663333">・[<a href=/dy/>...]``
    ``<span class="blue14"><a href=/dy/2026-03-29/49243.html target=_blank>``
    ``<font color='#FF0000'>标题</font></a></span></font></td>``
    ``<td width="59%"><font color="#666666">发布时间：2026-05-21 17:30:38</font></td>``

    标题链接固定在 ``<span class="blue14">`` 内；页头导航（公告区、排行榜等）
    不在其中，故先定位该 span 再取链接，避免把导航噪声收进结果。
    """
    items: dict = {}
    for sm in _BLUE_RE.finditer(html or ""):
        lm = _A_RE.search(sm.group(1))
        if not lm:
            continue
        hm = _HREF_RE.search(lm.group(1))
        if not hm:
            continue
        href = (hm.group(1) or hm.group(2) or hm.group(3) or "").strip()
        if not looks_detail_url(href):
            continue
        detail = urljoin(base_url, href)
        if detail in items:
            continue
        title = clean_html(lm.group(2))
        if len(title) < 2 or title == href or title == detail:
            continue  # 空链接 / 站点把 URL 当文字渲染
        seg = html[sm.end(): sm.end() + 800]
        dm = _DATE_RE.search(seg)
        date = ""
        if dm:
            date = (f"{dm.group(1)}-{int(dm.group(2)):02d}"
                    f"-{int(dm.group(3)):02d}")
        items[detail] = ParseItem(
            title=title, date=date, block=block_for_path(href),
            detail_url=detail, is_red=bool(_RED_RE.search(lm.group(0))))
    return list(items.values())


def block_for_path(url_or_path: str) -> str:
    """按详情路径前缀推断区块 label。"""
    path = url_or_path or ""
    idx = path.find("://")
    if idx >= 0:
        rest = path[idx + 3:]
        slash = rest.find("/")
        path = rest[slash:] if slash >= 0 else "/"
    if not path.startswith("/"):
        path = "/" + path
    for prefix, label in _PATH_BLOCKS:
        if prefix in path:
            return label
    return "其他"
