"""模块健康度自检：记录每次解析的条目数与资源命中率，连续异常时提示“可能已改版”。

数据存在 settings 表（key = module_health:<id>），无需新增表。
判定：连续 `WARN_AFTER` 次解析出 0 条 → 标记异常（设置页黄字提示）。
"""
from __future__ import annotations

import json
from typing import Optional

from ...models import now_ms

KEY_PREFIX = "module_health:"
WARN_AFTER = 2          # 连续几次 0 结果算异常
LOW_RATIO = 0.3         # 资源命中率低于此值视为可疑（仅在有详情抓取时判定）


def _empty() -> dict:
    return {"runs": 0, "fails": 0, "last_items": 0,
            "last_ratio": None, "last_at": 0, "warn": False}


def load(db, module_id: str) -> dict:
    """读取模块健康度（缺失返回空记录）。"""
    raw = ""
    try:
        raw = db.get_setting(KEY_PREFIX + (module_id or "")) or ""
    except Exception:
        return _empty()
    if not raw:
        return _empty()
    try:
        data = json.loads(raw)
    except Exception:
        return _empty()
    base = _empty()
    if isinstance(data, dict):
        base.update({k: v for k, v in data.items() if k in base})
    return base


def mark(db, module_id: str, items: int,
         ratio: Optional[float] = None) -> dict:
    """记录一次解析结果，返回更新后的健康度。"""
    info = load(db, module_id)
    info["runs"] = int(info.get("runs") or 0) + 1
    info["last_items"] = int(items or 0)
    info["last_at"] = now_ms()
    if ratio is not None:
        info["last_ratio"] = round(float(ratio), 2)
    if int(items or 0) <= 0:
        info["fails"] = int(info.get("fails") or 0) + 1
    else:
        info["fails"] = 0
    info["warn"] = bool(info["fails"] >= WARN_AFTER
                        or (ratio is not None and ratio < LOW_RATIO
                            and int(items or 0) > 0))
    try:
        db.set_setting(KEY_PREFIX + (module_id or ""),
                       json.dumps(info, ensure_ascii=False))
    except Exception:
        pass
    return info


def reset(db, module_id: str) -> None:
    """清除告警（用户重新分析后调用）。"""
    try:
        db.set_setting(KEY_PREFIX + (module_id or ""), "")
    except Exception:
        pass


def unhealthy(db, module_ids: Optional[list] = None) -> list:
    """返回异常模块 [(module_id, info)]。"""
    out = []
    for mid in (module_ids or []):
        info = load(db, mid)
        if info.get("warn"):
            out.append((mid, info))
    return out


def describe(info: dict) -> str:
    """健康度 → 一句人话（设置页展示）。"""
    if not info or not info.get("runs"):
        return "尚未解析"
    if info.get("warn"):
        if info.get("last_ratio") is not None and info["last_ratio"] < LOW_RATIO:
            return (f"异常：最近一次 {info['last_items']} 条，"
                    f"资源命中率仅 {info['last_ratio']}")
        return f"异常：连续 {info['fails']} 次解析到 0 条（站点可能已改版）"
    extra = ""
    if info.get("last_ratio") is not None:
        extra = f"，资源命中率 {info['last_ratio']}"
    return f"正常：最近 {info['last_items']} 条{extra}"
