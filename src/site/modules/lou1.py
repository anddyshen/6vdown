"""BT之家 1lou.me 论坛模块（Xiuno BBS · utf-8）。

实测结构：
- 版块页：``forum-N.htm``（N=版块 fid），分页 ``forum-N-P.htm``；
  版块 fid：1 最新电影 / 2 电视剧集 / 3 高清电影 / 4 高清剧集 /
            13 网盘电影 / 14 网盘剧集 / 17 动漫专区 / 10 纪录综艺；
  游戏/音乐/图书/美图/交流/站务/求助等非资源版块在解析时直接跳过；
- 列表行：``<li class="media thread ..." data-href="thread-XXXXX.htm">`` 内含
  标题 ``<a ... class="text-title">``、版块 ``<a href="forum-N.htm" title="版块名">``、
  日期 ``<span class="date ...">YYYY-MM-DD HH:MM</span>``；
  同一帖子会渲染桌面/移动两套模板 → 按详情 URL 去重；
- 帖子页：``thread-XXXXX.htm``，正文 ``<div class="message break-all">``（◎ 简介）。
  资源分三类提取：
    ① 磁力（正文文本，通用正则）→ 可发送；
    ② 附件（Xiuno ``attach-download`` 链接）→ .torrent 可发送，其它仅复制；
    ③ 网盘链接（夸克/阿里/百度/UC/天翼/迅雷）→ 仅展示+复制。
  注意：部分帖子的下载链接需登录/回复后可见，游客端解析不到（会在简介中标注）。
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin

from ...models import MagnetLink, ParseItem
from ..netdisk import extract_pan_links, is_netdisk_url
from ..parser import clean_html
from .base import ModuleMeta, SearchSpec, SiteModule, root_url

# 版块名 → 区块 label
_FORUM_BLOCKS = {
    "最新电影": "最新电影",
    "高清电影": "最新电影",
    "网盘电影": "最新电影",
    "电视剧集": "更新电视剧",
    "高清剧集": "更新电视剧",
    "网盘剧集": "更新电视剧",
    "国剧": "国剧",
    "国产剧": "国剧",
    "日韩剧": "日韩剧",
    "韩剧": "日韩剧",
    "日剧": "日韩剧",
    "欧美剧": "美剧",
    "美剧": "美剧",
    "动漫": "动画",
    "动漫专区": "动画",
    "动画": "动画",
    "短剧": "短剧",
    "纪录综艺": "综艺",
    "综艺": "综艺",
}

# 非资源版块：直接跳过（含各版块页顶部的置顶公告）
_SKIP_FORUMS = {
    "站务专区", "交流专区", "求助专区", "新美图区", "游戏专区",
    "音乐专区", "图书专区",
}

# fid → 区块 label（搜索接口返回的是 fid，不是版块名）
_FID_BLOCKS = {
    1: "最新电影", 3: "最新电影", 13: "最新电影",
    2: "更新电视剧", 4: "更新电视剧", 14: "更新电视剧",
    17: "动画", 10: "综艺",
}

# 搜索接口（前端 SPA /search/assets/app.js 实际调用）：
#   GET {root}search/api/search.php?q=<关键词>&fid=0&page=<n>
# 返回 JSON：{"ok":true,"data":{"total":N,"page":n,"page_size":50,
#             "hits":[{"tid","fid","subject","username","create_date",
#                      "views","posts","files","thread_url"}]}}
_SEARCH_API = "search/api/search.php"
_DEFAULT_ROOT = "https://www.1lou.me/"
# 网盘版块 fid：全站搜索结果按时间排序，普通种子帖会挤满前面几页，
# 网盘帖常落到上限之外 → 额外按这两个版块补搜一次
_PAN_FIDS = (13, 14)   # 13 网盘电影 / 14 网盘剧集

_LI_RE = re.compile(
    r'<li class="media thread[^"]*"[^>]*data-href="(thread-\d+\.htm)"(.*?)</li>',
    re.S)
_TITLE_RE = re.compile(
    r'<a href="thread-\d+\.htm"[^>]*class="text-title"[^>]*>(.*?)</a>', re.S)
_FORUM_RE = re.compile(
    r'<a href="forum-(\d+)\.htm"[^>]*title="([^"]*)"', re.I)
_DATE_RE = re.compile(
    r'<span class="date[^"]*"[^>]*>\s*(\d{4}-\d{1,2}-\d{1,2})', re.I)

# 帖子正文资源
_ATTACH_A_RE = re.compile(
    r'<a\b[^>]*href=["\']?([^"\' >]*(?:attach-download|/download/|download\.php|\.torrent)[^"\' >]*)["\']?'
    r'[^>]*>(.*?)</a>', re.S | re.I)
# 网盘域名与提取码识别统一维护在 src/site/netdisk.py（各站共用）
_MESSAGE_RE = re.compile(
    r'<div class="message break-all"[^>]*>(.*)$', re.S)


class Lou1Module(SiteModule):
    """BT之家 1LOU 站（Xiuno BBS 论坛）。"""

    max_list_pages = 1  # 论坛更新慢，单页 40+ 帖足够；避免对论坛站过度请求

    # 搜索：站点搜索页是前端 SPA，实际调用 JSON 接口（见 _SEARCH_API）
    supports_search = True
    max_search_pages = 1
    search_result_limit = 80

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="lou1",
            name="BT之家 1LOU（1lou.me）",
            desc=("Xiuno BBS 论坛；版块页入口；磁力/种子附件可发送，"
                  "网盘仅复制；支持站内搜索（JSON 接口）"),
            entry_mode="entries",
            encoding="utf-8",
            default_entry_urls=(
                "https://www.1lou.me/forum-1.htm",   # 最新电影
                "https://www.1lou.me/forum-3.htm",   # 高清电影
                "https://www.1lou.me/forum-13.htm",  # 网盘电影
                "https://www.1lou.me/forum-2.htm",   # 电视剧集
                "https://www.1lou.me/forum-4.htm",   # 高清剧集
                "https://www.1lou.me/forum-14.htm",  # 网盘剧集
                "https://www.1lou.me/forum-17.htm",  # 动漫专区
                "https://www.1lou.me/forum-10.htm",  # 纪录综艺
            ),
        )

    # ------------------------------------------------------------ 列表
    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        return parse_list(html, base_url)

    # ------------------------------------------------------------ 详情
    # ------------------------------------------------------------ 搜索
    def search_spec(self, keyword: str, page: int = 1,
                    base: str = "") -> SearchSpec:
        root = root_url(base, _DEFAULT_ROOT)
        return SearchSpec(
            url=urljoin(root, _SEARCH_API), method="GET",
            data={"q": keyword, "fid": "0", "page": str(page)},
            encoding="utf-8", referer=root + "search/", base=root)

    def parse_search(self, text: str, base_url: str) -> list:
        """搜索接口返回 JSON（非 HTML），按 tid 去重 → list[ParseItem]。"""
        return parse_search_json(text, base_url)

    def search(self, keyword, fetcher, max_pages=None, base="",
               polite_delay=0.0, log_cb=None, cancel=None,
               page_html=None) -> list:
        """全站搜索 + 网盘版块补搜（fid=13/14），网盘条目排在最前。

        1LOU 的全站搜索按时间倒序，普通电影/剧集帖数量远多于网盘帖，
        网盘帖经常落在第 2 页之后甚至上限之外 → 只搜全站时“搜不到网盘”，
        故再按网盘版块各补搜一页；后续 union 时网盘帖置前，
        让“自动解析详情”优先抓到网盘链接。
        """
        items = super().search(
            keyword, fetcher, max_pages=max_pages, base=base,
            polite_delay=polite_delay, log_cb=log_cb, cancel=cancel,
            page_html=page_html)
        kw = (keyword or "").strip()
        if not kw or (cancel and cancel()):
            return _pan_first(items)
        root = root_url(base, _DEFAULT_ROOT)
        seen = {it.detail_url for it in items if it.detail_url}
        for fid in _PAN_FIDS:
            if cancel and cancel():
                break
            spec = SearchSpec(
                url=urljoin(root, _SEARCH_API), method="GET",
                data={"q": kw, "fid": str(fid), "page": "1"},
                encoding="utf-8", referer=root + "search/", base=root)
            try:
                text, _ = self._request_search(fetcher, spec)
            except Exception as e:
                if log_cb:
                    log_cb(f"[搜索] “{kw}” 网盘版块 fid={fid} 请求失败："
                           f"{type(e).__name__}: {e}")
                continue
            got = self.parse_search(text or "", spec.base or root)
            new = [it for it in got
                   if it.detail_url and it.detail_url not in seen]
            for it in new:
                seen.add(it.detail_url)
            items.extend(new)
            if log_cb:
                log_cb(f"[搜索] “{kw}” 网盘版块 fid={fid}：新增 {len(new)} 条")
            if polite_delay > 0:
                time.sleep(min(polite_delay, 1.5))
        return _pan_first(items)

    def parse_detail(self, html: str, item: ParseItem) -> None:
        item.magnets = extract_resources(html, item.detail_url or "",
                                         item.title or "")
        if not item.desc:
            item.desc = extract_desc(html)
        if not item.magnets and not item.desc:
            item.desc = _hidden_note(html)


# ---------------------------------------------------------------- 列表解析
def parse_list(html: str, base_url: str) -> list:
    """版块页 → list[ParseItem]（按详情 URL 去重，跳过非资源版块）。"""
    items: dict = {}
    for lm in _LI_RE.finditer(html or ""):
        href, inner = lm.group(1), lm.group(2)
        tm = _TITLE_RE.search(inner)
        if not tm:
            continue
        title = clean_html(tm.group(1))
        title = re.sub(r"^【[^】]*】\s*", "", title).strip()  # 去掉【日期】前缀
        if len(title) < 2:
            continue
        fm = _FORUM_RE.search(inner)
        forum = clean_html(fm.group(2)) if fm else ""
        if forum in _SKIP_FORUMS:
            continue  # 置顶公告等非资源帖
        block = _FORUM_BLOCKS.get(forum, "其他")
        dm = _DATE_RE.search(inner)
        date = dm.group(1) if dm else ""
        detail = urljoin(base_url, href)
        if detail in items:
            continue
        items[detail] = ParseItem(
            title=title, date=date, block=block, detail_url=detail,
            is_classic=("经典" in title))
    return list(items.values())


# ---------------------------------------------------------------- 搜索解析
def parse_search_json(text: str, base_url: str) -> list:
    """搜索接口 JSON → list[ParseItem]（按帖子 URL 去重）。

    hits[] 字段：tid / fid / subject / highlighted_subject / username /
                 create_date(Unix 秒) / views / posts / files / thread_url。
    """
    try:
        payload = json.loads(text or "")
    except Exception:
        return []
    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    data = payload.get("data") or {}
    items: dict = {}
    for hit in (data.get("hits") or []):
        if not isinstance(hit, dict):
            continue
        href = str(hit.get("thread_url") or "").strip()
        if not href:
            continue
        detail = urljoin(base_url, href)
        if detail in items:
            continue
        title = re.sub(r"^【[^】]*】\s*", "",
                       clean_html(str(hit.get("subject") or ""))).strip()
        if len(title) < 2:
            continue
        date = ""
        try:
            ts = int(hit.get("create_date") or 0)
            if ts > 0:
                date = time.strftime("%Y-%m-%d", time.localtime(ts))
        except (TypeError, ValueError):
            date = ""
        items[detail] = ParseItem(
            title=title, date=date,
            block=_FID_BLOCKS.get(hit.get("fid"), "其他"),
            detail_url=detail)
    return list(items.values())


def _pan_first(items: list) -> list:
    """网盘标记条目排前面（稳定排序，其余保持原顺序）。"""
    from ..netdisk import looks_pan_title

    return sorted(items, key=lambda it: 0 if looks_pan_title(
        getattr(it, "title", "")) else 1)


# ---------------------------------------------------------------- 详情解析
# 网盘关键词（链接文字或标题里出现即判定为网盘资源）
_PAN_WORDS = ("夸克", "阿里", "百度", "UC", "uc", "天翼", "迅雷", "115",
              "微云", "网盘", "中国移动", "移动云盘", "和彩云")
# 明确不是种子的附件扩展名（图片 / 压缩包 / 视频等）→ 仅复制
_OTHER_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico",
              ".rar", ".zip", ".7z", ".mp4", ".mkv", ".avi", ".rmvb",
              ".txt", ".pdf", ".nfo", ".srt", ".ass")


def classify_attach(name: str, url: str, title: str = "") -> str:
    """判定附件/链接的资源类型：torrent（可发送）或 pan（仅复制）。

    - 链接文字/URL 外链到网盘域名，或含网盘关键词 → pan（仅复制）；
    - 含 ``.torrent`` → torrent（可发送）；
    - 含其它明确扩展名（图片/压缩包/视频等）→ pan（仅复制）；
    - 站内附件无后缀（Xiuno 的 attach-download-*）→ torrent，
      1LOU 这类附件点击即下载 .torrent，属于可发送资源。
    """
    low = ((name or "") + " " + (url or "")).lower()
    if is_netdisk_url(url):
        return "pan"
    if ".torrent" in low:
        return "torrent"
    if any(ext in low for ext in _OTHER_EXT):
        return "pan"
    for w in _PAN_WORDS:
        if w in (name or "") or w in (title or ""):
            return "pan"
    return "torrent"


def _message_scope(html: str) -> str:
    """截取帖子正文 div（按嵌套 div 配对），避免把页脚/导航链接当资源。"""
    m = _MESSAGE_RE.search(html or "")
    if not m:
        return html or ""
    start = m.start(1)
    depth = 0
    for mm in re.finditer(r"<div\b|</div>", html[start:]):
        if mm.group(0).lower() == "</div>":
            if depth == 0:
                return html[start:start + mm.start()]
            depth -= 1
        else:
            depth += 1
    return html[start:]


def extract_resources(html: str, base_url: str, title: str = "") -> list:
    """帖子正文 → 磁力 + 附件 + 网盘（按 URL 去重，保持出现顺序）。"""
    out: list = []
    seen: set = set()

    def _add(label: str, url: str, kind: str) -> None:
        url = (url or "").strip()
        if not url or url in seen:
            return
        seen.add(url)
        out.append(MagnetLink(label=label[:80], url=url, kind=kind))

    from ..parser import parse_detail_magnets

    scope = _message_scope(html or "")
    for ml in parse_detail_magnets(scope):
        _add(ml.label, ml.url, "magnet")
    # Xiuno 附件（attach-download-*.htm / .torrent）在页面中多位于帖子正文下方
    # 或附件列表 <ul class="attachlist">，在此对全文进行扫描提取
    for m in _ATTACH_A_RE.finditer(html or ""):
        url = urljoin(base_url, m.group(1).strip())
        name = clean_html(m.group(2)).strip()
        if not name or len(name) < 2 or name in ("下载附件", "附件", "下载", "点击下载"):
            after_text = (html or "")[m.end():m.end() + 200]
            m_fn = re.search(r'([^\s<>"\']+\.torrent)', after_text, re.I)
            if not m_fn:
                before_text = (html or "")[max(0, m.start() - 150):m.start()]
                m_fn = re.search(r'([^\s<>"\']+\.torrent)', before_text, re.I)
            name = m_fn.group(1).strip() if m_fn else (name or url.rsplit("/", 1)[-1])
        # Xiuno 附件 URL 形如 attach-download-3000427.htm，不带后缀；
        # 1LOU 的附件绝大多数就是 .torrent 种子（点击即下载），故默认按
        # 种子处理（可发送）；仅当链接文字/标题明确指向网盘时才归为 pan。
        _add(name, url, classify_attach(name, url, title))
    # 正文里的网盘地址（<a> 链接与纯文本都覆盖；URL 未带 pwd 时补正文提取码）
    for ml in extract_pan_links(scope):
        _add(ml.label, ml.url, "pan")
    return out


def extract_desc(html: str) -> str:
    """正文简介：优先 ◎ 信息块，其次 message 正文前段。"""
    mm = _MESSAGE_RE.search(html or "")
    if mm:
        text = clean_html(mm.group(1)[:6000])
        i = text.find("◎")
        if i >= 0:
            seg = text[i:i + 420].strip()
            if seg:
                return seg[:420]
        seg = text[:220].strip()
        if seg:
            return seg[:220]
    from ..parser import parse_detail_desc

    return parse_detail_desc(html)


def _hidden_note(html: str) -> str:
    """未解析到资源时，识别“登录/回复后可见”并在简介中标注。"""
    text = clean_html(html or "")[:20000]
    if ("回复" in text and "可见" in text) or "登录后" in text:
        return "该帖下载链接需登录/回复后可见（游客端无法解析）"
    return ""
