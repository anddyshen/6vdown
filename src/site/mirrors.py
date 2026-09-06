"""镜像管理与可用性探测、地址发布页发现。"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .. import constants
from ..log import get_logger
from .fetcher import SiteFetcher

log = get_logger("site.mirrors")

_URL_RE = re.compile(r"https?://[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?:/|\\b)")


def normalize_url(url: str) -> str:
    url = (url or "").strip().strip("\"'")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    return url.rstrip("/") + "/"


def host_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def discover_from_publish(url: str = constants.PUBLISH_PAGE,
                          fetcher: SiteFetcher | None = None) -> list:
    """从 6v123 地址发布页读取最新可用域名（UTF-8）。返回候选 https:// 地址。"""
    fetcher = fetcher or SiteFetcher()
    out = []
    try:
        html, _ = fetcher.get(url, timeout=15)
    except Exception as e:
        log.warning("读取发布页失败: %s", e)
        return out
    for host in set(_URL_RE.findall(html)):
        host = host.rstrip("/").lower()
        if not host.startswith("http"):
            continue
        if any(h in host for h in constants.PUBLISH_DOMAIN_HINTS):
            continue
        out.append(host + "/")
    out.sort()
    return out


def probe_mirrors(urls: list, fetcher: SiteFetcher | None = None) -> dict:
    """探测列表各地址，返回 {url: (ok:bool, note:str, length:int)}。"""
    fetcher = fetcher or SiteFetcher()
    result = {}
    for url in urls:
        result[url] = fetcher.probe(url)
    return result
