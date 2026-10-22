"""6vdown / C2Down - Docker 与 Web 服务端启动入口。

用法：
    python server.py --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import os
import sys
import uvicorn

from src.log import get_logger

log = get_logger("main_server")


def main():
    parser = argparse.ArgumentParser(description="6vdown / C2Down Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听 IP（默认 0.0.0.0）")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口（支持 PORT 环境变量，默认 5080）",
    )
    args = parser.parse_args()

    port = args.port
    if port is None:
        env_p = os.environ.get("PORT") or os.environ.get("C2DOWN_PORT")
        port = int(env_p) if env_p and env_p.isdigit() else 5080

    log.info("正在启动 6vdown Web 服务: http://%s:%d", args.host, port)
    uvicorn.run(
        "src.server.app:app",
        host=args.host,
        port=port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()

