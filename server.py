"""6vdown / C2Down - Docker 与 Web 服务端启动入口。

用法：
    python server.py --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import sys
import uvicorn

from src.log import get_logger

log = get_logger("main_server")


def main():
    parser = argparse.ArgumentParser(description="6vdown / C2Down Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听 IP（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    args = parser.parse_args()

    log.info("正在启动 6vdown Web 服务: http://%s:%d", args.host, args.port)
    uvicorn.run(
        "src.server.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()

