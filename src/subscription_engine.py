"""订阅过滤决策引擎：画质智能决策、已推防重判断、与 Emby 存量差量匹配。"""
from __future__ import annotations

import re
from typing import Optional
from .models import MagnetLink, ParseItem, Subscription
from .ui.workbench import _ep_meta


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


def filter_subscription_updates(
    sub: Subscription,
    item: ParseItem,
    is_pushed_fn,
    priority_order: list[str],
    emby_existing: set[tuple[int, int]] | None = None,
) -> list[dict]:
    """对比并提取某部剧新出且尚未下载的磁力任务列表。
    
    返回列表元素格式：
    {
        "sub_id": int,
        "sub_title": str,
        "ep_label": str,       # 如 "第12集"
        "season": int,
        "episode": int,
        "quality": str,        # "1080P"
        "magnet_label": str,
        "magnet_url": str,
        "item": ParseItem,
    }
    """
    if not item.magnets:
        return []

    groups = item.episode_groups()
    new_candidates = []

    for ep_label, m_list in groups.items():
        s, e = _ep_meta(ep_label)
        season_num = s if s is not None else 1
        # 1. 如果配置了 Emby 且查到了该集在 Emby 中已存在，跳过
        if emby_existing and e is not None:
            if (season_num, e) in emby_existing:
                continue

        # 2. 如果该组所有磁力都已在本地推送历史中，跳过
        unpushed = [m for m in m_list if not is_pushed_fn(sub.id, m.url)]
        if not unpushed:
            continue

        # 3. 按画质规则选出一条最佳磁力
        best_m, best_q = pick_best_magnet(unpushed, priority_order)
        if best_m:
            new_candidates.append({
                "sub_id": sub.id,
                "sub_title": sub.title,
                "ep_label": ep_label,
                "season": s or 1,
                "episode": e or 0,
                "quality": best_q,
                "magnet_label": (best_m.label or "").strip(),
                "magnet_url": best_m.url,
                "item": item,
            })

    return new_candidates
