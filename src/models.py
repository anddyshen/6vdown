"""数据模型（dataclass）。"""
from __future__ import annotations

import json
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
    """单个磁力/资源地址，label 用于展示与分集。

    kind: magnet（磁力，可发送）/ torrent（.torrent 附件直链，可发送）
          / pan（网盘或非种子附件，仅展示+复制，不可发送）。
    """

    label: str = ""
    url: str = ""
    kind: str = "magnet"

    def sendable(self) -> bool:
        return self.kind in ("magnet", "torrent")


@dataclass
class SiteInstance:
    """站点实例：一个可独立解析的站点（绑定解析模块与入口地址）。

    - entry_urls 为空 → 使用共享镜像池（mirror_sites，hao6v 家族行为）；
    - entry_urls 非空 → 逐入口抓取（分类页/版块页站点，如电影港新版、1lou）。
    - is_current：当前解析站点（每次解析优先使用，失效时按启用顺序降级）。
    """

    id: Optional[int] = None
    module_id: str = "hao6v"
    name: str = ""
    entry_urls: list = field(default_factory=list)
    enabled: bool = True
    is_current: bool = False
    note: str = ""
    created_at: int = 0

    def entries(self) -> list:
        return [u for u in (self.entry_urls or []) if u]


def site_from_row(row: Any) -> SiteInstance:
    urls: list = []
    try:
        data = json.loads(row["entry_urls"] or "[]")
        urls = [str(x) for x in data if x]
    except Exception:
        urls = []
    return SiteInstance(
        id=row["id"], module_id=row["module_id"] or "hao6v",
        name=row["name"] or "", entry_urls=urls,
        enabled=bool(row["enabled"]),
        is_current=bool(row["is_current"]) if "is_current" in row.keys() else False,
        note=row["note"] or "",
        created_at=row["created_at"] or 0,
    )


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
    is_update: bool = False      # 同一详情页的后续更新（集数/日期前进）
    prev_title: str = ""         # 更新前的标题（库中旧值，用于“05 → 06”提示）
    last_seen: int = 0           # 最近一次在首页看到的时间戳（毫秒）

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


@dataclass
class Subscription:
    """订阅项：追踪某部剧在站内的更新。"""

    id: Optional[int] = None
    title: str = ""
    detail_url: str = ""
    status: str = "active"          # active | paused | completed
    last_ep: str = ""              # 最近检测到的集数标签，如“第12集”
    emby_series_id: str = ""       # 绑定的 Emby Series ID（可选）
    created_at: int = 0
    updated_at: int = 0


@dataclass
class SubscriptionHistory:
    """已推送/下载的订阅磁力记录（防重复）。"""

    id: Optional[int] = None
    sub_id: int = 0
    episode_label: str = ""
    magnet_url: str = ""
    quality: str = ""
    pushed_at: int = 0


def sub_from_row(row: Any) -> Subscription:
    return Subscription(
        id=row[0],
        title=row[1],
        detail_url=row[2],
        status=row[3],
        last_ep=row[4] or "",
        emby_series_id=row[5] or "",
        created_at=row[6],
        updated_at=row[7],
    )

