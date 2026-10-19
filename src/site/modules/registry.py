"""模块注册表：内置模块注册 / 查询；用户 JSON 规则模块（data/modules）覆盖内置。

新增站点模块两条路：
  1) 内置 Python 模块：在 _register_builtin() 里登记；
  2) 用户规则模块：data/modules/<id>.json（generic 引擎驱动），
     同 module_id 时**覆盖**内置模块（站点改版可先改规则应急）。
"""
from __future__ import annotations

from .base import ModuleMeta, SiteModule
from .dygang import DygangModule
from .dyg7 import Dyg7Module
from .hao6v import Hao6vModule
from .lou1 import Lou1Module

_BUILTIN: dict = {}
_EXTERNAL: dict = {}


def _register_builtin() -> None:
    if _BUILTIN:
        return
    for mod in (Hao6vModule(), DygangModule(), Dyg7Module(), Lou1Module()):
        _BUILTIN[mod.meta.module_id] = mod
    _load_external()


def register_module(module: SiteModule) -> None:
    """注册一个模块实例（内置或外部规则模块共用）。"""
    if not getattr(module, "meta", None) or not module.meta.module_id:
        raise ValueError("模块缺少 meta.module_id")
    _EXTERNAL[module.meta.module_id] = module


def _load_external() -> None:
    """从 data/modules 加载用户规则模块（覆盖同 ID 内置模块）。"""
    try:
        from .rule_store import load_user_modules

        for mod in load_user_modules():
            _EXTERNAL[mod.meta.module_id] = mod
    except Exception:
        pass  # 规则目录异常不影响内置模块


def reload_external_modules() -> int:
    """重新加载用户规则模块（设置页保存/删除后调用）。返回加载数量。"""
    _register_builtin()
    _EXTERNAL.clear()
    _load_external()
    return len(_EXTERNAL)


def get_module(module_id: str):
    """按 ID 取模块；用户规则优先，其次内置；不存在返回 None。"""
    _register_builtin()
    return _EXTERNAL.get(module_id or "") or _BUILTIN.get(module_id or "")


def list_modules() -> list:
    """全部模块元信息（用户规则 + 内置）。"""
    _register_builtin()
    merged = dict(_BUILTIN)
    merged.update(_EXTERNAL)
    return [m.meta for m in merged.values()]


def module_ids() -> list:
    _register_builtin()
    return list(set(_EXTERNAL) | set(_BUILTIN))
