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

import re
from urllib.parse import urljoin

from ...models import MagnetLink, ParseItem
from ..parser import clean_html
from .base import ModuleMeta, SiteModule

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
    r'<a\b[^>]*href="([^"]*(?:attach-download|/download/|download\.php)[^"]*)"'
    r'[^>]*>(.*?)</a>', re.S | re.I)
_PAN_A_RE = re.compile(
    r'<a\b[^>]*href="(https?://[^"]*(?:pan\.quark\.cn|aliyundrive\.com|'
    r'alipan\.com|pan\.baidu\.com|drive\.uc\.cn|cloud\.189\.cn|'
    r'xunlei\.com|115\.com|weiyun\.com)[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_MESSAGE_RE = re.compile(
    r'<div class="message break-all"[^>]*>(.*)$', re.S)


class Lou1Module(SiteModule):
    """BT之家 1LOU 站（Xiuno BBS 论坛）。"""

    max_list_pages = 1  # 论坛更新慢，单页 40+ 帖足够；避免对论坛站过度请求

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="lou1",
            name="BT之家 1LOU（1lou.me）",
            desc="Xiuno BBS 论坛；版块页入口；磁力/种子附件可发送，网盘仅复制",
            entry_mode="entries",
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
    def parse_detail(self, html: str, item: ParseItem) -> None:
        item.magnets = extract_resources(html, item.detail_url or "")
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


# ---------------------------------------------------------------- 详情解析
def extract_resources(html: str, base_url: str) -> list:
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

    for ml in parse_detail_magnets(html or ""):
        _add(ml.label, ml.url, "magnet")
    for m in _ATTACH_A_RE.finditer(html or ""):
        url = urljoin(base_url, m.group(1).strip())
        name = clean_html(m.group(2)) or url.rsplit("/", 1)[-1]
        # Xiuno 附件 URL 不带后缀，按文件名/URL 判断是否种子
        kind = "torrent" if ".torrent" in (name + " " + url).lower() else "pan"
        _add(name, url, kind)
    for m in _PAN_A_RE.finditer(html or ""):
        url = m.group(1).strip()
        name = clean_html(m.group(2)) or "网盘链接"
        _add(name, url, "pan")
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
