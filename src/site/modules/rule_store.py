"""自定义模块规则存储：data/modules/*.json 读写 / 校验 / 热加载。

目录约定：
- 内置参考规则：src/site/modules/rules/*.json（只读模板，四个内置站点的等价表达）；
- 用户规则：<数据目录>/modules/*.json（可编辑；同 module_id 覆盖内置模块）。

保存前必须通过 validate_rule（必填字段 + 全部正则可编译）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from ... import constants
from .generic import GenericModule, GenericRule

RULES_DIRNAME = "modules"


def rules_dir() -> str:
    """用户规则目录（不存在则创建）。"""
    d = os.path.join(constants.app_data_dir(), RULES_DIRNAME)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def bundled_dir() -> str:
    """内置参考规则目录（随源码/打包分发）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")


def list_rule_files(user_only: bool = True) -> list:
    """规则文件路径列表（用户目录，或含内置参考）。"""
    dirs = [rules_dir()]
    if not user_only:
        dirs.append(bundled_dir())
    out = []
    for d in dirs:
        try:
            for name in sorted(os.listdir(d)):
                if name.lower().endswith(".json"):
                    out.append(os.path.join(d, name))
        except Exception:
            continue
    return out


def load_rule_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def validate_rule(data: dict) -> list:
    """校验规则；返回错误列表（空 = 通过）。"""
    errors: list = []
    if not isinstance(data, dict):
        return ["规则必须是 JSON 对象"]

    module_id = str(data.get("module_id") or "").strip()
    if not module_id:
        errors.append("缺少 module_id（模块唯一 ID，建议英文小写）")
    elif not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", module_id):
        errors.append("module_id 只能包含字母/数字/下划线/连字符（≤40 字符）")
    if not str(data.get("name") or "").strip():
        errors.append("缺少 name（站点显示名）")

    entry_mode = str(data.get("entry_mode") or "entries")
    if entry_mode not in ("entries", "mirror"):
        errors.append("entry_mode 只能是 entries 或 mirror")
    if entry_mode == "entries" and not [
            u for u in (data.get("entry_urls") or []) if str(u).strip()]:
        errors.append("entries 模式至少需要一个 entry_urls 入口地址")

    ex = data.get("extract") or {}
    mode = str(ex.get("mode") or "rows")
    if mode not in ("rows", "date_anchor"):
        errors.append("extract.mode 只能是 rows 或 date_anchor")
    if not str(ex.get("link_re") or "").strip():
        errors.append("缺少 extract.link_re（详情链接正则）")
    if mode == "rows" and not str(ex.get("row_re") or "").strip():
        errors.append("rows 模式必须提供 extract.row_re（行容器正则）")
    if mode == "date_anchor" and not str(ex.get("date_re") or "").strip():
        errors.append("date_anchor 模式必须提供 extract.date_re（日期正则）")

    # 全部正则必须可编译
    for key in ("row_re", "link_re", "title_re", "status_re", "date_re",
                "block_re", "block_row_re", "skip_row_re", "title_qual_re",
                "red_re"):
        pat = str(ex.get(key) or "")
        if pat:
            try:
                re.compile(pat, re.S | re.I)
            except re.error as e:
                errors.append(f"extract.{key} 正则无法编译：{e}")
    de = data.get("detail") or {}
    mag = str(de.get("magnet_re") or "")
    if mag:
        try:
            re.compile(mag, re.I)
        except re.error as e:
            errors.append(f"detail.magnet_re 正则无法编译：{e}")
    if str(de.get("desc_mode") or "meta") not in (
            "meta", "info", "text", "none"):
        errors.append("detail.desc_mode 只能是 meta/info/text/none")

    # 搜索段（可选）：启用则必须给出 url；结果结构缺省沿用 extract
    sr = data.get("search")
    if isinstance(sr, dict) and sr.get("enabled"):
        if not str(sr.get("url") or "").strip():
            errors.append("已启用搜索时 search.url 不能为空")
        if str(sr.get("method") or "POST").upper() not in ("GET", "POST"):
            errors.append("search.method 只能是 GET 或 POST")
        if sr.get("params") is not None and not isinstance(sr["params"], dict):
            errors.append("search.params 必须是对象（表单字段 → 值）")
        rex = sr.get("result")
        if rex is not None and not isinstance(rex, dict):
            errors.append("search.result 必须是对象（结果页提取规则）")
        elif isinstance(rex, dict):
            rmode = str(rex.get("mode") or ex.get("mode") or "rows")
            if rmode not in ("rows", "date_anchor"):
                errors.append("search.result.mode 只能是 rows 或 date_anchor")
            if rmode == "rows" and not str(
                    rex.get("row_re") or ex.get("row_re") or "").strip():
                errors.append("搜索结果 rows 模式必须提供 row_re")
            if rmode == "date_anchor" and not str(
                    rex.get("date_re") or ex.get("date_re") or "").strip():
                errors.append("搜索结果 date_anchor 模式必须提供 date_re")
            for key in ("row_re", "link_re", "title_re", "status_re",
                        "date_re", "block_re", "block_row_re", "skip_row_re",
                        "title_qual_re", "red_re"):
                pat = str(rex.get(key) or "")
                if pat:
                    try:
                        re.compile(pat, re.S | re.I)
                    except re.error as e:
                        errors.append(f"search.result.{key} 正则无法编译：{e}")
    return errors


def rule_from_dict(data: dict) -> GenericRule:
    """dict → GenericRule（先校验，失败抛 ValueError）。"""
    errors = validate_rule(data)
    if errors:
        raise ValueError("；".join(errors[:4]))
    return GenericRule.from_dict(data)


def save_rule(data: dict) -> str:
    """校验并写入用户规则目录，返回文件路径。"""
    rule = rule_from_dict(data)
    path = os.path.join(rules_dir(), f"{rule.module_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rule.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def delete_rule(module_id: str) -> bool:
    path = os.path.join(rules_dir(), f"{module_id}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def load_user_modules() -> list:
    """加载用户规则目录的全部模块（坏规则跳过并记录原因）。"""
    from ...log import get_logger

    log = get_logger("rule_store")
    mods = []
    for path in list_rule_files(user_only=True):
        data = load_rule_file(path)
        if data is None:
            log.warning("规则文件解析失败，已跳过：%s", path)
            continue
        try:
            mods.append(GenericModule(rule_from_dict(data), source=path))
        except Exception as e:
            log.warning("规则无效，已跳过 %s：%s", path, e)
    return mods


def load_bundled_modules() -> list:
    """内置参考规则模块（供设置页“模板/对照”与测试使用）。"""
    mods = []
    for path in list_rule_files(user_only=False):
        if os.path.dirname(path) != bundled_dir():
            continue
        data = load_rule_file(path)
        if data is None:
            continue
        try:
            mods.append(GenericModule(rule_from_dict(data), source="builtin"))
        except Exception:
            continue
    return mods
