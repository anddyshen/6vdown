"""通用规则模块引擎：规则 JSON 驱动，新站点零代码接入。

设计来源：把 hao6v / dygang / dyg7 / lou1 四个内置模块的解析逻辑抽象为
一门“规则语言”（工程上只有正则可用，故全部规则都是正则原语）：

- 提取模式 rows（行容器 + 行内链接/标题/日期/状态）：覆盖 dyg7 / lou1 / hao6v；
- 提取模式 date_anchor（日期锚点 + 向前就近链接）：覆盖 dygang；
- 区块归属：入口路径映射（block_map）优先，其次最近的标题/标签按钮（block_re）；
- 详情页：磁力正则 + 附件/网盘链接识别（kind=magnet/torrent/pan）；
- 翻页：page_template（如 {entry}index_{page}.html），整页无新增即停。

规则 JSON 结构见 rules/*.json（内置站点的等价表达，可作模板）。
校验与存储见 rule_store.py；本地/AI 推导见 analyzer.py / ai_client.py。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from ... import constants
from ...models import MagnetLink, ParseItem
from ..parser import clean_html
from .base import ModuleMeta, SiteModule

# ---------------------------------------------------------------- 默认值
DEFAULT_MAGNET_RE = r"magnet:\?xt=urn:[a-z0-9]+:[A-Za-z0-9_-]{16,}"
# 同时匹配 YYYY-MM-DD 与 [MM-DD] 两种日期写法
DEFAULT_DATE_RE = r"(\d{4})-(\d{1,2})-(\d{1,2})|\[(\d{1,2})-(\d{1,2})\]"
DEFAULT_EXCLUDE = ("更多", "下一页", "上一页", "尾页", "首页", "返回",
                   "网站地图", "RSS", "收藏本站", "加入收藏", "全选", "登录",
                   "注册", "迅雷", "发帖", "回复", "查看", "版权", "免责",
                   "榜单", "排行榜", "教程", "帮助", "论坛", "联系我们",
                   "公告", "专题", "留言板")
DEFAULT_PAN_RES = ("pan.quark.cn", "aliyundrive.com", "alipan.com",
                   "pan.baidu.com", "drive.uc.cn", "cloud.189.cn",
                   "xunlei.com", "115.com", "weiyun.com")
DEFAULT_ATTACH_RES = ("attach-download", "/download/", "download.php")
DEFAULT_TITLE_QUAL_RE = (
    r"(\d{4}|《|》|1080|720p|4K|BD|HD|WEB|全集|更新至|第\s*\d+\s*集|"
    r"剧场版|加长版|导演剪辑|中英|国语|粤语|国英|双语|中字|字幕)")
_LOOKBACK = 900  # date_anchor 模式向前寻找标题链接的窗口


def _dn_of(url: str) -> str:
    m = re.search(r"[?&]dn=([^&\s]+)", url or "")
    if not m:
        return ""
    from urllib.parse import unquote

    try:
        return unquote(m.group(1)).replace("+", " ")[:80]
    except Exception:
        return m.group(1)[:80]


# ---------------------------------------------------------------- 规则结构
@dataclass
class ExtractRule:
    """列表提取规则。"""

    mode: str = "rows"                    # rows | date_anchor
    row_re: str = ""                      # rows 模式：行容器（整行含开标签）
    link_re: str = ""                     # 详情链接（取第 1 个捕获组）
    title_re: str = ""                    # 标题来源（可选；缺省用链接文字）
    status_re: str = ""                   # 状态标记（可选，如 <i>更新至18集</i>）
    date_re: str = ""                     # 日期（可选；rows 模式限行内）
    block_re: str = ""                    # 标题/标签按钮（可选，就近归区块）
    block_row_re: str = ""                # 行级区块来源（如论坛版块名，优先级最高）
    block_name_map: dict = field(default_factory=dict)  # 名称→区块 label
    block_map: dict = field(default_factory=dict)   # 入口路径→区块
    skip_row_re: str = ""                 # 整行命中则跳过（如非资源版块）
    skip_titles: tuple = DEFAULT_EXCLUDE
    min_title_len: int = 2
    title_qual_re: str = ""               # 标题质量过滤（可选）
    title_status_join: bool = True        # 状态并入标题（用于更新判定）
    alt_complete: bool = False            # 链接文字被截断时用同条目 alt 补全
    red_re: str = constants.RED_RE_STR
    lookback: int = _LOOKBACK


@dataclass
class DetailRule:
    """详情页提取规则。"""

    magnet_re: str = DEFAULT_MAGNET_RE
    pan_res: tuple = DEFAULT_PAN_RES
    attach_res: tuple = DEFAULT_ATTACH_RES
    desc_mode: str = "meta"               # meta | info | text | none


@dataclass
class GenericRule:
    """一条完整的模块规则。"""

    module_id: str = ""
    name: str = ""
    desc: str = ""
    encoding: str = "auto"                # auto | gb18030 | utf-8 ...
    entry_mode: str = "entries"           # entries | mirror
    entry_urls: list = field(default_factory=list)
    max_pages: int = 1
    page_template: str = ""               # 如 {entry}index_{page}.html
    extract: ExtractRule = field(default_factory=ExtractRule)
    detail: DetailRule = field(default_factory=DetailRule)

    # ------------------------------------------------------------ 构造
    @classmethod
    def from_dict(cls, data: dict) -> "GenericRule":
        if not isinstance(data, dict):
            raise ValueError("规则必须是 JSON 对象")
        ex = dict(data.get("extract") or {})
        de = dict(data.get("detail") or {})
        skip = ex.get("skip_titles")
        rule = cls(
            module_id=str(data.get("module_id") or "").strip(),
            name=str(data.get("name") or "").strip(),
            desc=str(data.get("desc") or "").strip(),
            encoding=str(data.get("encoding") or "auto"),
            entry_mode=str(data.get("entry_mode") or "entries"),
            entry_urls=[str(u) for u in (data.get("entry_urls") or []) if u],
            max_pages=int(data.get("max_pages") or 1),
            page_template=str(data.get("page_template") or ""),
            extract=ExtractRule(
                mode=str(ex.get("mode") or "rows"),
                row_re=str(ex.get("row_re") or ""),
                link_re=str(ex.get("link_re") or ""),
                title_re=str(ex.get("title_re") or ""),
                status_re=str(ex.get("status_re") or ""),
                date_re=str(ex.get("date_re") or ""),
                block_re=str(ex.get("block_re") or ""),
                block_row_re=str(ex.get("block_row_re") or ""),
                block_name_map=dict(ex.get("block_name_map") or {}),
                block_map=dict(ex.get("block_map") or {}),
                skip_row_re=str(ex.get("skip_row_re") or ""),
                skip_titles=tuple(skip) if skip else DEFAULT_EXCLUDE,
                min_title_len=int(ex.get("min_title_len") or 2),
                title_qual_re=str(ex.get("title_qual_re") or ""),
                title_status_join=bool(ex.get("title_status_join", True)),
                alt_complete=bool(ex.get("alt_complete", False)),
                red_re=str(ex.get("red_re") or constants.RED_RE_STR),
                lookback=int(ex.get("lookback") or _LOOKBACK),
            ),
            detail=DetailRule(
                magnet_re=str(de.get("magnet_re") or DEFAULT_MAGNET_RE),
                pan_res=tuple(de.get("pan_res") or DEFAULT_PAN_RES),
                attach_res=tuple(de.get("attach_res") or DEFAULT_ATTACH_RES),
                desc_mode=str(de.get("desc_mode") or "meta"),
            ),
        )
        return rule

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "desc": self.desc,
            "encoding": self.encoding,
            "entry_mode": self.entry_mode,
            "entry_urls": list(self.entry_urls),
            "max_pages": self.max_pages,
            "page_template": self.page_template,
            "extract": {
                "mode": self.extract.mode,
                "row_re": self.extract.row_re,
                "link_re": self.extract.link_re,
                "title_re": self.extract.title_re,
                "status_re": self.extract.status_re,
                "date_re": self.extract.date_re,
                "block_re": self.extract.block_re,
                "block_row_re": self.extract.block_row_re,
                "block_name_map": dict(self.extract.block_name_map),
                "block_map": dict(self.extract.block_map),
                "skip_row_re": self.extract.skip_row_re,
                "skip_titles": list(self.extract.skip_titles),
                "min_title_len": self.extract.min_title_len,
                "title_qual_re": self.extract.title_qual_re,
                "title_status_join": self.extract.title_status_join,
                "alt_complete": self.extract.alt_complete,
                "red_re": self.extract.red_re,
                "lookback": self.extract.lookback,
            },
            "detail": {
                "magnet_re": self.detail.magnet_re,
                "pan_res": list(self.detail.pan_res),
                "attach_res": list(self.detail.attach_res),
                "desc_mode": self.detail.desc_mode,
            },
        }


# ---------------------------------------------------------------- 引擎
class GenericModule(SiteModule):
    """规则 JSON 驱动的通用站点模块。"""

    def __init__(self, rule: GenericRule, source: str = ""):
        self.rule = rule
        self.source = source  # 规则来源（builtin 参考 / 用户文件路径）
        self.meta = ModuleMeta(
            module_id=rule.module_id,
            name=rule.name or rule.module_id,
            desc=rule.desc,
            entry_mode=rule.entry_mode or "entries",
            default_entry_urls=tuple(rule.entry_urls),
            builtin=False,
            encoding=rule.encoding,
        )
        self.max_list_pages = max(1, int(rule.max_pages or 1))
        self._compiled = False
        self._row_re = self._link_re = self._title_re = None
        self._status_re = self._date_re = self._block_re = None
        self._skip_row_re = self._qual_re = self._red_re = None
        self._magnet_re = None
        self._anchor_re = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S)
        self._attach_a_re = re.compile(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)

    # ------------------------------------------------------------ 编译
    def _compile(self) -> None:
        if self._compiled:
            return
        ex = self.rule.extract
        flags = re.S | re.I
        self._row_re = re.compile(ex.row_re, flags) if ex.row_re else None
        self._link_re = re.compile(ex.link_re, flags) if ex.link_re else None
        self._title_re = re.compile(ex.title_re, flags) if ex.title_re else None
        self._status_re = (re.compile(ex.status_re, flags)
                           if ex.status_re else None)
        self._date_re = re.compile(ex.date_re, flags) if ex.date_re else None
        self._block_re = re.compile(ex.block_re, flags) if ex.block_re else None
        self._block_row_re = (re.compile(ex.block_row_re, flags)
                              if ex.block_row_re else None)
        self._skip_row_re = (re.compile(ex.skip_row_re, flags)
                             if ex.skip_row_re else None)
        self._qual_re = (re.compile(ex.title_qual_re, flags)
                         if ex.title_qual_re else None)
        self._red_re = re.compile(ex.red_re, flags)
        self._magnet_re = re.compile(self.rule.detail.magnet_re, re.I)
        self._compiled = True

    # ------------------------------------------------------------ 列表
    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        self._compile()
        if self.rule.extract.mode == "date_anchor":
            return self._parse_date_anchor(html, base_url, entry_url)
        return self._parse_rows(html, base_url, entry_url)

    def parse_list_pages(self, html: str, base_url: str, entry_url: str = "",
                         fetcher=None, max_pages: int = 1,
                         include_unknown: bool = True) -> list:
        items = self.parse_list(html, base_url, entry_url, include_unknown)
        tpl = self.rule.page_template
        if fetcher is None or not tpl or max_pages <= 1:
            return items
        seen = {it.detail_url for it in items}
        for page in range(2, max_pages + 1):
            url = tpl.format(entry=(entry_url or base_url).rstrip("/") + "/",
                             page=page)
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
                break
        return items

    # ------------------------------------------------------------ rows 模式
    def _parse_rows(self, html: str, base_url: str, entry_url: str) -> list:
        ex = self.rule.extract
        items: dict = {}
        entry_block = self._entry_block(entry_url)
        headings = self._collect_headings(html)
        for rm in self._row_re.finditer(html or ""):
            row = rm.group(0)
            if self._skip_row_re and self._skip_row_re.search(row):
                continue
            if self._row_excluded(row):
                continue      # 版块名在 block_name_map 中映射为空 = 该版块不收录
            lm = self._link_re.search(row)
            if not lm:
                continue
            href = self._href_of(lm)
            if not self._looks_detail(href):
                continue
            title = self._title_of(row, lm)
            if len(title) < ex.min_title_len:
                continue
            if any(t in title for t in ex.skip_titles):
                continue
            if self._qual_re and not self._qual_re.search(title):
                continue
            detail = urljoin(base_url, href)
            if detail in items:
                continue
            status = self._status_of(row)
            title = self._join_status(title, status)
            items[detail] = ParseItem(
                title=title, date=self._date_in(row), block=self._block_at(
                    rm.start(), headings, entry_block, self._row_block(row)),
                detail_url=detail, is_red=bool(self._red_re.search(row)),
                is_classic=("经典" in title))
        return list(items.values())

    # ------------------------------------------------------------ 日期锚点模式
    def _parse_date_anchor(self, html: str, base_url: str,
                           entry_url: str) -> list:
        ex = self.rule.extract
        items: dict = {}
        entry_block = self._entry_block(entry_url)
        headings = self._collect_headings(html)
        date_re = self._date_re or re.compile(DEFAULT_DATE_RE, re.S | re.I)
        for dm in date_re.finditer(html or ""):
            pos = dm.start()
            date = _norm_date(dm)
            hit = self._nearest_link(html, pos)
            if not hit:
                continue
            href, title, link_pos = hit
            if len(title) < ex.min_title_len or any(
                    t in title for t in ex.skip_titles):
                continue
            if self._qual_re and not self._qual_re.search(title):
                continue
            detail = urljoin(base_url, href)
            if detail in items:
                continue
            seg = html[link_pos:pos]
            items[detail] = ParseItem(
                title=title, date=date, block=self._block_at(
                    pos, headings, entry_block),
                detail_url=detail,
                is_red=bool(self._red_re.search(seg)),
                is_classic=("经典" in title))
        return list(items.values())

    def _nearest_link(self, html: str, pos: int):
        """日期位置向前窗口中最后一个有效标题链接。"""
        ex = self.rule.extract
        start = max(0, pos - ex.lookback)
        head = html[start:pos]
        best = None
        for lm in self._link_re.finditer(head):
            href = self._href_of(lm)
            if not self._looks_detail(href):
                continue
            title = self._title_of(head, lm)
            if len(title) < ex.min_title_len:
                continue
            if any(t in title for t in ex.skip_titles):
                continue
            best = (href, title, start + lm.start())
        if not best:
            return None
        href, title, link_pos = best
        if ex.alt_complete:
            title = _alt_complete(html[start:pos], title, link_pos - start)
        return href, title, link_pos

    # ------------------------------------------------------------ 详情
    def parse_detail(self, html: str, item: ParseItem) -> None:
        self._compile()
        d = self.rule.detail
        out: list = []
        seen: set = set()

        def _add(label: str, url: str, kind: str) -> None:
            url = (url or "").strip()
            if not url or url in seen:
                return
            seen.add(url)
            out.append(MagnetLink(label=(label or url)[:80], url=url, kind=kind))

        for m in self._magnet_re.finditer(html or ""):
            url = m.group(0)
            _add(_dn_of(url) or url[:60], url, "magnet")
        base = item.detail_url or ""
        for m in self._attach_a_re.finditer(html or ""):
            href = m.group(1).strip()
            text = clean_html(m.group(2))
            low = href.lower()
            if any(r in low for r in d.attach_res):
                url = urljoin(base, href)
                kind = ("torrent"
                        if ".torrent" in (text + " " + url).lower() else "pan")
                _add(text or url.rsplit("/", 1)[-1], url, kind)
            elif any(r in href for r in d.pan_res):
                _add(text or "网盘链接", href, "pan")
        item.magnets = out
        if not item.desc:
            item.desc = self._desc(html)

    def _desc(self, html: str) -> str:
        mode = self.rule.detail.desc_mode
        if mode == "none":
            return ""
        from ..parser import parse_detail_desc

        if mode == "info":
            text = clean_html(html or "")[:6000]
            i = text.find("◎")
            if i >= 0:
                seg = text[i:i + 420].strip()
                if seg:
                    return seg[:420]
            return parse_detail_desc(html)
        if mode == "text":
            return clean_html(html or "")[:220]
        return parse_detail_desc(html)

    # ------------------------------------------------------------ 工具
    def _href_of(self, m) -> str:
        href = m.group(1) if m.groups() else m.group(0)
        return (href or "").strip().strip("\"'")

    def _looks_detail(self, href: str) -> bool:
        low = (href or "").lower()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return False
        return (low.endswith((".htm", ".html"))
                or ".htm?" in low or ".html?" in low
                or "thread-" in low or re.search(r"/\d{3,}", low))

    def _title_of(self, row: str, lm) -> str:
        ex = self.rule.extract
        if self._title_re:
            # 规则指定了标题来源：没匹配到（或为空）视为无效行，不兜底
            tm = self._title_re.search(row)
            if tm:
                title = clean_html(tm.group(1) if tm.groups() else tm.group(0))
                if title:
                    return _clean_title(title)
            return ""
        # 未指定 title_re：用链接文字兜底
        title = ""
        am = self._anchor_re.search(row, max(0, lm.start() - 200))
        if am:
            title = clean_html(am.group(1))
        if not title:
            end = row.find("</a>", lm.end())
            if end > 0:
                title = clean_html(row[lm.end():end])
        return _clean_title(title)

    def _status_of(self, row: str) -> str:
        if not self._status_re:
            return ""
        m = self._status_re.search(row)
        if not m:
            return ""
        return clean_html(m.group(1) if m.groups() else m.group(0))

    def _join_status(self, title: str, status: str) -> str:
        ex = self.rule.extract
        if ex.title_status_join and status and status != "正片":
            return f"{title}（{status}）"
        return title

    def _date_in(self, row: str) -> str:
        if not self._date_re:
            return ""
        m = self._date_re.search(row)
        return _norm_date(m) if m else ""

    def _entry_block(self, entry_url: str) -> str:
        path = urlparse(entry_url or "").path or "/"
        best, best_len = "", 0
        for prefix, label in (self.rule.extract.block_map or {}).items():
            if prefix and prefix in path and len(prefix) > best_len:
                best, best_len = label, len(prefix)
        return best

    def _row_block_name(self, row: str) -> str:
        """行级版块名（如论坛每行自带版块名），无则返回空串。"""
        if not self._block_row_re:
            return ""
        m = self._block_row_re.search(row)
        if not m:
            return ""
        name = next((g for g in reversed(m.groups()) if g), "")
        return clean_html(name)

    def _row_excluded(self, row: str) -> bool:
        """版块名在 block_name_map 中显式映射为空 → 该行不收录（如站务公告）。"""
        name = self._row_block_name(row)
        if not name:
            return False
        name_map = self.rule.extract.block_name_map or {}
        return name in name_map and not name_map[name]

    def _row_block(self, row: str) -> str:
        """行级区块（优先级最高）：如论坛每行自带版块名。"""
        name = self._row_block_name(row)
        if not name:
            return ""
        name_map = self.rule.extract.block_name_map or {}
        if name in name_map:
            return name_map[name]
        return (tab_block_label(name)
                or block_label_for_heading(name) or "")

    def _collect_headings(self, html: str) -> list:
        """标题/标签按钮边界：[(位置, 区块 label)]。

        标题文字取“最后一个非空捕获组”——这样规则可以把编号组放前面
        （如 tab(\\d+)_btn_(\\d+) 后面跟名称组），名称组始终在最后。
        """
        if not self._block_re:
            return []
        out = []
        for m in self._block_re.finditer(html or ""):
            raw = next((g for g in reversed(m.groups()) if g), "")
            label = tab_block_label(raw)
            if not label:
                label = block_label_for_heading(clean_html(raw))
            if label:
                out.append((m.start(), label))
        out.sort(key=lambda x: x[0])
        return out

    def _block_at(self, pos: int, headings: list, entry_block: str,
                  row_block: str = "") -> str:
        if row_block:
            return row_block  # 行级区块优先级最高
        label = entry_block
        for hpos, hlab in headings:
            if hpos <= pos:
                label = hlab
            else:
                break
        return label or "其他"


# ---------------------------------------------------------------- 模块级工具
def _clean_title(title: str) -> str:
    title = re.sub(r"^【[^】]*】\s*", "", title or "").strip()
    title = re.sub(r"^[\[\(]?\d{1,2}-\d{1,2}[\]\)]?\s*", "", title).strip()
    return title.strip()


def _norm_date(m) -> str:
    """归一化日期：优先 YYYY-MM-DD 组，其次 [MM-DD] 组，最后全文兜底。"""
    groups = m.groups()
    n = len(groups)
    if n >= 3 and groups[0]:
        return f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
    if n >= 5 and groups[3]:
        return f"{int(groups[3]):02d}-{int(groups[4]):02d}"
    if n == 1 and groups[0]:
        return clean_date_text(groups[0])
    return clean_date_text(m.group(0))


def clean_date_text(text: str) -> str:
    """任意日期文本 → YYYY-MM-DD 或 MM-DD（无法识别返回空串）。"""
    text = text or ""
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"\[?(\d{1,2})-(\d{1,2})\]?", text)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def _alt_complete(head: str, title: str, anchor_off: int) -> str:
    """链接文字被站点截断时，用同条目内以其为前缀的 alt 补全。"""
    if not title:
        return title
    best = ""
    for m in re.finditer(r"alt\s*=\s*[\"']([^\"']+)[\"']", head, re.I):
        alt = clean_html(m.group(1))
        if m.start() <= anchor_off and len(alt) > len(title) \
                and alt.startswith(title):
            best = alt
    return best or title


# 延迟导入避免环
from ..parser import block_label_for_heading, tab_block_label  # noqa: E402
