"""站点解析模块包：每个站点一个模块，由 SiteParseService 统一编排。"""
from .base import ModuleMeta, SiteModule
from .registry import get_module, list_modules, module_ids, register_module

__all__ = [
    "ModuleMeta",
    "SiteModule",
    "get_module",
    "list_modules",
    "module_ids",
    "register_module",
]
