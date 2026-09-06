"""JSON 应用配置读写。"""
from __future__ import annotations

import json
import os

from . import constants
from .constants import BLOCK_KEYWORDS

DEFAULTS = {
    "theme": "system",            # system | light | dark
    "http_mode": "ask",           # http 链接处理：ask/send/ignore
    "clipboard_monitor": True,    # 剪贴板监听开关
    "notify_enabled": True,       # 右下角提醒总开关
    "notify_seconds": 6,          # 弹窗停留秒数
    "auto_send_magnet": True,     # 磁力链接自动发送
    "start_on_boot": False,       # 开机自启
    "parse_enabled": False,       # 定时自动解析（预留）
    "parse_interval_min": 30,     # 预留
    "enabled_blocks": list(BLOCK_KEYWORDS.keys()),
    "fetch_detail": True,         # 是否抓取详情页磁力
    "polite_delay": 0.3,          # 详情页请求间隔
    "drop_win_on_top": True,      # 拖拽小窗置顶
    "parse_default": "ask",
    "start_behavior": "window",
    "clip_start": "last",
    "first_run": True,
}


class Config:
    def __init__(self, path: str = ""):
        self.path = path or constants.config_path()
        self.data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                merged = dict(DEFAULTS)
                merged.update(loaded)
                self.data = merged
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULTS.get(key) if default is None else default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def __contains__(self, key) -> bool:
        return key in self.data
