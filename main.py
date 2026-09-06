"""6vdown 入口。

用法：
    python main.py                 # 启动图形界面
    python main.py --parse-headless  # 无界面执行一次站点解析（调试用）
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _headless_parse() -> int:
    from src.config import Config
    from src.database import Database
    from src.site.fetcher import SiteFetcher
    from src.site.service import SiteParseService

    db = Database()
    cfg = Config()
    svc = SiteParseService(db, SiteFetcher())
    summary = svc.run(enabled_blocks=cfg["enabled_blocks"],
                      log_cb=lambda s: print(s, flush=True))
    for it in summary.get("items") or []:
        print(f"ITEM\t{it.title}\t{it.block}\t{it.date}\t{it.detail_url}\t"
              f"磁力={len(it.magnets)}\t红={it.is_red}\t经典={it.is_classic}",
              flush=True)
    return 0 if summary.get("ok") else 1


def main() -> None:
    if "--parse-headless" in sys.argv:
        sys.exit(_headless_parse())
    from src.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
