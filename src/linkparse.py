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
