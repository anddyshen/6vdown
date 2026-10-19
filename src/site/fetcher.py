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


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text[:4000])


def decode_bytes(raw: bytes) -> str:
    """解码页面字节。

    顺序策略（兼容部分 CDN 节点“声明 gb2312、实际输出 UTF-8”的情况）：
      1) 能按 UTF-8 干净解码且含中文 → 直接采用（GBK 字节几乎不可能通过）；
      2) 按页面声明 → gb18030 顺序严格解码；
      3) 全部严格失败时，取替换字符最少的编码。
    """
    head = raw[:1500].decode("latin1", "ignore")
    m = _CHARSET_RE.search(head)
    declared = (m.group(1) or "").lower() if m else ""
    ordered: list = []
    for enc in (declared, "gb18030", "utf-8"):
        if enc and enc not in ordered:
            ordered.append(enc)
    try:
        text = raw.decode("utf-8")
        if _has_cjk(text):
            return text
    except (UnicodeDecodeError, LookupError):
        pass
    for enc in ordered:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    best = None
    for enc in ordered:
        try:
            soft = raw.decode(enc, "replace")
        except LookupError:
            continue
        n = soft.count("\ufffd")
        if best is None or n < best[0]:
            best = (n, soft)
    return best[1] if best else raw.decode("gb18030", "replace")


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
