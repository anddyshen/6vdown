"""下载器客户端包。"""
from .base import BaseClient, SendResult
from .clients import Aria2Client, QBittorrentClient, TransmissionClient
from .manager import DownloaderManager

__all__ = [
    "BaseClient",
    "SendResult",
    "DownloaderManager",
    "QBittorrentClient",
    "TransmissionClient",
    "Aria2Client",
]
