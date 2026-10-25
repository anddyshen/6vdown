"""剪贴板 / 文本中的链接解析（纯逻辑，可单测）。

识别：磁力链接、http(s) 链接、ed2k / thunder（提示不支持）。
http 链接细分：.torrent 直链 / 疑似 PT 直链 / 普通网页。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

# 全角空格字符
FWS = "\u3000"

_MAGNET_RE = re.compile(
    "magnet:\\?xt=urn:[a-z0-9]+:[A-Za-z0-9_-]{16,}(?:&[^\\s<>\"'，。；、\u3000]*)?",
    re.IGNORECASE,
)
_HTTP_RE = re.compile(
    "https?://[^\\s<>\"'，。；、（）()【】《》\u3000\n\r]+", re.IGNORECASE
)
_ED2K_RE = re.compile("ed2k://[^\\s<>\"']+", re.IGNORECASE)
_THUNDER_RE = re.compile("thunder://[^\\s<>\"']+", re.IGNORECASE)


@dataclass
class ParsedLink:
    kind: str = "unknown"      # magnet | http | ed2k | thunder
    url: str = ""
    sub: str = ""              # http 细分: torrent | pt | web
    note: str = ""


def classify_http(url: str) -> str:
    """返回 torrent / pt / web。"""
    try:
        p = urlparse(url)
    except Exception:
        return "web"
    path = (p.path or "").lower()
    query = (p.query or "").lower()
    low = url.lower()
    if path.endswith(".torrent") or ".torrent?" in low:
        return "torrent"
    if "passkey=" in query or "down=" in query or "download.php" in path:
        return "pt"
    return "web"


def _normalize(text: str) -> str:
    return (text or "").replace(FWS, " ").replace("\r", " ").replace("\n", " ")


def _clean(url: str) -> str:
    url = (url or "").strip()
    return url.rstrip(".,;:)]}>、，。；：")


def parse_text(text: str) -> list:
    """从任意文本中提取链接，返回 list[ParsedLink]。"""
    text = _normalize(text or "")
    out: list = []
    seen = set()

    def push(kind, url, sub="", note=""):
        url = _clean(url)
        if not url or url in seen:
            return
        seen.add(url)
        if len(url) > 20000:
            url = url[:20000]
        out.append(ParsedLink(kind=kind, url=url, sub=sub, note=note))

    magnet_spans = [m.span() for m in _MAGNET_RE.finditer(text)]
    skip_spans = list(magnet_spans)
    skip_spans += [m.span() for m in _ED2K_RE.finditer(text)]
    skip_spans += [m.span() for m in _THUNDER_RE.finditer(text)]

    def in_span(pos: int) -> bool:
        return any(s <= pos < e for s, e in skip_spans)

    for m in _MAGNET_RE.finditer(text):
        push("magnet", m.group(0))
    for m in _ED2K_RE.finditer(text):
        push("ed2k", m.group(0))
    for m in _THUNDER_RE.finditer(text):
        push("thunder", m.group(0))
    for m in _HTTP_RE.finditer(text):
        if in_span(m.start()):
            continue
        url = m.group(0)
        sub = classify_http(url)
        note = {
            "torrent": "种子文件直链",
            "pt": "PT 下载直链",
            "web": "网页/普通链接",
        }.get(sub, "")
        push("http", url, sub, note)
    return out


def is_magnet_like(url: str) -> bool:
    return bool(_MAGNET_RE.match((url or "").strip()))


def looks_like_link(text: str) -> bool:
    return bool(text) and bool(_MAGNET_RE.search(text) or _HTTP_RE.search(text))


def resolve_link(url: str, base: str) -> str:
    return urljoin(base or "", url or "")


def magnet_hash(url: str) -> str:
    """粗略提取磁力哈希作过去重指纹，无则返回原 url。"""
    m = re.search(r"urn:btih:([0-9a-fA-F]{40}|[A-Za-z0-9]{32})", url or "")
    if m:
        return m.group(1).lower()
    return (url or "").strip()


MEDIA_EXTENSIONS = (
    ".mp4", ".mkv", ".rmvb", ".avi", ".ts", ".flv", ".iso", ".torrent",
    ".wmv", ".mov", ".m4v", ".webm", ".zip", ".rar", ".7z"
)


def format_download_name(
    url: str,
    title: str = "",
    ep_label: str = "",
    quality: str = "",
    raw_label: str = "",
) -> str:
    """提取或生成详尽的下载资源名称。

    规则：
    1. 优先提取 Magnet 的 &dn= 文件名（URL 解码）或 HTTP/FTP/ED2K 直链的文件名；
    2. 若链接无文件名，但 ep_label 或 raw_label 自身带有视频扩展名（如 .mp4, .mkv 等），视为文件名；
    3. 若有文件名，且有解析出的影视标题：若文件名已包含标题则直接用文件名，否则组合成 《标题》 文件名；
    4. 若无文件名，则使用解析出的相关名字作为名称：《影视名》 + 分集标签 + [画质]；
    5. 终极兜底：当没有任何名称或标签时，显示前 60 个字符的截断 URL。
    """
    import posixpath
    from urllib.parse import parse_qs, unquote, urlparse

    file_name = ""
    u = (url or "").strip()

    # 1. 尝试从 URL 中解析真实文件名
    if u.startswith("magnet:"):
        try:
            p = urlparse(u)
            qs = parse_qs(p.query)
            dn = qs.get("dn", [])
            if dn:
                file_name = unquote(dn[0]).strip()
        except Exception:
            pass
    elif u.startswith(("http://", "https://", "ftp://", "ed2k://")):
        try:
            if u.startswith("ed2k://"):
                parts = u.split("|")
                if len(parts) >= 4 and parts[1].lower() == "file":
                    file_name = unquote(parts[2]).strip()
            else:
                p = urlparse(u)
                base = posixpath.basename(p.path or "")
                if base and "." in base:
                    file_name = unquote(base).strip()
        except Exception:
            pass

    # 2. 如果 URL 中没有文件名，检查 raw_label / ep_label 是否为完整文件名
    if not file_name:
        for candidate in (raw_label, ep_label):
            cand = (candidate or "").strip()
            if any(cand.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
                file_name = cand
                break

    title = (title or "").strip()
    ep_label = (ep_label or "").strip()
    quality = (quality or "").strip()
    raw_label = (raw_label or "").strip()

    # 3. 处理有真实文件名的情况
    if file_name:
        if title:
            # 文件名中若尚未包含影视标题，则冠以《标题》
            if title.lower() not in file_name.lower():
                final_name = f"《{title}》 {file_name}"
            else:
                final_name = file_name
        else:
            final_name = file_name

        # 检查是否需要附加分集标签（例如文件名未体现集数时）
        if ep_label and ep_label != file_name and ep_label not in final_name:
            import re
            m_ep = re.search(r"\d+", ep_label)
            has_ep_num = False
            if m_ep:
                num_str = m_ep.group(0)
                # 检查类似 E01, EP01, 第01集 等在文件名中是否存在
                patterns = [
                    f"e{int(num_str):02d}",
                    f"ep{int(num_str):02d}",
                    f"e{int(num_str)}",
                    f"ep{int(num_str)}",
                    f"第{num_str}",
                    f"_{int(num_str):02d}_",
                    f"_{int(num_str):02d}.",
                    f"-{int(num_str):02d}.",
                ]
                has_ep_num = any(p in file_name.lower() for p in patterns)
            if not has_ep_num:
                final_name = f"{final_name} ({ep_label})"
        return final_name

    # 4. 没有文件名：使用解析出的相关名称（影视名称 + 分集 + 画质）
    parts = []
    if title:
        parts.append(f"《{title}》")

    display_label = ep_label or raw_label
    if display_label:
        if title and title in display_label:
            parts = [display_label]
        else:
            parts.append(display_label)

    if quality:
        current_str = " ".join(parts)
        if quality.upper() not in current_str.upper():
            parts.append(f"[{quality}]")

    if parts:
        return " ".join(parts)

    # 5. 兜底
    return u[:60] + "..." if len(u) > 60 else (u or "未知资源")
