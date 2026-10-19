"""hao6v / 6v520 老模板站点模块。

把原有 HomeParser + parse_detail_magnets/parse_detail_desc 原样包装成模块，
保证重构后行为零变化。适用：hao6v.cc、6v520.net/cc 及其同模板镜像。
"""
from __future__ import annotations

from ..parser import HomeParser, parse_detail_desc, parse_detail_magnets
from .base import ModuleMeta, SiteModule


class Hao6vModule(SiteModule):
    """6v520/hao6v 家族：首页 tab 区块 + <li> 行 + 日期，详情页磁力/◎简介。"""

    def __init__(self):
        self.meta = ModuleMeta(
            module_id="hao6v",
            name="6v电影（hao6v / 6v520 模板）",
            desc="首页标签页区块更新列表；详情页提取磁力与◎简介",
            entry_mode="mirror",
        )

    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        return HomeParser(html, base_url).parse(include_unknown=include_unknown)

    def parse_detail(self, html: str, item) -> None:
        item.magnets = parse_detail_magnets(html)
        item.desc = parse_detail_desc(html)
