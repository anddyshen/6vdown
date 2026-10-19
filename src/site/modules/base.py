"""站点解析模块基类与元信息。

每个站点一个模块（内置 Python 模块，或未来的 JSON 规则模块），
统一提供三类能力：
  1) 入口策略：镜像池（hao6v 家族）或实例自带入口列表（分类页站点）；
  2) 列表页解析：HTML → list[ParseItem]；
  3) 详情页解析：填充 item.magnets / item.desc。

SiteParseService 只依赖本接口编排，不关心具体站点结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModuleMeta:
    """模块元信息（设置页/注册表展示用）。"""

    module_id: str                 # 唯一 ID，如 hao6v / dygang / dyg7 / lou1
    name: str                      # 展示名
    desc: str = ""                 # 适用站点说明
    # 入口模式：
    #   mirror  = 使用共享镜像池（mirror_sites），当前→其它可用 自动降级；
    #   entries = 使用站点实例自带的入口地址列表（分类页/版块页站点）。
    entry_mode: str = "mirror"
    default_entry_urls: tuple = ()  # 新建站点实例时的默认入口
    builtin: bool = True           # 是否内置模块（False = 外部 JSON 规则）
    encoding: str = "auto"         # 页面编码：auto / gb18030 / utf-8（POST 搜索等场景）


class SiteModule:
    """站点解析模块接口。子类实现 parse_list / parse_detail 即可。"""

    meta: ModuleMeta
    # 列表页默认抓取页数（1 = 只抓入口页）；需要翻页的模块可覆盖
    max_list_pages = 1

    # ------------------------------------------------------------ 接口
    def parse_list(self, html: str, base_url: str, entry_url: str = "",
                   include_unknown: bool = True) -> list:
        """列表页（首页/分类页/版块页）→ list[ParseItem]。

        base_url 用于把相对链接补全为详情页绝对地址；
        entry_url 为本次抓取的入口地址（多入口站点可按入口归区块）。
        """
        raise NotImplementedError

    def parse_list_pages(self, html: str, base_url: str, entry_url: str = "",
                         fetcher=None, max_pages: int = 1,
                         include_unknown: bool = True) -> list:
        """多页列表抓取（默认只抓入口页；需要翻页的模块覆盖本方法）。

        fetcher 由服务层注入；返回合并去重后的 list[ParseItem]。
        """
        return self.parse_list(html, base_url, entry_url, include_unknown)

    def parse_detail(self, html: str, item: ParseItem) -> None:  # noqa: F821
        """详情页解析：填充 item.magnets / item.desc（失败可留空由补抓兜底）。"""
        raise NotImplementedError

    # ------------------------------------------------------------ 辅助
    def blocks(self) -> list:
        """该模块可能产出的区块 label（设置页勾选过滤用）。"""
        from ... import constants

        return list(constants.BLOCK_KEYWORDS.keys())

    def entry_mode(self) -> str:
        return self.meta.entry_mode
