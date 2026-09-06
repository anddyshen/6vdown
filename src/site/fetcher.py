"""站点抓取：requests + GBK 解码 + 校准缓存副本。"""
from __future__ import annotations

import os
import re
import time

import requests

from .. import constants
from ..log import get_logger

log = get_logger("site.fetcher")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_CHARSET_RE = re.compile(r'charset\s*=\s*["\']?([\w-]+)', re.IGNORECASE)


def decode_bytes(raw: bytes) -> str:
    head = raw[:1500].decode("latin1", "ignore")
    m = _CHARSET_RE.search(head)
    declared = m.group(1) if m else ""
    candidates = [declared, "gb18030", "utf-8"]
    for enc in candidates:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("gb18030", "replace")


class SiteFetcher:
    """带 UA、超时、缓存副本的抓取器。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get(self, url: str, timeout: int = 18, cache: bool = False):
        """GET 并解码为文本。cache=True 时保留一份 HTML 副本用于校准。"""
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        html = decode_bytes(resp.content)
        if cache:
            self._save_cache(url, resp.content)
        return html, resp.url

    def probe(self, url: str, timeout: int = 10) -> tuple:
        """探测镜像可用性：返回 (ok, 说明, 文本长度)。"""
        try:
            resp = self.session.get(url, timeout=timeout, allow_redirects=True)
            html = decode_bytes(resp.content)
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}", 0
            if len(html) < 3000:
                return False, "内容过短，可能非站点首页", len(html)
            return True, "OK", len(html)
        except requests.RequestException as e:
            return False, f"{type(e).__name__}: {e}", 0

    def _save_cache(self, url: str, raw: bytes) -> str:
        try:
            d = constants.www_cache_dir()
            host = re.sub(r"[^0-9a-zA-Z]", "_", url.split("//")[1].split("/")[0])
            path = os.path.join(d, f"home_{host}_{time.strftime('%Y%m%d_%H%M%S')}.html")
            with open(path, "wb") as f:
                f.write(raw)
            # 仅保留最新 5 份
            files = sorted(
                (os.path.join(d, x) for x in os.listdir(d) if x.startswith("home_")),
                key=os.path.getmtime,
            )
            for old in files[:-5]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            return path
        except Exception:
            return ""
