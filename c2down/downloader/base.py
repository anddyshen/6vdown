"""下载器客户端基类与结果对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import DownloadHost


@dataclass
class SendResult:
    ok: bool = False
    message: str = ""
    extra: str = ""


class BaseClient:
    """统一接口：连接测试 + 添加任务。"""

    label = "base"

    def __init__(self, host: DownloadHost):
        self.host = host
        self.base = host.base_url() if host else ""

    def add(self, url: str, timeout: int = 25) -> SendResult:
        raise NotImplementedError

    def test(self, timeout: int = 8) -> SendResult:
        raise NotImplementedError

    @staticmethod
    def build(host: DownloadHost) -> "BaseClient":
        from .clients import Aria2Client, QBittorrentClient, TransmissionClient

        if host.type == "tr":
            return TransmissionClient(host)
        if host.type == "ar":
            return Aria2Client(host)
        return QBittorrentClient(host)
