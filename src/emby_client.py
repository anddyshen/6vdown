"""轻量 Emby 媒体库 API 客户端与连通性检查器。"""
from __future__ import annotations

import re
from typing import Optional
import requests

from .log import get_logger

log = get_logger("emby")


class EmbyClient:
    """Emby 媒体库 REST API 客户端。"""

    def __init__(self, server_url: str = "", api_key: str = ""):
        self.server_url = (server_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()

    def is_configured(self) -> bool:
        return bool(self.server_url and self.api_key)

    def _headers(self) -> dict:
        return {
            "Accept": "application/json",
            "X-Emby-Token": self.api_key,
        }

    def test_connection(self) -> tuple[bool, str]:
        """测试与 Emby 服务器的连接与鉴权。"""
        if not self.is_configured():
            return False, "服务器地址或 API Key 为空"
        url = f"{self.server_url}/System/Info"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                srv_name = data.get("ServerName", "Emby Server")
                version = data.get("Version", "")
                return True, f"连接成功！服务器：{srv_name} (v{version})"
            elif resp.status_code in (401, 403):
                return False, "连接失败：API Key 无效或无权限访问"
            else:
                return False, f"连接失败：HTTP {resp.status_code}"
        except Exception as e:
            return False, f"连接异常：{e}"

    def find_series_episodes(self, series_name: str) -> set[tuple[int, int]]:
        """查找指定剧名在 Emby 中已存在的 (季号, 集号) 集合。
        
        返回值示例：{(1, 1), (1, 2), ..., (2, 5)}
        若无法连接或未搜到，返回空 set。
        """
        if not self.is_configured():
            return set()
        clean_name = re.sub(r"第[0-9一二三四五六七八九十]+季|[Ss]\d+", "", series_name).strip()
        search_term = clean_name if clean_name else series_name

        try:
            # 1. 搜索 SeriesId
            url = f"{self.server_url}/Items"
            params = {
                "IncludeItemTypes": "Series",
                "SearchTerm": search_term,
                "Recursive": "true",
                "Limit": 5,
            }
            resp = requests.get(url, headers=self._headers(), params=params, timeout=5)
            if resp.status_code != 200:
                return set()
            items = resp.json().get("Items", [])
            if not items:
                return set()
            
            series_id = items[0]["Id"]

            # 2. 获取该剧名下所有已入库的集数
            ep_url = f"{self.server_url}/Shows/{series_id}/Episodes"
            ep_resp = requests.get(ep_url, headers=self._headers(), timeout=5)
            if ep_resp.status_code != 200:
                return set()

            existing = set()
            for ep in ep_resp.json().get("Items", []):
                s_num = ep.get("ParentIndexNumber", 1)  # 季号，默认第1季
                e_num = ep.get("IndexNumber")           # 集号
                if e_num is not None:
                    existing.add((int(s_num), int(e_num)))
            return existing
        except Exception as e:
            log.warning("Emby 查询异常: %s", e)
            return set()

