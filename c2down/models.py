"""数据模型（dataclass）。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


def now_ms() -> int:
    return int(time.time() * 1000)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class DownloadHost:
    """下载主机配置。type: qb / tr / ar"""

    id: Optional[int] = None
    type: str = "qb"
    name: str = ""
    address: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    is_active: bool = False
    created_at: int = 0

    def base_url(self) -> str:
        addr = (self.address or "").strip().rstrip("/")
        if addr.startswith("http://") or addr.startswith("https://"):
            return addr
        scheme = "http"
        if self.port in (443, 8443):
            scheme = "https"
        return f"{scheme}://{addr}" + (f":{self.port}" if self.port else "")


@dataclass
class MirrorSite:
    """备用镜像站。"""

    id: Optional[int] = None
    url: str = ""
    enabled: bool = True
    is_current: bool = False
    status: str = ""  # "" | "ok" | "fail"
    checked_at: int = 0
    created_at: int = 0
    note: str = ""


@dataclass
class MagnetLink:
    """单个磁力/资源地址，label 用于展示与分集。"""

    label: str = ""
    url: str = ""


@dataclass
class ParseItem:
    """首页更新列表中的一条解析结果。"""

    title: str = ""
    date: str = ""
    block: str = "其他"          # 归属区块
    detail_url: str = ""         # 详情页绝对地址（增量去重主键）
    is_red: bool = False
    is_classic: bool = False
    magnets: list = field(default_factory=list)   # list[MagnetLink]
    desc: str = ""
    detail_ok: bool = False      # 详情页是否抓取成功
    error: str = ""
    first_seen: int = 0

    def magnet_urls(self) -> list:
        return [m.url for m in self.magnets]

    def episode_groups(self) -> "dict":
        """按链接文字分集：{ '第156集': [MagnetLink...], '整片/未标注': [...] }"""
        import re as _re

        groups: dict = {}
        ep_re = _re.compile(constants_pattern())
        for m in self.magnets:
            label = (m.label or "").strip()
            m2 = ep_re.search(label) if label else None
            key = m2.group(0) if m2 else ("整片" if not label else f"其他({label[:12]})")
            groups.setdefault(key, []).append(m)
        return groups


def constants_pattern():
    from . import constants

    return constants.EPISODE_RE_STR


@dataclass
class TaskRecord:
    """task_log 中的一条操作痕迹。"""

    id: Optional[int] = None
    created_at: int = 0
    title: str = ""
    link: str = ""
    source: str = ""           # clipboard / drop / site / manual
    host_name: str = ""
    host_type: str = ""
    status: str = ""           # ok / fail
    message: str = ""


def host_from_row(row: Any) -> DownloadHost:
    return DownloadHost(id=row[0], type=row[1], name=row[2], address=row[3],
                        port=row[4], username=row[5], password=row[6],
                        is_active=bool(row[7]), created_at=row[8])


def mirror_from_row(row: Any) -> MirrorSite:
    return MirrorSite(id=row[0], url=row[1], enabled=bool(row[2]),
                      is_current=bool(row[3]), status=row[4],
                      checked_at=row[5], created_at=row[6], note=row[7] or "")


def task_from_row(row: Any) -> TaskRecord:
    return TaskRecord(id=row[0], created_at=row[1], title=row[2], link=row[3],
                      source=row[4], host_name=row[5], host_type=row[6],
                      status=row[7], message=row[8])
