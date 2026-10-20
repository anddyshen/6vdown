"""订阅过滤决策引擎：画质智能决策、已推防重判断、与 Emby 存量差量匹配。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import MagnetLink, ParseItem, Subscription

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _cn_int(s: str) -> int:
    if not s:
        return 0
    if str(s).isdigit():
        return int(s)
    total = 0
    num = 0
    for ch in str(s):
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (num or 1) * unit
            num = 0
        else:
            num = 0
    return total + num


def _ep_meta(name: str) -> tuple[Optional[int], Optional[int]]:
    """从组名提取 (季, 集)。如 S01E05 / 第1季第5集 / 第156集。"""
    text = (name or "").strip()
    s = e = None
    m = re.search(r"[Ss](\d{1,3})\s*[Ee](\d{1,4})", text)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"第\s*([0-9]{1,3}|[一二三四五六七八九十百千两零]+)\s*季", text)
        if m:
            s = _cn_int(m.group(1))
        m = re.search(r"[Ee](\d{1,4})", text)
        if m:
            e = int(m.group(1))
        if e is None:
            m = re.search(r"第\s*([0-9]{1,4}|[一二三四五六七八九十百千两零]+)\s*集", text)
            if m:
                e = _cn_int(m.group(1))
    return s, e


def sort_episode_groups(groups: dict) -> list:
    """多集排序：同一季相邻；季号大在前；同季最新一集（集号大）在前；
    无季号但带集号的按集号倒序；最终尽量保证第一条是“最新一集”。"""
    items = list(groups.items())
    metas = [(nm, *_ep_meta(nm)) for nm, _ in items]
    any_season = any(s is not None for _, s, _ in metas)

    if any_season:
        def key(i):
            s, e = metas[i][1], metas[i][2]
            if s is not None:
                return (0, -s, -(e if e is not None else 0), i)
            if e is not None:
                return (1, 0, -e, i)
            return (2, 0, 0, i)
    else:
        def key(i):
            s, e = metas[i][1], metas[i][2]
            if e is not None:
                return (0, -e, i)
            return (1, 0, i)

    order = sorted(range(len(items)), key=key)
    return [items[i] for i in order]


def detect_quality(text: str) -> str:
    """根据磁力名称/标签识别画质类别 (1080P / 4K / 720P / OTHER)。"""
    t = (text or "").upper()
    if any(k in t for k in ("2160P", "4K", "UHD")):
        return "4K"
    if any(k in t for k in ("1080P", "1080I", "FHD")):
        return "1080P"
    if any(k in t for k in ("720P", "HD")):
        return "720P"
    return "OTHER"


def pick_best_magnet(magnets: list[MagnetLink], priority_order: list[str]) -> tuple[Optional[MagnetLink], str]:
    """根据画质优先级列表（如 ['1080P', '4K', '720P', 'OTHER']）为同一集挑选一条最优磁力。"""
    if not magnets:
        return None, ""
    if len(magnets) == 1:
        q = detect_quality(magnets[0].label)
        return magnets[0], q

    order = priority_order if priority_order else ["1080P", "4K", "720P", "OTHER"]

    # 按检测到的画质分桶
    buckets: dict[str, list[MagnetLink]] = {}
    for m in magnets:
        q = detect_quality(m.label)
        buckets.setdefault(q, []).append(m)

    for target_q in order:
        if target_q in buckets and buckets[target_q]:
            return buckets[target_q][0], target_q

    # 若未能按规则匹配，返回第一条
    first_m = magnets[0]
    return first_m, detect_quality(first_m.label)


def get_quality_options(magnets: list[MagnetLink], priority_order: list[str]) -> list[dict]:
    """获取该集可用的全部画质备选方案（用于快速下拉切换）。"""
    order = priority_order if priority_order else ["1080P", "4K", "720P", "OTHER"]
    # 优先去重相同画质
    buckets: dict[str, list[MagnetLink]] = {}
    for m in magnets:
        q = detect_quality(m.label)
        buckets.setdefault(q, []).append(m)

    options = []
    # 先按优先级放入
    for q in order:
        if q in buckets and buckets[q]:
            options.append({"quality": q, "magnet": buckets[q][0]})
    # 放入其它未在优先级里的画质
    for q, m_list in buckets.items():
        if q not in order and m_list:
            options.append({"quality": q, "magnet": m_list[0]})
    return options


@dataclass
class SubscriptionUpdate:
    """某部订阅剧集的更新检测结果。"""

    sub: Subscription
    item: ParseItem
    latest_candidate: Optional[dict] = None          # 聚焦：最新一集（追新集）
    missing_history: list[dict] = field(default_factory=list) # 回溯：历史漏集列表
    has_emby: bool = False                           # 是否经过了 Emby 差量比对

    @property
    def has_any_update(self) -> bool:
        return bool(self.latest_candidate or self.missing_history)


def analyze_subscription_updates(
    sub: Subscription,
    item: ParseItem,
    is_magnet_pushed_fn: Callable[[int, str], bool],
    is_ep_pushed_fn: Callable[[int, str], bool],
    priority_order: list[str],
    emby_existing: Optional[set[tuple[int, int]]] = None,
) -> Optional[SubscriptionUpdate]:
    """深入分析订阅剧集的更新：
    
    1. 区分【最新一集】与【历史缺失集】；
    2. 无 Emby 模式：对比本地推送历史；
    3. 有 Emby 模式：比对 Emby 库内缺失的剧集。
    """
    if not item.magnets:
        return None

    groups = item.episode_groups()
    if not groups:
        return None

    ordered = sort_episode_groups(groups)
    if not ordered:
        return None

    # 站点当前发布的最新一集的标签名（排在最上面的第一组）
    site_latest_ep_label = ordered[0][0]

    latest_candidate: Optional[dict] = None
    missing_history: list[dict] = []
    has_emby = emby_existing is not None

    for ep_label, m_list in ordered:
        s, e = _ep_meta(ep_label)
        season_num = s if s is not None else 1

        # 仅考虑可下载类型（磁力/种子附件）
        sendable = [m for m in m_list
                    if getattr(m, "kind", "magnet") in ("magnet", "torrent")]
        if not sendable:
            continue

        best_m, best_q = pick_best_magnet(sendable, priority_order)
        if not best_m:
            continue

        # 判断本地或 Emby 是否已拥有此集
        already_have = False
        if has_emby and emby_existing is not None:
            if e is not None and (season_num, e) in emby_existing:
                already_have = True
            else:
                # 若 Emby 没有，还需确认本地是否刚刚推过
                if is_magnet_pushed_fn(sub.id, best_m.url) or is_ep_pushed_fn(sub.id, ep_label):
                    already_have = True
        else:
            # 无 Emby 模式：比对本地推送历史
            if is_magnet_pushed_fn(sub.id, best_m.url) or is_ep_pushed_fn(sub.id, ep_label):
                already_have = True

        if already_have:
            continue

        options = get_quality_options(sendable, priority_order)
        candidate = {
            "sub_id": sub.id,
            "sub_title": sub.title,
            "ep_label": ep_label,
            "season": season_num,
            "episode": e or 0,
            "quality": best_q,
            "magnet_label": (best_m.label or "").strip(),
            "magnet_url": best_m.url,
            "options": options,
            "item": item,
        }

        # 如果正好是站点发布的最新一集
        if ep_label == site_latest_ep_label:
            latest_candidate = candidate
        else:
            # 属于历史漏集
            missing_history.append(candidate)

    # 如果有最新集或历史漏集，返回整合结果
    if latest_candidate or missing_history:
        return SubscriptionUpdate(
            sub=sub,
            item=item,
            latest_candidate=latest_candidate,
            missing_history=missing_history,
            has_emby=has_emby,
        )

    return None


def filter_subscription_updates(
    sub: Subscription,
    item: ParseItem,
    is_pushed_fn: Callable[[int, str], bool],
    priority_order: list[str],
    emby_existing: set[tuple[int, int]] | None = None,
) -> list[dict]:
    """向后兼容接口：提取所有待下载更新（最新集 + 历史集）。"""
    res = analyze_subscription_updates(
        sub=sub,
        item=item,
        is_magnet_pushed_fn=is_pushed_fn,
        is_ep_pushed_fn=lambda _sid, _lbl: False,
        priority_order=priority_order,
        emby_existing=emby_existing,
    )
    if not res:
        return []
    all_items = []
    if res.latest_candidate:
        all_items.append(res.latest_candidate)
    all_items.extend(res.missing_history)
    return all_items
