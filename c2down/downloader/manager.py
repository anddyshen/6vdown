"""DownloaderManager：多主机管理 + 统一发送入口。"""
from __future__ import annotations

from typing import Optional

from ..database import Database
from ..models import DownloadHost
from .base import BaseClient, SendResult

TYPE_LABELS = {"qb": "qBittorrent", "tr": "Transmission", "ar": "Aria2"}


class DownloaderManager:
    def __init__(self, db: Database):
        self.db = db

    def client_for(self, host: Optional[DownloadHost] = None) -> Optional[BaseClient]:
        host = host or self.db.active_host()
        if not host:
            return None
        return BaseClient.build(host)

    def active_host_name(self) -> str:
        h = self.db.active_host()
        if not h:
            return ""
        return TYPE_LABELS.get(h.type, h.type) + ("/" + h.name if h.name else "")

    def send(self, url: str, host: Optional[DownloadHost] = None,
             timeout: int = 30) -> SendResult:
        host = host or self.db.active_host()
        if not host:
            return SendResult(False, "尚未配置下载主机，请在“设置”中添加并激活一台")
        client = BaseClient.build(host)
        return client.add(url, timeout=timeout)

    def test_host(self, host: DownloadHost, timeout: int = 8) -> SendResult:
        return BaseClient.build(host).test(timeout=timeout)
