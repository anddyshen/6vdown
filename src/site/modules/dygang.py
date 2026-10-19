"""电影港 dygang.tv 专用解析模块（EmpireCMS 老模板 · gb2312 · table 行布局）。

与 hao6v 模块的实测差异：
- 更新行是嵌套 table：标题链接 ``<a class="c2" href="/ys/20261018/60778.htm">片名</a>``
  后跟一个仅含日期的小表格 ``<td>2026-10-18</td>``（不是 6v520 的 <li>+<span> 行）；
- 区块标签写在 ``<li id="tabN_btn_M">最新电影(更新)</li>`` 按钮上，
  列表容器是 ``<div id="tabN_div_M">``（该站按钮编号与容器编号不一致，
  故按“容器之前同组第一个按钮”退化配对）；
- 详情页链接以 .htm 结尾，标题多为裸片名（无画质标记），不能套用 hao6v 的
  标题质量过滤——这里以“日期锚点”作为主过滤（链接后 900 字符内必须出现日期）。

解析策略：遍历全页日期 → 向前就近取最后一个有效标题链接 → 按最近的
tab 容器 / 标题边界归区块 → 按详情 URL 去重（保留更具体区块、合并标记）。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ... import constants
from ...models import ParseItem
from ..parser import block_label_for_heading, clean_html, tab_block_label
from .base import ModuleMeta, SearchSpec, SiteModule, root_url

_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
_ALT_RE = re.compile(r"alt\s*=\s*[\"']([^\"']+)[\"']", re.I)
_YMD_RE = re.compile(r"(?<![0-9])(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_TAB_DIV_RE = re.compile(
    r"<div\b[^>]*\bid\s*=\s*[\"']?tab(\d+)_div_(\d+)[\"']?", re.I)
_TAB_BTN_RE = re.compile(
    r"<li\b[^>]*\bid\s*=\s*[\"']?tab(\d+)_btn_(\d+)[\"']?[^>]*>(.*?)</li>",
    re.S | re.I,
)
_H_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.S)
_RED_FONT_RE = re.compile(
    r"<font\b[^>]*color\s*=\s*[\"']?#?[Ff][Ff]0000[\"']?", re.I)
_RED_RE = re.compile(constants.RED_RE_STR, re.I)

_EXCLUDE_TAIL = ("更多", "下一页", "上一页", "尾页", "首页", "返回",
                 "网站地图", "RSS", "收藏本站", "加入收藏", "全选", "登录",
                 "注册", "迅雷", "发帖", "回复", "查看", "版权", "免责",
                 "榜单", "排行榜", "教程", "帮助", "论坛", "联系我们",
                 "公告", "专题", "留言板")

# 与 parser.py 保持一致：同一链接出现在多个区块时保留更具体的归属
_BLOCK_PRIORITY = {
    "美剧": 3, "日韩剧": 3, "国剧": 3,
    "动画": 2, "经典高清": 2,
    "最新电影": 1, "更新电视剧": 1,
}

_LOOKBACK = 900  # 日期锚点向前寻找标题链接的窗口（实测行高约 200-400 字符）


_SEARCH_PATH = "e/search/index.php"      # EmpireCMS 搜索入口（全站共用）
_DEFAULT_ROOT = "https://www.dygang.tv/"


class DygangModule(SiteModule):
    """电影港（dygang.tv 及其同模板镜像）。"""

    # 搜索：EmpireCMS 通用 /e/search/index.php（POST · gb2312）
    supports_search = True
    max_search_pages = 1
    search_result_limit = 80

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="dygang",
            name="电影港（dygang.tv）",
            desc="EmpireCMS 老模板 table 行布局；gb2312；.htm 详情页；支持站内搜索",
            entry_mode="entries",
            encoding="gb2312",
            default_entry_urls=("https://www.dygang.tv/",),
        )

    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        return parse_home(html, base_url)

    def search_spec(self, keyword: str, page: int = 1,
                    base: str = "") -> SearchSpec:
        root = root_url(base, _DEFAULT_ROOT)
        data = {"tempid": "1", "tbname": "article", "keyboard": keyword,
                "show": "title,smalltext"}
        if page > 1:
            data["page"] = str(page)
        return SearchSpec(url=urljoin(root, _SEARCH_PATH), method="POST",
                          data=data, encoding="gb2312", referer=root,
                          base=root)

    def parse_search(self, text: str, base_url: str) -> list:
        """搜索结果页 → list[ParseItem]。

        结果页与首页结构不同：首页是「标题链接 → 日期」，而搜索结果页是
        「图片链接 → 日期 → 标题链接(class=classlinkclass)」，故单独解析，
        并按 ``<td width=50%>`` 切块避免跨条目取错日期。
        """
        return parse_search_results(text, base_url)


# ---------------------------------------------------------------- 搜索解析
_SEARCH_LINK_RE = re.compile(
    r'<a\b[^>]*class\s*=\s*["\']?classlinkclass["\']?[^>]*>(.*?)</a>',
    re.S | re.I)
_ITEM_SPLIT_RE = re.compile(r"<td\s+width=['\"]?50%['\"]?\s*>", re.I)


def parse_search_results(html: str, base_url: str) -> list:
    """解析电影港搜索结果页（按条目块定位标题链接与日期）。"""
    items: dict = {}
    for chunk in _ITEM_SPLIT_RE.split(html or "")[1:]:
        lm = _SEARCH_LINK_RE.search(chunk)
        if not lm:
            continue
        hm = _HREF_RE.search(lm.group(0))
        if not hm:
            continue
        href = (hm.group(1) or "").strip()
        if not href.lower().endswith((".htm", ".html")):
            continue
        title = clean_html(lm.group(1))
        if len(title) < 2 or any(t in title for t in _EXCLUDE_TAIL):
            continue
        detail = urljoin(base_url, href)
        if detail in items:
            continue
        head = chunk[:lm.start()]
        dates = list(_YMD_RE.finditer(head))
        date = ""
        if dates:
            dm = dates[-1]
            date = (f"{dm.group(1)}-{int(dm.group(2)):02d}"
                    f"-{int(dm.group(3)):02d}")
        items[detail] = ParseItem(
            title=title, date=date, block="其他", detail_url=detail,
            is_red=bool(_RED_FONT_RE.search(head[-300:] or "")
                        or _RED_RE.search(head[-300:] or "")),
            is_classic=("经典" in title))
    return list(items.values())

    def parse_detail(self, html: str, item: ParseItem) -> None:
        # 详情页磁力/简介与 6v 家族同构：磁力在【下载地址】区，简介取 meta/◎
        from ..netdisk import extract_pan_links
        from ..parser import parse_detail_desc, parse_detail_magnets

        item.magnets = parse_detail_magnets(html)
        item.desc = parse_detail_desc(html)
        # 详情页也可能给出网盘分享（含提取码），一并收录为“仅复制”资源
        item.magnets += extract_pan_links(html, item.detail_url or "",
                                         item.title or "")


# ---------------------------------------------------------------- 区块边界
def _collect_boundaries(html: str) -> list:
    """[(位置, 区块 label)]：tab 容器 + h1-h4 标题，按位置排序。"""
    out = []
    btns = {}  # (tabN, M) -> (pos, 原始按钮文字)
    for m in _TAB_BTN_RE.finditer(html):
        btns[(m.group(1), int(m.group(2)))] = (m.start(), m.group(3))
    for dm in _TAB_DIV_RE.finditer(html):
        n, mm = dm.group(1), int(dm.group(2))
        raw = ""
        same = [(pos, text) for (bn, bm), (pos, text) in btns.items()
                if bn == n and bm == mm and pos <= dm.start()]
        if same:
            raw = same[-1][1]  # 同编号按钮中最近的一个
        else:
            # 退化配对：该 tab 组中位于容器之前的第一个按钮
            group = sorted((pos, bm, text)
                           for (bn, bm), (pos, text) in btns.items()
                           if bn == n and pos <= dm.start())
            if group:
                raw = group[0][2]
        label = tab_block_label(raw) if raw else ""
        if not label and raw:
            label = block_label_for_heading(clean_html(raw))
        if label:
            out.append((dm.start(), label))
    for hm in _H_RE.finditer(html):
        label = block_label_for_heading(clean_html(hm.group(2)))
        if label:
            out.append((hm.start(), label))
    out.sort(key=lambda x: x[0])
    return out


def _block_at(boundaries: list, pos: int) -> str:
    label = "其他"
    for bpos, blab in boundaries:
        if bpos <= pos:
            label = blab
        else:
            break
    return label


# ---------------------------------------------------------------- 主解析
def parse_home(html: str, base_url: str) -> list:
    """电影港首页 → list[ParseItem]（日期锚点 + 就近标题链接）。"""
    boundaries = _collect_boundaries(html or "")
    items: dict = {}
    for dm in _YMD_RE.finditer(html or ""):
        pos = dm.start()
        date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        hit = _nearest_title_link(html, pos)
        if not hit:
            continue
        href, text, link_pos = hit
        title = re.sub(r"^[\[\(]?\d{1,2}-\d{1,2}[\]\)]?\s*", "", text).strip()
        title = re.sub(r"^【[^】]*】\s*", "", title).strip()
        detail = urljoin(base_url, href)
        block = _block_at(boundaries, pos)
        seg = html[link_pos:pos]
        is_red = bool(_RED_FONT_RE.search(seg)) or bool(_RED_RE.search(seg))
        is_classic = ("经典" in text) or (block == "经典高清")
        old = items.get(detail)
        if old is not None:
            if _BLOCK_PRIORITY.get(block, 0) > _BLOCK_PRIORITY.get(old.block, 0):
                old.block = block
            old.is_red = old.is_red or is_red
            old.is_classic = old.is_classic or is_classic
            continue
        items[detail] = ParseItem(
            title=title, date=date, block=block, detail_url=detail,
            is_red=is_red, is_classic=is_classic)
    return list(items.values())


def _nearest_title_link(html: str, pos: int):
    """日期锚点向前窗口中最后一个有效标题链接 → (href, text, 链接起始位置)。

    站点会把列表里的标题文字截断（实测 8 字左右），而同一条目图片的 alt
    通常是完整片名；当链接文字是某个 alt 的前缀时，用 alt 补全标题。
    """
    start = max(0, pos - _LOOKBACK)
    head = html[start:pos]
    alts = [(m.start(), clean_html(m.group(1))) for m in _ALT_RE.finditer(head)]
    best = None
    for am in _A_RE.finditer(head):
        open_tag, inner = am.group(1), am.group(2)
        hm = _HREF_RE.search(open_tag)
        if not hm:
            continue
        href = hm.group(1).strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if not href.lower().endswith((".htm", ".html")):
            continue
        text = clean_html(inner)
        if len(text) < 2:
            continue  # 图片链接（无文字）等
        if any(t in text for t in _EXCLUDE_TAIL):
            continue
        best = (href, text, start + am.start())
    if not best:
        return None
    href, text, abs_pos = best
    anchor_off = abs_pos - start
    for apos, atext in reversed(alts):
        if apos <= anchor_off and len(atext) > len(text) and atext.startswith(text):
            text = atext  # 被站点截断的标题 → 用同条目 alt 补全
            break
    return href, text, abs_pos
