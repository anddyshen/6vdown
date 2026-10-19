"""网盘链接识别与提取（详情页资源分类用）。

电影站/论坛的下载链接形态很杂：
- 磁力：``magnet:?xt=urn:btih:...``
- 种子附件：站内 ``attach-download-*.htm``（无后缀，点击即下载 .torrent）
- 网盘分享：夸克 / 百度 / 阿里云盘 / UC / 天翼 / 迅雷 / 115 /
  微云 / 移动云盘 / 123 云盘 / 蓝奏云 …

网盘链接**不能推送给下载器**（要在浏览器打开、常带提取码），
所以统一归类为 ``pan``：只展示与复制，不可发送。

常见分享地址形态（均已覆盖）：
- 夸克 ``https://pan.quark.cn/s/<id>?pwd=<code>``
- 百度 ``https://pan.baidu.com/s/<id>?pwd=<code>``
- 阿里 ``https://www.aliyundrive.com/s/<id>``、
      ``https://www.alipan.com/s/<id>``
- UC  ``https://drive.uc.cn/s/<id>``
- 天翼 ``https://cloud.189.cn/t/<id>``、
      ``https://cloud.189.cn/web/share?code=<id>``
- 迅雷 ``https://pan.xunlei.com/s/<id>``
- 115  ``https://115.com/s/<id>``
- 微云 ``https://share.weiyun.com/<id>``
- 移动 ``https://caiyun.139.com/m/i?<id>``
- 123  ``https://www.123pan.com/s/<id>``
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import MagnetLink

# 网盘域名（不含 scheme 与子域前缀）
PAN_HOSTS = (
    "pan.quark.cn",      # 夸克网盘
    "aliyundrive.com",   # 阿里云盘
    "alipan.com",        # 阿里云盘（新域名）
    "pan.baidu.com",     # 百度网盘
    "drive.uc.cn",       # UC 网盘
    "cloud.189.cn",      # 天翼云盘
    "pan.xunlei.com",    # 迅雷云盘
    "xunlei.com",        # 迅雷
    "115.com",           # 115 网盘
    "115cdn.com",        # 115 CDN
    "weiyun.com",        # 腾讯微云
    "caiyun.139.com",    # 移动云盘
    "yun.139.com",       # 移动云盘（和彩云）
    "123pan.com",        # 123 云盘
    "lanzou.com",        # 蓝奏云
    "lanzouo.com",       # 蓝奏云（备用域）
    "lanzoux.com",       # 蓝奏云（备用域）
    "cowtransfer.com",   # 奶牛快传
    "wenshushu.cn",      # 文叔叔
)

# 网盘名 → 域名关键词（用于显示 label）
_NETDISK_NAMES = (
    ("夸克网盘", ("pan.quark.cn",)),
    ("阿里云盘", ("aliyundrive.com", "alipan.com")),
    ("百度网盘", ("pan.baidu.com",)),
    ("UC网盘", ("drive.uc.cn",)),
    ("天翼云盘", ("cloud.189.cn",)),
    ("迅雷云盘", ("pan.xunlei.com", "xunlei.com")),
    ("115网盘", ("115.com", "115cdn.com")),
    ("腾讯微云", ("share.weiyun.com", "weiyun.com")),
    ("移动云盘", ("caiyun.139.com", "yun.139.com")),
    ("123云盘", ("123pan.com",)),
    ("蓝奏云", ("lanzou",)),
    ("奶牛快传", ("cowtransfer.com",)),
    ("文叔叔", ("wenshushu.cn",)),
)

_HOST_PATTERN = "|".join(re.escape(h) for h in PAN_HOSTS)

# 正文里的网盘地址（含可选子域前缀与 ?pwd= 等查询参数）
PAN_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:" + _HOST_PATTERN + r")"
    r"/[^\s<>\"'\u3000]*", re.I)

# 提取码 / 访问码 / 密码（正文常另起一行写“提取码：xxxx”）
PWD_RE = re.compile(
    r"(?:提取码|访问码|密码|pwd)\s*[:：=]?\s*([A-Za-z0-9]{4})\b", re.I)


def is_netdisk_url(url: str) -> bool:
    """URL 是否属于已知网盘分享地址。"""
    low = (url or "").strip().lower()
    if not low.startswith(("http://", "https://")):
        return False
    try:
        host = urlparse(low).netloc.split("@")[-1].split(":")[0]
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in PAN_HOSTS)


def netdisk_name(url: str) -> str:
    """按 URL 推断网盘名（用于 label），未识别返回“网盘链接”。"""
    low = (url or "").lower()
    for name, hosts in _NETDISK_NAMES:
        if any(h in low for h in hosts):
            return name
    return "网盘链接"


# 标题里的网盘标记词（用于搜索结果优先展示 / 优先抓详情）
PAN_TITLE_WORDS = (
    "夸克", "网盘", "百度", "阿里", "UC", "天翼", "迅雷", "115",
    "微云", "移动云盘", "和彩云", "123云盘", "蓝奏", "奶牛", "文叔叔",
)


def looks_pan_title(title: str) -> bool:
    """标题是否标记为网盘资源（如 ``[夸克下载]…`` / ``[百度网盘]…``）。

    站点通常把网盘类型写在首个方括号里，故优先只看前缀；无方括号时看全标题。
    """
    t = (title or "").strip()
    if not t:
        return False
    m = re.match(r"^[【\[]([^】\]]+)[】\]]\s*", t)
    head = m.group(1) if m else t
    low = head.lower()
    return any(w.lower() in low for w in PAN_TITLE_WORDS)


def extract_pan_links(html: str, base_url: str = "", title: str = "") -> list:
    """从 HTML 正文提取网盘链接（自动补全提取码），按 URL 去重。"""
    out: list = []
    seen: set = set()
    for m in PAN_URL_RE.finditer(html or ""):
        url = m.group(0).rstrip("，。,.；;）)】]》>")
        if "pwd=" not in url.lower():
            tail = (html or "")[m.end(): m.end() + 80]
            # 只看“下一个网盘链接之前”的文字，避免把后面另一条链接的
            # 提取码错配到当前链接上
            nxt = PAN_URL_RE.search(tail)
            if nxt:
                tail = tail[:nxt.start()]
            pm = PWD_RE.search(tail)
            if pm:
                url += ("&" if "?" in url else "?") + "pwd=" + pm.group(1)
        if url in seen:
            continue
        seen.add(url)
        out.append(MagnetLink(label=netdisk_name(url)[:80], url=url,
                              kind="pan"))
    return out
