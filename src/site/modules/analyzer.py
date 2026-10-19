"""本地规则推导（AutoProfile）：输入 URL → 结构探测 → 候选规则 → 详情验证。

不依赖 AI、零外部服务，永远可用。流程：
  1) 抓入口页，探测“详情链接模式”（后缀统计 + 论坛/CMS 特定标记优先）；
  2) 探测行容器（含详情链接的重复 tag+class 签名；无 class 时退回裸标签）；
  3) 探测标题来源（title 属性 / 子元素 / 各 class 的链接文字）→ 取最完整且更干净的；
  4) 探测日期作用域（行内 → rows 模式；行外 → date_anchor 模式）、状态标记；
  5) 探测区块来源（tab 按钮 / 标题 / 论坛版块名 / 导航路径映射）；
  6) 用 generic 引擎试解析，条目过少则记录告警；
  7) 抓 1-3 个详情页验证磁力/附件/网盘提取率，产出置信度报告。

产出规则 dict 可直接交给 generic 引擎或保存为 data/modules/<id>.json。
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from ..parser import clean_html
from .generic import GenericModule, GenericRule
from .rule_store import validate_rule

# ---------------------------------------------------------------- 探测正则
_DATE_PROBES = (
    ("ymd", r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    ("md", r"\[(\d{1,2})-(\d{1,2})\]"),
    ("cn", r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    ("slash", r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)"),
)
# 引擎可识别的日期正则（分组布局与 generic._norm_date 对应）
_ENGINE_DATE_RE = r"(\d{4})-(\d{1,2})-(\d{1,2})|\[(\d{1,2})-(\d{1,2})\]"

_TAG_OPEN_RE = re.compile(
    r"<(li|div|tr|article|section|dd|dl)\b([^>]*)>", re.I)
_CLASS_RE = re.compile(r"class\s*=\s*[\"']([^\"']+)[\"']", re.I)
_A_HREF_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_DATA_HREF_RE = re.compile(r"data-href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_STATIC_EXT = (".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".ico",
               ".svg", ".woff", ".ttf")

# 详情页链接常见标记（优先级从高到低；命中数达标即优先于后缀规则）
_LINK_MARKERS = ("thread-", "tid=", "read-", "show-", "view-", "article-",
                 "post-", "bbs-", "topic-", "thread", "forumdisplay")
# 行容器标签优先级：列表项最像“行”，div 最容易误命中布局容器
_TAG_RANK = {"li": 3, "article": 3, "tr": 2, "dd": 2, "div": 1, "section": 1}
# 裸标签兜底只用列表项：tr/dd 在 table 布局站（如电影港老模板）会误命中
_PLAIN_TAGS = ("li", "article")

_TITLE_ATTR_RE = r"title\s*=\s*[\"']([^\"']{2,160})[\"']"
_TITLE_NAME_RE = r"<p class=\"name\">(.*?)</p>"
_STATUS_CANDIDATES = (
    r"<p class=\"other\">\s*<i>([^<]+)</i>",
    r"<i[^>]*class=\"[^\"]*(?:status|state|flag|bz)[^\"]*\"[^>]*>([^<]+)</i>",
    r"<em[^>]*>([^<]{1,12})</em>",
    r"<span class=\"[^\"]*(?:status|state|flag|jishi)[^\"]*\"[^>]*>([^<]+)</span>",
)
_HEADING_RE = re.compile(r"<h([1-4])[^>]*>(.*?)</h\1>", re.S | re.I)
_TAB_BTN_RE = re.compile(r"<li[^>]*id=\"tab\d+_btn_\d+\"[^>]*>(.*?)</li>", re.S | re.I)
_H_RE_STR = r"<h([1-4])[^>]*>(.*?)</h\1>"
_TAB_RE_STR = (r"<li[^>]*id=\"tab(\d+)_btn_(\d+)\"[^>]*>(.*?)</li>")
_FORUM_LINK_RE = re.compile(
    r"<a href=\"(forum-\d+[^\"]*)\"[^>]*title=\"([^\"]+)\"", re.I)
_NAV_LINK_RE = re.compile(
    r"<a[^>]*href=\"(/[A-Za-z0-9_-]{1,20}/?)\"[^>]*>([^<]{2,12})</a>", re.I)

# 版块/导航文字 → 统一区块 label（自动推导专用别名表；
# 覆盖“站点简写名”这类 tab_block_label 匹配不到的情况）
_BLOCK_ALIASES = {
    "电影": "最新电影", "最新电影": "最新电影", "高清电影": "最新电影",
    "网盘电影": "最新电影", "电影下载": "最新电影", "动作片": "最新电影",
    "喜剧片": "最新电影", "爱情片": "最新电影", "科幻片": "最新电影",
    "恐怖片": "最新电影", "战争片": "最新电影", "剧情片": "最新电影",
    "电视剧": "更新电视剧", "电视剧集": "更新电视剧", "剧集": "更新电视剧",
    "最新电视剧": "更新电视剧", "高清剧集": "更新电视剧",
    "网盘剧集": "更新电视剧", "国产电视剧": "更新电视剧",
    "国剧": "国剧", "国产剧": "国剧", "大陆剧": "国剧",
    "日韩剧": "日韩剧", "日剧": "日韩剧", "韩剧": "日韩剧",
    "美剧": "美剧", "欧美剧": "美剧", "欧美": "美剧",
    "动画": "动画", "动漫": "动画", "动画片": "动画", "动漫专区": "动画",
    "综艺": "综艺", "纪录片": "综艺", "纪录综艺": "综艺",
    "短剧": "短剧",
    "经典": "经典高清", "经典高清": "经典高清", "经典电影": "经典高清",
}


def _esc(s: str) -> str:
    return re.escape(s)


def _norm(s: str) -> str:
    """去空白，用于“前缀”比较。"""
    return re.sub(r"\s+", "", s or "")


def _slug(url: str) -> str:
    host = urlparse(url or "").netloc.replace(":", "_")
    slug = re.sub(r"[^a-z0-9]+", "_", host.lower()).strip("_")
    return slug or "site"


# ---------------------------------------------------------------- 探测函数
def detect_link_pattern(html: str) -> str:
    """详情链接模式：特定标记优先，其次按后缀统计，生成 link_re。"""
    hrefs = _A_HREF_RE.findall(html or "") + _DATA_HREF_RE.findall(html or "")
    detail = []
    for h in hrefs:
        low = (h or "").lower()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if low.endswith(_STATIC_EXT):
            continue
        if (low.endswith((".htm", ".html")) or "thread-" in low
                or re.search(r"/\d{3,}", low)):
            detail.append(h)
    if not detail:
        return ""
    # 1) 论坛/CMS 详情链接常带特定标记（thread-/tid=/read- …），优先于后缀
    for marker in _LINK_MARKERS:
        hits = {h for h in detail if marker in h.lower()}
        if len(hits) >= 3:
            return '<a[^>]*href="([^"]*' + marker + '[^"]*)"'
    # 2) 后缀统计
    suf: dict = {}
    for h in detail:
        low = h.lower()
        if low.endswith(".html"):
            suf[".html"] = suf.get(".html", 0) + 1
        elif low.endswith(".htm"):
            suf[".htm"] = suf.get(".htm", 0) + 1
        else:
            suf["id"] = suf.get("id", 0) + 1
    best = max(suf, key=lambda k: suf[k])
    if best in (".html", ".htm"):
        ext = best.lstrip(".")
        return '<a[^>]*href="([^"]+\\.' + ext + ')"'
    return "<a[^>]*href=\"([^\"]*(?:/\\d{3,}|\\?id=\\d+)[^\"]*)\""


def detect_row_candidates(html: str, link_re: str) -> list:
    """行容器候选：[(row_re, 含链接行数, 总出现次数)]。

    排序：标签优先级（li/article > tr/dd > div）→ 含链接行数 → 出现次数。
    div 最容易误命中布局容器，因此排在列表项之后。
    """
    if not link_re or not html:
        return []
    try:
        link = re.compile(link_re, re.I | re.S)
    except re.error:
        return []
    counts: dict = {}
    for m in _TAG_OPEN_RE.finditer(html):
        cm = _CLASS_RE.search(m.group(2) or "")
        if not cm:
            continue
        cls = (cm.group(1) or "").strip()
        if not cls or len(cls) > 90:
            continue
        key = (m.group(1).lower(), cls)
        counts[key] = counts.get(key, 0) + 1
    out = []
    for (tag, cls), total in counts.items():
        if total < 3:
            continue
        row_re = (f"<{tag}[^>]*class=\"[^\"]*{_esc(cls)}[^\"]*\"[^>]*>.*?</{tag}>")
        rows = _iter_rows(html, row_re)
        if not rows:
            continue
        with_link = sum(1 for r in rows if link.search(r))
        if with_link < max(2, total // 2):
            continue
        out.append((row_re, with_link, total, _TAG_RANK.get(tag, 1)))
    if not out:
        # 无 class 型容器（老模板常见裸 <li>）→ 退回裸标签
        for tag in _PLAIN_TAGS:
            row_re = f"<{tag}[^>]*>.*?</{tag}>"
            rows = _iter_rows(html, row_re)
            if len(rows) < 3:
                continue
            with_link = sum(1 for r in rows if link.search(r))
            if with_link < 2:
                continue
            out.append((row_re, with_link, len(rows), _TAG_RANK.get(tag, 1)))
    out.sort(key=lambda x: (-x[3], -x[1], -x[2]))
    return [(r, w, t) for r, w, t, _ in out]


def _iter_rows(html: str, row_re: str, limit: int = 200) -> list:
    try:
        return [m.group(0) for m in
                re.finditer(row_re, html, re.S | re.I)][:limit]
    except re.error:
        return []


def sample_rows(html: str, row_re: str, limit: int = 40) -> list:
    if not row_re or not html:
        return []
    return _iter_rows(html, row_re, limit)


def _measure(rows: list, pattern: str):
    """在样例行上评估某个标题模式。返回 (覆盖率, 平均长度, {行号: 文本})。"""
    try:
        rx = re.compile(pattern, re.I | re.S)
    except re.error:
        return None
    found: dict = {}
    for i, r in enumerate(rows):
        m = rx.search(r)
        if not m:
            continue
        raw = m.group(1) if m.groups() else m.group(0)
        t = re.sub(r"<[^>]+>", "", raw or "").strip()
        if t:
            found[i] = t
    if not found:
        return None
    avg = sum(len(t) for t in found.values()) / len(found)
    return len(found) / len(rows), avg, found


def detect_title_source(rows: list) -> str:
    """标题来源：比较 title 属性 / 子元素 / 各 class 的链接文字。

    规则：
      - 覆盖率 ≥60% 且平均长度 ≥4 才算候选；
      - 若 title 属性文本是“最长链接文字”的前缀（说明链接文字只是多了装饰，
        如状态/评分），则属性更干净，优先采用；
      - 否则取“平均长度最长”的候选（信息最完整）。
    """
    if not rows:
        return ""
    cands = [(_TITLE_ATTR_RE, "attr"), (_TITLE_NAME_RE, "name")]
    cls_count: dict = {}
    for r in rows:
        seen = set()
        for m in _ANCHOR_RE.finditer(r):
            cm = _CLASS_RE.search(m.group(1) or "")
            if not cm:
                continue
            c = (cm.group(1) or "").strip()
            if c and len(c) <= 60 and c not in seen:
                seen.add(c)
                cls_count[c] = cls_count.get(c, 0) + 1
    half = max(1, len(rows) // 2)
    for c, n in cls_count.items():
        if n >= half:
            cands.append((f"<a[^>]*class=\"[^\"]*{_esc(c)}[^\"]*\"[^>]*>(.*?)</a>",
                          "anchor"))
    scored = []
    for pat, kind in cands:
        m = _measure(rows, pat)
        if not m:
            continue
        cover, avg, found = m
        if cover < 0.6 or avg < 4:
            continue
        scored.append((pat, kind, cover, avg, found))
    if not scored:
        return ""                      # 交给引擎用链接文字兜底
    best = max(scored, key=lambda x: x[3] * x[2])
    # 属性 vs 最长链接文字：属性是前缀 → 属性更干净
    anchor = max((s for s in scored if s[1] == "anchor"),
                 key=lambda x: x[3], default=None)
    if anchor:
        for pat, kind, cover, avg, found in scored:
            if kind != "attr":
                continue
            ok = sum(1 for i, t in found.items()
                     if i in anchor[4] and _norm(anchor[4][i]).startswith(_norm(t)))
            if ok >= max(1, int(len(rows) * 0.6)):
                return pat
    return best[0]


def detect_date(html: str, row_re: str = "") -> tuple:
    """日期探测：返回 (mode, date_re)。行内过半 → rows；否则 date_anchor。"""
    if not html:
        return "rows", ""
    found = ""
    for _name, pat in _DATE_PROBES:
        if re.search(pat, html):
            found = pat
            break
    if not found:
        return "rows", ""
    if row_re:
        rows = sample_rows(html, row_re, 60)
        if rows:
            inside = sum(1 for r in rows if re.search(found, r))
            if inside >= max(1, len(rows) // 2):
                return "rows", found
    return "date_anchor", found


def detect_status(html: str, row_re: str) -> str:
    """状态标记（如“更新至18集/全集/HD”），返回 status_re。"""
    rows = sample_rows(html, row_re, 30) if row_re else []
    if not rows:
        return ""
    best, best_n = "", 0
    for pat in _STATUS_CANDIDATES:
        try:
            rx = re.compile(pat, re.I | re.S)
        except re.error:
            continue
        n = sum(1 for r in rows if rx.search(r))
        if n > best_n:
            best, best_n = pat, n
    return best if best_n >= max(2, len(rows) // 4) else ""


def _guess_block_label(name: str) -> str:
    """版块/导航文字 → 统一区块 label（未识别返回空串=不收录）。"""
    from ..parser import block_label_for_heading, tab_block_label

    text = clean_html(name or "")
    if not text:
        return ""
    label = tab_block_label(text) or block_label_for_heading(text)
    if label:
        return label
    if text in _BLOCK_ALIASES:
        return _BLOCK_ALIASES[text]
    for key, val in _BLOCK_ALIASES.items():
        if key in text:
            return val
    return ""


def detect_block_source(html: str) -> tuple:
    """区块来源探测：返回 (kind, regex, name_map)。

    kind: heading（tab 按钮/标题就近归区块）/ row（行级版块名）/
          map（导航路径映射）/ none
    """
    if not html:
        return "none", "", {}
    if _TAB_BTN_RE.search(html):
        # tab 按钮常与 <h> 混用，合并为一个正则（名称组始终放最后）
        regex = (_TAB_RE_STR if not _HEADING_RE.search(html)
                 else _TAB_RE_STR + "|" + _H_RE_STR)
        return "heading", regex, {}
    if _HEADING_RE.search(html):
        return "heading", _H_RE_STR, {}
    forums = _FORUM_LINK_RE.findall(html)
    if len(forums) >= 3:
        name_map: dict = {}
        for _href, name in forums:
            nm = clean_html(name)
            if nm and nm not in name_map:
                name_map[nm] = _guess_block_label(nm)
        if any(name_map.values()):
            return ("row",
                    r"<a href=\"forum-\d+[^\"]*\"[^>]*title=\"([^\"]*)\"",
                    name_map)
    navs = _NAV_LINK_RE.findall(html)
    if navs:
        mapping: dict = {}
        for path, text in navs:
            label = _guess_block_label(text)
            if label:
                mapping[path] = label
        if mapping:
            return "map", "", mapping
    return "none", "", {}


# ---------------------------------------------------------------- 规则生成
def build_rule(entry_url: str, html: str, module_id: str = "",
               name: str = "", encoding: str = "auto",
               max_pages: int = 1) -> dict:
    """单页推导规则 dict（不抓详情页）；失败返回 {}。"""
    link_re = detect_link_pattern(html)
    if not link_re:
        return {}
    rows = detect_row_candidates(html, link_re)
    if rows:
        # 有行容器就用行容器（页面其他位置的零星日期不代表列表行有日期）
        mode, row_re = "rows", rows[0][0]
        date_mode, _probe = detect_date(html, row_re)
        date_re = (_ENGINE_DATE_RE
                   if date_mode == "rows"
                   and re.search(_ENGINE_DATE_RE, html) else "")
    else:
        # 无行容器（老模板 table 布局等）→ 退回日期锚点
        mode, row_re = "date_anchor", ""
        date_re = (_ENGINE_DATE_RE if re.search(_ENGINE_DATE_RE, html)
                   else detect_date(html, "")[1])
    title_re = detect_title_source(sample_rows(html, row_re) if row_re else [])
    status_re = detect_status(html, row_re)
    kind, block_re, name_map = detect_block_source(html)
    return {
        "module_id": module_id or _slug(entry_url),
        "name": name or (urlparse(entry_url).netloc or entry_url),
        "desc": "AutoProfile 自动推导规则（建议人工预览确认）",
        "encoding": encoding,
        "entry_mode": "entries",
        "entry_urls": [entry_url],
        "max_pages": max_pages,
        "page_template": "",
        "extract": {
            "mode": mode,
            "row_re": row_re,
            "link_re": link_re,
            "title_re": title_re,
            "status_re": status_re,
            "date_re": date_re,
            "block_re": block_re if kind == "heading" else "",
            "block_row_re": block_re if kind == "row" else "",
            "block_name_map": name_map if kind == "row" else {},
            "block_map": name_map if kind == "map" else {},
            "skip_row_re": "",
            "min_title_len": 2,
            "title_qual_re": "",
            "title_status_join": True,
            "alt_complete": False,
        },
        "detail": {
            "magnet_re": r"magnet:\?xt=urn:[a-z0-9]+:[A-Za-z0-9_-]{16,}",
            # pan_res 由 src/site/netdisk.py 统一提供，无需逐站列举
            "attach_res": ["attach-download", "/download/", "download.php"],
            "desc_mode": "meta",
        },
    }


def rule_to_module(rule: dict):
    """规则 dict → GenericModule；无效返回 None。"""
    try:
        return GenericModule(GenericRule.from_dict(rule))
    except Exception:
        return None


# ---------------------------------------------------------------- 本地 / AI
def derive_rule(url: str, html: str, cfg=None, use_ai: bool = False,
                log_cb=None, ai_timeout: int = 90) -> dict:
    """生成规则：默认本地推导；use_ai 时先试 AI，失败自动降级本地。

    AI 结果必须通过**本地双重把关**才采用：
      ① rule_store.validate_rule（结构与正则）；
      ② 在样本上试解析 ≥3 条。
    返回 {"rule": dict|None, "source": "local"|"ai"|"", "notes": [str]}。
    """

    def emit(msg: str) -> None:
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    notes: list = []
    local = build_rule(url, html)
    by_local = "local" if local else ""
    if not use_ai:
        emit("[推导] 使用本地 AutoProfile 推导")
        return {"rule": local, "source": by_local, "notes": notes}

    emit("[推导] 调用 AI 生成规则……")
    hint = ""
    if local:
        ex = local.get("extract") or {}
        hint = json.dumps({
            "mode": ex.get("mode"), "link_re": ex.get("link_re"),
            "row_re": ex.get("row_re"), "title_re": ex.get("title_re"),
            "date_re": ex.get("date_re"),
        }, ensure_ascii=False)
    try:
        from ..ai_client import generate_rule

        rule = generate_rule(cfg, url, html, hint=hint, timeout=ai_timeout)
    except Exception as e:
        notes.append(f"AI 生成失败，已改用本地推导：{e}")
        emit("[推导] AI 失败 → 降级本地：" + str(e)[:120])
        return {"rule": local, "source": by_local, "notes": notes}

    errors = validate_rule(rule)
    if errors:
        notes.append("AI 规则未通过校验，已改用本地推导：" + "；".join(errors[:3]))
        emit("[推导] AI 规则校验失败 → 降级本地")
        return {"rule": local, "source": by_local, "notes": notes}
    module = rule_to_module(rule)
    items = module.parse_list(html, url, entry_url=url) if module else []
    if len(items) < 3:
        notes.append(f"AI 规则仅解析到 {len(items)} 条（<3），已改用本地推导")
        emit(f"[推导] AI 规则试解析仅 {len(items)} 条 → 降级本地")
        return {"rule": local, "source": by_local, "notes": notes}
    emit(f"[推导] AI 规则通过校验，试解析 {len(items)} 条")
    return {"rule": rule, "source": "ai", "notes": notes}


# ---------------------------------------------------------------- 完整流程
def analyze(url: str, fetcher=None, max_details: int = 3,
            polite_delay: float = 0.3, log_cb=None) -> dict:
    """完整推导：抓入口页 → 生成规则 → 试解析 → 详情验证。

    返回 {ok, rule, confidence{items,magnet_ratio,details_checked,mode},
          samples{entry_url,detail_urls}, warnings[]}。
    """
    from ..fetcher import SiteFetcher

    fetcher = fetcher or SiteFetcher()
    result = {"ok": False, "rule": {}, "confidence": {},
              "samples": {"entry_url": url, "detail_urls": []},
              "warnings": []}

    def emit(msg: str) -> None:
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    emit(f"[分析] 抓取入口页 {url}")
    try:
        html, _final = fetcher.get(url, timeout=20)
    except Exception as e:
        result["warnings"].append(f"入口抓取失败：{type(e).__name__}: {e}")
        return result
    if len(html) < 3000:
        result["warnings"].append("入口页面内容过短，可能被反爬拦截或需要登录")

    rule = build_rule(url, html)
    if not rule:
        result["warnings"].append(
            "未能探测到详情链接模式（页面可能为 JS 渲染、需登录或结构特殊）")
        return result
    module = rule_to_module(rule)
    if module is None:
        result["warnings"].append("推导出的规则未通过校验")
        return result

    items = module.parse_list(html, url, entry_url=url)
    result["confidence"]["mode"] = rule["extract"]["mode"]
    result["confidence"]["items"] = len(items)
    emit(f"[分析] 模式 {rule['extract']['mode']}，试解析 {len(items)} 条")
    if len(items) < 3:
        result["warnings"].append(
            f"仅解析到 {len(items)} 条，规则可能不完整（可人工调整 row_re/link_re）")

    picks = items[:max_details] if items else []
    if picks:
        hit, checked = 0, 0
        for it in picks:
            try:
                dhtml, _ = fetcher.get(it.detail_url, timeout=20)
            except Exception as e:
                result["warnings"].append(
                    f"详情抓取失败 {it.detail_url}：{type(e).__name__}")
                continue
            checked += 1
            try:
                module.parse_detail(dhtml, it)
                if it.magnets:
                    hit += 1
            except Exception:
                pass
            if polite_delay > 0:
                time.sleep(min(polite_delay, 1.0))
        if checked:
            ratio = round(hit / checked, 2)
            result["confidence"]["magnet_ratio"] = ratio
            result["confidence"]["details_checked"] = checked
            emit(f"[分析] 详情验证 {hit}/{checked} 含资源")
            if hit == 0:
                result["warnings"].append(
                    "详情页未解析到磁力/附件/网盘（可能需登录，或详情规则需调整）")
        result["samples"]["detail_urls"] = [it.detail_url for it in picks]

    result["rule"] = rule
    result["ok"] = len(items) >= 3
    if result["ok"]:
        emit("[分析] 完成，规则已生成（请人工预览后保存）")
    return result
