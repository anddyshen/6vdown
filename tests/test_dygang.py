"""电影港 dygang.tv 模块单测（按实测页面结构还原的样本）。

覆盖：
- tab 容器 → 区块标签（按钮编号与容器编号不一致时的退化配对）；
- table 行 + 相邻日期 td 的“日期锚点”提取；
- 裸片名（无画质标记）必须能解析；
- 红链 / 经典标记、同 URL 多区块去重合并；
- 导航/页脚/无标题日期等噪声不得产出条目；
- 模块入口与 registry 行为。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import ParseItem  # noqa: E402
from src.site.modules import get_module, list_modules  # noqa: E402
from src.site.modules.dygang import DygangModule, parse_home  # noqa: E402

SITE = "https://www.dygang.tv/"


def _item(img_href, title_html, date, cls="c2", alt="封面"):
    """还原一个更新行：图片表 + 标题表 + 日期表（实测嵌套 table 布局）。"""
    return f"""
<table width="136" border="0" cellspacing="2" cellpadding="0">
  <tr><td width="132">
    <TABLE class=border1 cellSpacing=0 cellPadding=3 border=0><TBODY><TR><TD>
      <a href='{img_href}' target="_blank"><img src='https://tu.66tutup.com:667/2026/4035.jpg'
         border='0' width='120' height='150' alt='{alt}'></a></TD></TR></TABLE>
    <TABLE border=0 align="center" cellPadding=3 cellSpacing=0><TBODY><TR><TD>
      <a href="{img_href}" target="_blank" class="{cls}">{title_html}</a></TD></TR></TABLE>
    <TABLE border=0 align="center" cellPadding=3 cellSpacing=0><TBODY><TR><TD>
      {date}</TD></TR></TABLE>
  </td></tr></table>"""


HOME_HTML = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN">
<html xmlns="http://www.w3.org/1999/xhtml"><head>
<meta http-equiv="Content-Type" content="text/html; charset=gb2312" />
<title>电影港_高清电影下载_720p高清_1080p高清</title></head>
<body>
<div id="top"><span><a href="https://www.hao6v.cc" target=_blank>6v电影</a> |
<a href="https://www.dygang.me" target=_blank>电影港 地址发布页</a> |
<a href="/e/search/result/?searchid=176303">喜剧片</a></span></div>
<TABLE><TR><TD><a href="/"><IMG src="/images/logo.gif" border=0></a></TD></TR></TABLE>
<ul id="tab1">
<li id="tab1_btn_1" onmouseover="etabit(this)">最新电影(更新)</li>
<li id="tab1_btn_2" onmouseover="etabit(this)">日韩剧(更新)</li></ul>
<div id="tab1_div_0">
<TABLE cellSpacing=0 cellPadding=2 width="100%" align=center border=0><TBODY><TR><TD vAlign=top>
<table width='100%' border='0' cellspacing='0' cellpadding='0'><tr>
<td width='25%'>{_item("/ys/20261018/60778.htm", "偷天父子兵", "2026-10-18")}</td>
<td width='25%'>{_item("/gy/20261017/60770.htm",
                        "<font color='#FF0000'>经典老片 1987</font>", "2026-10-17")}</td>
</tr></table></TD></TR></TABLE>
</div>
<h3>最新电视剧更新</h3>
<div id="tab2_div_0">
<TABLE><TR><TD>{_item("/dsj/20261016/60760.htm", "《测试剧》第05集", "2026-10-16")}</TD></TR></TABLE>
</div>
<div class="footer">
<a href="/sitemap.html">网站地图</a> <a href="/help.html">留言板</a>
Copyright &copy; 2015-2020 All Rights Reserved. 浙ICP备09009508号
<TD>2026-10-10</TD>
</div>
</body></html>"""


class TestDygangParsing(unittest.TestCase):
    def setUp(self):
        self.items = parse_home(HOME_HTML, SITE)

    def _by_url(self):
        return {it.detail_url: it for it in self.items}

    def test_basic_extraction(self):
        rows = self._by_url()
        self.assertIn(SITE + "ys/20261018/60778.htm", rows)
        it = rows[SITE + "ys/20261018/60778.htm"]
        self.assertEqual(it.title, "偷天父子兵")   # 裸片名（无画质标记）也要能解析
        self.assertEqual(it.date, "2026-10-18")
        self.assertEqual(it.block, "最新电影")

    def test_block_from_tab_container(self):
        """容器 tab1_div_0 之前同组第一个按钮 = 最新电影（退化配对）。"""
        rows = self._by_url()
        self.assertEqual(rows[SITE + "ys/20261018/60778.htm"].block, "最新电影")
        self.assertEqual(rows[SITE + "gy/20261017/60770.htm"].block, "最新电影")

    def test_block_from_heading(self):
        rows = self._by_url()
        self.assertEqual(rows[SITE + "dsj/20261016/60760.htm"].block, "更新电视剧")

    def test_red_and_classic_flags(self):
        rows = self._by_url()
        it = rows[SITE + "gy/20261017/60770.htm"]
        self.assertTrue(it.is_red)
        self.assertTrue(it.is_classic)
        plain = rows[SITE + "ys/20261018/60778.htm"]
        self.assertFalse(plain.is_red)
        self.assertFalse(plain.is_classic)

    def test_noise_is_ignored(self):
        """导航/页脚/无标题日期/排除尾词不得产出条目。"""
        urls = set(self._by_url())
        self.assertNotIn(SITE + "sitemap.html", urls)
        self.assertNotIn(SITE + "help.html", urls)
        self.assertNotIn("https://www.hao6v.cc", urls)
        self.assertEqual(len(self.items), 3, "只能解析出 3 条更新记录")

    def test_dedup_merges_flags(self):
        """同一详情 URL 出现在推荐区与更新区：只留一条并合并标记。"""
        dup = HOME_HTML.replace(
            '<h3>最新电视剧更新</h3>',
            _item("/ys/20261018/60778.htm", "偷天父子兵", "2026-10-18")
            + '<h3>最新电视剧更新</h3>')
        rows = {it.detail_url: it for it in parse_home(dup, SITE)}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[SITE + "ys/20261018/60778.htm"].block, "最新电影")

    def test_priority_block_wins(self):
        """同一 URL 先归最新电影、后归日韩剧（更具体）→ 最终日韩剧。"""
        html = HOME_HTML.replace(
            '<h3>最新电视剧更新</h3>',
            '<div id="tab3_div_0">'
            + _item("/ys/20261018/60778.htm", "偷天父子兵", "2026-10-18")
            + '</div><ul><li id="tab3_btn_3">日韩剧</li></ul>'
            + '<h3>最新电视剧更新</h3>')
        # 注意：按钮在容器之后不生效，改为放在容器之前
        html = HOME_HTML.replace(
            '<h3>最新电视剧更新</h3>',
            '<ul><li id="tab3_btn_3">日韩剧</li></ul><div id="tab3_div_0">'
            + _item("/ys/20261018/60778.htm", "偷天父子兵", "2026-10-18")
            + '</div><h3>最新电视剧更新</h3>')
        rows = {it.detail_url: it for it in parse_home(html, SITE)}
        self.assertEqual(rows[SITE + "ys/20261018/60778.htm"].block, "日韩剧")

    def test_truncated_title_completed_by_alt(self):
        """站点会截断列表标题文字；同条目 alt 是完整片名 → 以前缀规则补全。"""
        html = HOME_HTML.replace(
            _item("/ys/20261018/60778.htm", "偷天父子兵", "2026-10-18"),
            _item("/ys/20261018/60778.htm", "登峰传奇：丹增诺", "2026-10-18",
                  alt="登峰传奇：丹增诺盖"))
        rows = {it.detail_url: it for it in parse_home(html, SITE)}
        self.assertEqual(rows[SITE + "ys/20261018/60778.htm"].title,
                         "登峰传奇：丹增诺盖")

    def test_unrelated_alt_not_used(self):
        """alt 与链接文字不是前缀关系时不得替换标题。"""
        rows = {it.detail_url: it for it in parse_home(HOME_HTML, SITE)}
        self.assertEqual(rows[SITE + "ys/20261018/60778.htm"].title, "偷天父子兵")

    def test_module_wrapper(self):
        via_module = DygangModule().parse_list(HOME_HTML, SITE)
        self.assertEqual(
            [(i.title, i.date, i.block, i.detail_url) for i in via_module],
            [(i.title, i.date, i.block, i.detail_url) for i in self.items])

    def test_module_meta(self):
        m = DygangModule()
        self.assertEqual(m.meta.module_id, "dygang")
        self.assertEqual(m.meta.entry_mode, "entries")
        self.assertEqual(list(m.meta.default_entry_urls),
                         ["https://www.dygang.tv/"])

    def test_registry(self):
        self.assertIsNotNone(get_module("dygang"))
        ids = [meta.module_id for meta in list_modules()]
        self.assertIn("dygang", ids)
        self.assertIn("hao6v", ids)

    def test_empty_html(self):
        self.assertEqual(parse_home("", SITE), [])
        self.assertEqual(parse_home("<html><body>无日期</body></html>", SITE), [])

    def test_parse_detail(self):
        m = DygangModule()
        it = ParseItem(title="繁花", detail_url="https://www.dygang.tv/dsj/123.htm")
        html = """<html><body>
        <div id="text">◎简　　介 这是繁花简介</div>
        <table bgcolor="#0099cc"><tr><td>
        <a href="magnet:?xt=urn:btih:abc1234567890abcdef1234567890abcdef12345">繁花.EP01.1080p.mkv</a>
        <a href="https://pan.quark.cn/s/xyz">夸克网盘</a>
        </td></tr></table>
        </body></html>"""
        m.parse_detail(html, it)
        self.assertEqual(len(it.magnets), 2)
        self.assertEqual(it.magnets[0].url, "magnet:?xt=urn:btih:abc1234567890abcdef1234567890abcdef12345")
        self.assertEqual(it.magnets[1].url, "https://pan.quark.cn/s/xyz")


if __name__ == "__main__":
    unittest.main()
