"""轻量 Emby 媒体库 API 客户端与连通性检查器。"""
from __future__ import annotations

import re
from typing import Optional
import requests

from .log import get_logger

log = get_logger("emby")


def clean_series_name(raw: str) -> list[str]:
    """从网页标题/订阅标题提取用于在 Emby 中搜索的可能剧名（按优先级排序）。"""
    candidates: list[str] = []
    text = (raw or "").strip()
    if not text:
        return candidates

    # 1. 优先提取《...》或【...】内部文本
    for pattern in (r"《([^》]+)》", r"【([^】]+)】", r"\[([^\]]+)\]"):
        m = re.search(pattern, text)
        if m:
            inner = m.group(1).strip()
            # 剥离内部可能存在的季数，如 《曼达洛人 第一季》 -> 曼达洛人
            inner_no_s = re.sub(r"(?:第\s*[0-9一二三四五六七八九十]+\s*季|[Ss]\d+).*", "", inner).strip()
            if inner_no_s and inner_no_s not in candidates:
                candidates.append(inner_no_s)
            if inner and inner not in candidates:
                candidates.append(inner)

    # 2. 剥离影视前缀分类词（美剧/韩剧/日剧/国剧/泰剧/台剧/英剧/港剧/日韩剧/欧美剧/动漫/电视剧/连续剧/纪录片/动画/综艺）
    t = re.sub(
        r"^(?:美剧|韩剧|日剧|国剧|泰剧|台剧|英剧|港剧|日韩剧|欧美剧|动漫|电视剧|连续剧|纪录片|动画|综艺)",
        "",
        text,
    ).strip()
    # 剥离各种括号
    t = re.sub(r"[《》【】\[\]\(\)]", "", t).strip()
    # 剥离季号及之后部分
    t_no_s = re.sub(r"(?:第\s*[0-9一二三四五六七八九十]+\s*季|[Ss]\d+).*", "", t).strip()
    # 剥离尾部集数，如 08 / 全39集 / 第12集 / 01-02
    t_no_s = re.sub(
        r"(?:第\s*[0-9一二三四五六七八九十]+\s*[集话期]|[0-9]{1,4}\s*[集话期]|全\s*[0-9]+\s*[集话期]|[0-9]{1,4}(?:-[0-9]{1,4})?)$",
        "",
        t_no_s,
    ).strip()

    if t_no_s and t_no_s not in candidates:
        candidates.append(t_no_s)
    if t and t not in candidates and t != t_no_s:
        candidates.append(t)

    return candidates


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

    def find_series(self, series_name: str) -> Optional[dict]:
        """按剧名多策略搜索 Emby 中的剧集信息。返回 Series Item 字典或 None。"""
        if not self.is_configured():
            return None
        cands = clean_series_name(series_name)
        if not cands:
            cands = [series_name.strip()]

        for term in cands:
            url = f"{self.server_url}/Items"
            params = {
                "IncludeItemTypes": "Series",
                "SearchTerm": term,
                "Recursive": "true",
                "Limit": 5,
            }
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=5)
                if resp.status_code == 200:
                    items = resp.json().get("Items", [])
                    if items:
                        # 精确匹配优先
                        for it in items:
                            if it.get("Name", "").strip().lower() == term.lower():
                                return it
                        return items[0]
            except Exception as e:
                log.warning("Emby 搜索剧集异常 (%s): %s", term, e)
        return None

    def get_series_episodes_by_id(self, series_id: str) -> Optional[set[tuple[int, int]]]:
        """获取指定 Series ID 名下所有已入库的 (季号, 集号) 集合。"""
        if not self.is_configured() or not series_id:
            return None
        try:
            ep_url = f"{self.server_url}/Shows/{series_id}/Episodes"
            ep_resp = requests.get(ep_url, headers=self._headers(), timeout=5)
            if ep_resp.status_code != 200:
                return None

            existing: set[tuple[int, int]] = set()
            for ep in ep_resp.json().get("Items", []):
                s_num = ep.get("ParentIndexNumber", 1)  # 季号，默认第1季
                e_num = ep.get("IndexNumber")           # 集号
                if e_num is not None:
                    existing.add((int(s_num), int(e_num)))
            return existing
        except Exception as e:
            log.warning("Emby 查询剧集集数异常 (ID=%s): %s", series_id, e)
            return None

    def find_series_episodes(
        self, series_name: str, series_id: Optional[str] = None
    ) -> Optional[set[tuple[int, int]]]:
        """查找指定剧名在 Emby 中已存在的 (季号, 集号) 集合。
        
        返回值：
        - 若找到对应剧集，返回已入库集数集合 set[tuple[int, int]]（如 {(1, 1), (2, 8)...}）；
        - 若在 Emby 中未匹配到此剧，返回 None（让外部区分“剧集未入库”与“在库但集数为空”）。
        """
        if not self.is_configured():
            return None

        target_id = series_id
        if not target_id:
            s_item = self.find_series(series_name)
            if s_item:
                target_id = str(s_item.get("Id", ""))

        if not target_id:
            return None

        return self.get_series_episodes_by_id(target_id)


