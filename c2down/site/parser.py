"""首页 / 详情页解析器（纯标准库 + 正则，模板无关、可单测）。

策略说明：
- 首页：以“带 [日期] 的更新行”为核心提取（需求：中部不定时更新信息，
  每条后有日期；其它部分忽略）。日期前的链接归为详情页候选。
- 区块归属：扫描含标题特征（h1-6/b/strong/含 title 的 class）的关键词
  上下文，作为区块边界。
- 红链/经典：行上下文命中红色样式或文字含“经典”即打星。
- 详情页：提取磁力链接及其文字 label（label 用于剧集分集）。
"""
from __future__ import annotations

import bisect
import html as html_mod
import re
import time
from urllib.parse import urljoin, urlparse

from .. import constants
from ..models import MagnetLink, ParseItem

# ---------------------------------------------------------------- 正则
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
_YMD_RE = re.compile(r"(?<![0-9])(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_MD_RE = re.compile(r"(?<![0-9])(\d{1,2})-(\d{1,2})(?!\d)")
_MAGNET_RE = re.compile(r"magnet:\?xt=urn:[a-z0-9]+:[A-Za-z0-9_-]{16,}")
_RED_RE = re.compile(constants.RED_RE_STR, re.I)
_DN_RE = re.compile(r"[?&]dn=([^&\s]+)")
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
    re.I,
)

_EXCLUDE_TAIL = ("更多", "下一页", "上一页", "尾页", "首页", "返回",
                 "网站地图", "RSS", "收藏本站", "加入收藏", "全选", "登录",
                 "注册", "迅雷", "发帖", "回复", "查看", "版权", "免责",
                 "榜单", "排行榜", "教程", "帮助", "007全集", "论坛",
                 "联系我们", "公告", "新版6V", "旧版66影视", "专题")

# ---------------------------------------------------------------- 工具


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = html_mod.unescape(s)
    s = s.replace("\xa0", " ").replace("\u3000", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def _in_tag(html: str, pos: int) -> bool:
    """pos 是否位于某个开始标签的属性内（如 href 里的日期）。"""
    lt = html.rfind("<", 0, pos)
    gt = html.rfind(">", 0, pos)
    return lt > gt


# 标题质量判定：电影/剧集条目通常含年份、片名书名号或清晰度标记
_TITLE_QUAL_RE = re.compile(
    r"(\d{4}|《|》|1080|720p|4K|BD|HD|WEB|全集|更新至|第\s*\d+\s*集|"
    r"剧场版|加长版|导演剪辑|中英|国语|粤语|国英|双语|中字|字幕)"
)


def block_label_for_heading(text: str) -> str:
    for label, kws in constants.BLOCK_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return label
    return ""


def _parse_date(raw: str) -> str:
    return (raw or "").strip().strip("[]()").replace(".", "-").replace("/", "-")


class HomeParser:
    def __init__(self, html: str, base_url: str):
        self.html = html
        self.base = base_url

    # ------------------------------------------------ 内部步骤
    _LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S)
    _H_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.S)
    _DATE_SPAN_RE = re.compile(
        r"<span[^>]*>\s*[\[\(]?(\d{1,2})-(\d{1,2})[\]\)]?\s*</span>"
        r"|<span[^>]*>\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*</span>",
        re.I,
    )

    def _collect_headings(self):
        """页面中 h1-h4 标题位置与文字。"""
        out = []
        for m in self._H_RE.finditer(self.html):
            text = clean_html(m.group(2))
            if text:
                out.append((m.start(), text))
        out.sort(key=lambda x: x[0])
        return out

    @staticmethod
    def _pick_li_date(inner: str):
        """在 <li> 内找日期（优先日期 span，兼容无 span 行）。"""
        dm = HomeParser._DATE_SPAN_RE.search(inner)
        if dm:
            if dm.group(1):
                return f"{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
            if dm.group(3):
                return f"{dm.group(3)}-{int(dm.group(4)):02d}-{int(dm.group(5)):02d}"
        for m in re.finditer(
            r"[\[\(]?(\d{4})-(\d{1,2})-(\d{1,2})[\]\)]?"
            r"|[\[\(]?(\d{1,2})-(\d{1,2})[\]\)]?",
            inner,
        ):
            if _in_tag(inner, m.start()):
                continue
            if m.group(1):
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            if m.group(4):
                return f"{int(m.group(4)):02d}-{int(m.group(5)):02d}"
        return ""

    # ------------------------------------------------ 主入口
    def parse(self, include_unknown: bool = True) -> list:
        """按 <li> 行 + 最近 <h3> 标题归区解析首页更新列表。

        模板结构（实测）：
          <li><span>[09-04]</span><a href="...">标题</a></li>
          区块标题位于 <h3>…★区块名★…</h3>；红链 = <a>内<font color=red>。
        """
        html = self.html
        headings = self._collect_headings()
        seen = {}
        cur_label = None
        hi = 0
        for lm in self._LI_RE.finditer(html):
            pos = lm.start()
            inner = lm.group(1)
            # 前进到该行之前最近的标题
            while hi < len(headings) and headings[hi][0] <= pos:
                lab = block_label_for_heading(headings[hi][1])
                if lab:
                    cur_label = lab
                hi += 1
            if not cur_label:
                continue  # 首个区块标题之前的内容（顶部导航等）忽略
            date = self._pick_li_date(inner)
            if not date:
                continue
            am = _A_RE.search(inner)
            if not am:
                continue
            open_tag, a_inner = am.group(1), am.group(2)
            href_m = _HREF_RE.search(open_tag)
            if not href_m:
                continue
            href = href_m.group(1).strip()
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            text = clean_html(a_inner)
            if len(text) < 5:
                continue
            if any(t in text for t in _EXCLUDE_TAIL):
                continue
            if not href.lower().endswith(".html"):
                continue
            if not _TITLE_QUAL_RE.search(text):
                continue
            # 红色 / 经典标记（在 <li> 内部判断，避免全页误报）
            is_red = bool(re.search(
                r"<font\b[^>]*color\s*=\s*[\"']?#?[Ff][Ff]0000[\"']?", inner)) \
                or bool(_RED_RE.search(inner))
            is_classic = ("经典" in text) or (cur_label == "经典高清")
            title = re.sub(r"^[\[\(]?\d{1,2}-\d{1,2}[\]\)]?\s*", "", text).strip()
            title = re.sub(r"^【[^】]*】\s*", "", title).strip()
            detail = urljoin(self.base, href)
            if detail in seen:
                continue
            it = ParseItem(title=title, date=date, block=cur_label,
                           detail_url=detail, is_red=is_red,
                           is_classic=is_classic)
            seen[detail] = it
        return list(seen.values())

    def blocks_found(self) -> list:
        return [label for label in constants.BLOCK_KEYWORDS if self._any_block_label(label)]

    def _any_block_label(self, label: str) -> bool:
        for kw in constants.BLOCK_KEYWORDS.get(label, []):
            if kw in self.html:
                return True
        return False


def host_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


# ---------------------------------------------------------------- 详情页
def parse_detail_magnets(html: str) -> list:
    """解析详情页所有磁力，返回 list[MagnetLink]。label 优先取磁力所在 <a> 的文字。"""
    out = []
    for m in _MAGNET_RE.finditer(html or ""):
        url = m.group(0)
        label = _label_for_magnet(html, m.start())
        if not label:
            label = _dn_of(url)
        out.append(MagnetLink(label=label[:80], url=url))
    dedup, seen = [], set()
    for ml in out:
        if ml.url in seen:
            continue
        seen.add(ml.url)
        dedup.append(ml)
    return dedup


def _label_for_magnet(html: str, pos: int) -> str:
    """磁力所在 <a> 的文字（第X集 等），兼容磁力在 href 属性内或 a 文本内。"""
    oa = html.rfind("<a", 0, pos)
    if oa >= 0:
        gt = html.find(">", oa)
        ca = html.find("</a>", pos)
        if (
            gt > 0
            and ca > pos
            and ca - oa < 1000
        ):
            inner = html[gt + 1:ca]
            if "<" not in inner:
                label = clean_html(inner)
                if label:
                    return label[:80]
    # 兜底：磁力前最近的一个完整链接文字
    head = html[max(0, pos - 500):pos]
    m = re.findall(r"<a\b[^>]*>(.*?)</a>", head, re.S)
    raw = m[-1] if m else ""
    if raw and "<" not in raw:
        return clean_html(raw)[:80]
    return ""


def _dn_of(url: str) -> str:
    m = _DN_RE.search(url)
    if m:
        try:
            from urllib.parse import unquote

            return unquote(m.group(1)).replace("+", " ")
        except Exception:
            return m.group(1)
    return ""


def parse_detail_desc(html: str) -> str:
    """详情页简介：优先 meta description，其次页面前段文本。"""
    m = _META_DESC_RE.search(html or "")
    if m:
        desc = clean_html(m.group(1))
        if len(desc) >= 8:
            return desc[:500]
    text = clean_html(html)
    i = text.find("◎")
    if i >= 0:
        seg = text[i:i + 420].strip()
        if seg:
            return seg[:420]
    return text[:220]
# END

