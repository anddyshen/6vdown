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
    "enabled_sites": [],              # 工作台勾选的站点 id 列表；空 = 全部启用站点
    "fetch_detail": True,         # 是否抓取详情页磁力
    "polite_delay": 0.3,          # 详情页请求间隔
    "detail_concurrency": 2,      # 详情页并发抓取数（1=串行最礼貌；慢站点可调高）
    "drop_win_on_top": True,      # 拖拽小窗置顶
    "parse_default": "ask",
    "start_behavior": "window",
    "clip_start": "last",
    "first_run": True,
    # 订阅与自动追剧
    "sub_auto_on_startup": True,             # 启动后自动检查订阅
    "sub_auto_direct_download": False,        # 发现新集数直接下载无需确认（默认需确认）
    "sub_scheduler_enabled": True,           # 周期性定时检查
    "sub_interval_hours": 4,                 # 检查间隔（小时）
    "quality_priority": ["1080P", "4K", "720P", "OTHER"],  # 默认 1080P 优先
    # Emby 媒体库联动
    "emby_enabled": False,
    "emby_server_url": "",                   # http://192.168.1.x:8096
    "emby_api_key": "",
    # AI 助手（仅用于“新站点解析规则生成”，可完全关闭）
    "ai_enabled": False,           # 总开关
    "ai_provider": "external",     # external=外部 OpenAI 兼容服务 | local=本机 Ollama/LM Studio
    "ai_base_url": "",             # 如 https://api.deepseek.com/v1
    "ai_model": "",                # 如 deepseek-chat / qwen2.5:7b
    "ai_api_key_enc": "",          # DPAPI 加密存储（明文不落盘）
    "ai_timeout": 90,              # 单次生成超时（秒）
    # 关键词搜索（跨站点并发；结果不入库，按需抓详情页）
    "search_sites": [],            # 参与搜索的站点 id 列表；空 = 全部支持搜索的启用站点
    "search_max_pages": 1,         # 每站点最多翻几页
    "search_limit": 80,            # 每站点结果上限
    "search_polite_delay": 0.3,    # 站内翻页间隔
    "search_concurrency": 2,       # 跨站点并发数
    "search_history_size": 20,     # 历史关键词保留条数
    "search_auto_detail": 8,       # 搜索后自动抓取前 N 条详情页资源（0 = 关闭）
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
