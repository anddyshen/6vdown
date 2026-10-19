"""应用常量、路径、默认值。"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> str:
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_data_dir() -> str:
    """数据目录（绿色模式）：数据跟随程序所在目录。

    - exe：与 6vdown.exe 同级的 data\\ 目录（拷贝整个目录即便携迁移）；
    - 若 exe 所在目录不可写（如 Program Files），回退 %APPDATA%\\6vdown；
    - 源码运行：项目 data\\ 目录。
    """
    if is_frozen():
        base = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
        try:
            os.makedirs(base, exist_ok=True)
            probe = os.path.join(base, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("1")
            os.remove(probe)
            return base
        except Exception:
            pass
        ap = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = os.path.join(ap, "6vdown")
    else:
        base = os.path.join(project_root(), "data")
    os.makedirs(base, exist_ok=True)
    return base


def legacy_data_dir() -> str:
    """旧版（%APPDATA%）数据目录，用于首次启动自动迁移。"""
    ap = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(ap, "C2Down")  # legacy old-version dir


def db_path() -> str:
    return os.path.join(app_data_dir(), "6vdown.db")


def config_path() -> str:
    return os.path.join(app_data_dir(), "config.json")


def www_cache_dir() -> str:
    d = os.path.join(app_data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- 默认镜像
# 均为实测可访问的同源“旧版模板”站点；地址发布页 6v123.com 仅用于自动发现。
DEFAULT_MIRRORS = [
    "https://www.hao6v.cc/",
    "https://www.6v520.net/",
    "https://www.6v520.cc/",
]
PUBLISH_PAGE = "https://www.6v123.com/"
PUBLISH_DOMAIN_HINTS = ("6v123.com",)

# ---------------------------------------------------------------- 默认站点实例
# 站点实例（site_instances）绑定解析模块；首次运行自动创建默认站点，
# 其入口为空 → 使用上面的共享镜像池（保持旧版行为不变）。
DEFAULT_SITE_MODULE = "hao6v"
DEFAULT_SITE_NAME = "6v电影（默认）"

# ---------------------------------------------------------------- 解析区块
# label -> 标题关键词（首页区块标题命中任一即归属该区块）
BLOCK_KEYWORDS = {
    "最新电影": ["最新电影"],
    "经典高清": ["经典"],
    "更新电视剧": ["电视剧", "更新电视剧"],
    "国剧": ["国剧"],
    "日韩剧": ["日韩剧", "日韩"],
    "美剧": ["美剧", "欧美剧", "欧美"],
    "动画": ["动画", "动漫"],
    "短剧": ["短剧"],
    "综艺": ["综艺"],
}
DEFAULT_ENABLED_BLOCKS = list(BLOCK_KEYWORDS.keys())

# 首页“区块名”其实写在标签按钮上：<li id="tabN_btn_M">区块名</li>，
# 对应的列表容器是 <ul id="tabN_div_M">。这里把站点标签名映射到统一 label。
# 注意：值必须落在 BLOCK_KEYWORDS 的 key 内，否则会被“勾选区块”过滤掉。
TAB_BLOCK_MAP = {
    "最新电影": "最新电影",
    "国语配音": "最新电影",
    "国语电影": "最新电影",
    "动漫新番": "动画",
    "动画电影": "动画",
    "动漫": "动画",
    "经典高清": "经典高清",
    "最新电视剧更新": "更新电视剧",
    "更新电视剧": "更新电视剧",
    "电视剧": "更新电视剧",
    "日韩剧": "日韩剧",
    "韩剧": "日韩剧",
    "日剧": "日韩剧",
    "美剧": "美剧",
    "欧美剧": "美剧",
    "国剧": "国剧",
    "国产剧": "国剧",
    "港剧": "国剧",
}

# 详情页“分集”判定：链接文字形如 第156集 / 第01集 / 05集
EPISODE_RE_STR = r"第\s*[0-9０-９一二三四五六七八九十百千两]+\s*集|[0-9]{1,4}\s*集"
RED_RE_STR = (
    r"(?i)(?:color\s*[:=]\s*[\"']?(?:red|#f00|#ff0000)|"
    r"style\s*=\s*[\"'][^\"']*color\s*:\s*(?:red|#f00|#ff0000)|"
    r"class\s*=\s*[\"'][^\"']*(?:red|hong)[^\"']*[\"'])"
)

# ---------------------------------------------------------------- 下载器
DOWNLOADER_TYPES = {"qb": "qBittorrent", "tr": "Transmission", "ar": "Aria2"}

HTTP_LINK_MODES = ("ask", "send", "ignore")  # http 链接处理方式
