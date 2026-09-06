"""无界面诊断：抓当前镜像首页并打印解析结果。

用途：解析结果列表为空时，快速判断是“没抓到数据”还是“抓到了但没显示”。
用法（在有网环境）：
    .venv-run\\Scripts\\python tools\\diag.py
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    from src.config import Config
    from src.database import Database
    from src.site.fetcher import SiteFetcher
    from src.site.parser import _A_RE, _HREF_RE, HomeParser
    from src.site.service import SiteParseService

    db = Database()
    cfg = Config()
    svc = SiteParseService(db, SiteFetcher())
    print("== resolve_site ==")
    url, html = svc.resolve_site()
    if not html:
        print("!! 所有镜像不可用")
        return
    print("site:", url)
    print("html_len:", len(html))

    p = HomeParser(html, url)
    items = p.parse(include_unknown=True)
    print("RAW_ITEMS:", len(items))
    for it in items[:25]:
        print("ITEM |", it.block, "|", it.date, "|",
              (it.title or "")[:42], "|", it.detail_url,
              "| RED" if it.is_red else "", "| CLS" if it.is_classic else "")

    # ---- 每个区块的首条记录：往上打印容器与区块标题（真正的结构样本）
    first_of_block = {}
    for it in items:
        if it.block not in first_of_block:
            first_of_block[it.block] = it
    for block, it in first_of_block.items():
        apos = None
        for m in _A_RE.finditer(html):
            href_m = _HREF_RE.search(m.group(1) or "")
            if not href_m:
                continue
            if urljoin(url, href_m.group(1)) == it.detail_url:
                apos = m.start()
                break
        if apos is None:
            continue
        seg = html[max(0, apos - 1100):apos + 150]
        print(f"--- SECTION [{block}] first-item anchor@{apos} ---")
        print(seg.replace("\n", " "))

    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "cache")
    files = sorted([f for f in os.listdir(d) if f.startswith("home_")]) \
        if os.path.isdir(d) else []
    if files:
        print("CACHE:", os.path.join(d, files[-1]))


if __name__ == "__main__":
    main()

