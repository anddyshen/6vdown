"""站点首页/详情解析器单测（构造两类模板 HTML）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.site.parser import (  # noqa: E402
    HomeParser,
    parse_detail_desc,
    parse_detail_magnets,
)

HOME_HTML = """<html><body>
<div class="nav"><a href="/">首页</a><a href="/list/1.html">最新电影专区</a></div>
<h2>★2025最新电影★</h2>
<ul>
<li><span class="t">[09-04]</span><a href="/v/12345.html"><font color="red">2026年高分剧情《大地》1080p.HD国语中字</font></a></li>
<li><span class="t">[09-03]</span><a href="/v/12346.html">经典电影《泰坦尼克》4K.HD中英字幕</a></li>
<li><span class="t">[09-02]</span><a href="/v/12347.html">下一页</a></li>
</ul>
<h2><b>经典高清电影</b></h2>
<ul><li><span class="t">[08-26]</span><a href="/v/2233.html">经典爱情片《玫瑰人生》1080p.BD</a></li></ul>
<h2>最新更新的电视剧（红色为推荐）</h2>
<ul><li><a href="/tv/1.html">港剧《龙城岁月》更新至第156集</a><span>[09-04]</span></li></ul>
<div class="foot">版权 © 联系</div>
</body></html>"""

DETAIL_HTML = """<html><head>
<meta name="description" content="◎片 名：大地  ◎年 代：2026  ◎产 地：中国大陆  ◎类 别：剧情">
</head><body>
<div class="zoom">
<a href="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">第01集</a>
<a href="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">第02集</a>
</div></body></html>"""


TABS_HTML = """<html><body>
<div class="col2"><div class="box">
<ul id="tab"><li class="curr" id="tab1_btn_0" onmouseover="etabit(this)">最新电影</li>
<li id="tab1_btn_2" onmouseover="etabit(this)">动漫新番</li></ul>
<ul class="lt" id="tab1_div_0"><li><span>[09-10]</span><a href="/dy/1.html">2025剧情《寻她》4K.HD中字</a></li></ul>
<ul class="lt" id="tab1_div_2" style="display:none;"><li><span>[09-07]</span><a href="/zydy/2.html">《吞噬星空》更新240</a></li></ul>
<h3>★最新更新电视剧★</h3>
<ul id="tab2"><li class="curr" id="tab2_btn_0">最新电视剧更新</li>
<li id="tab2_btn_2" onmouseover="etabit(this)">美剧</li></ul>
<ul class="lt" id="tab2_div_0"><li><span>[09-10]</span><a href="/mj/3.html"><font color='#FF0000'>《足球教练》第四季06</font></a></li></ul>
<ul class="lt" id="tab2_div_2" style="display:none;"><li><span>[09-10]</span><a href="/mj/3.html"><font color='#FF0000'>《足球教练》第四季06</font></a></li></ul>
</div></body></html>"""


class TestHomeParser(unittest.TestCase):
    def test_dates_and_links(self):
        items = HomeParser(HOME_HTML, "https://www.hao6v.cc/").parse()
        urls = [i.detail_url for i in items]
        self.assertEqual(len(items), 4)
        self.assertIn("https://www.hao6v.cc/v/12345.html", urls)
        self.assertIn("https://www.hao6v.cc/tv/1.html", urls)

    def test_blocks(self):
        items = HomeParser(HOME_HTML, "https://www.hao6v.cc/").parse()
        by_url = {i.detail_url: i for i in items}
        self.assertEqual(by_url["https://www.hao6v.cc/v/12345.html"].block, "最新电影")
        self.assertEqual(by_url["https://www.hao6v.cc/v/2233.html"].block, "经典高清")
        self.assertEqual(by_url["https://www.hao6v.cc/tv/1.html"].block, "更新电视剧")

    def test_red_and_classic(self):
        items = HomeParser(HOME_HTML, "https://www.hao6v.cc/").parse()
        by_url = {i.detail_url: i for i in items}
        self.assertTrue(by_url["https://www.hao6v.cc/v/12345.html"].is_red)
        self.assertTrue(by_url["https://www.hao6v.cc/v/12346.html"].is_classic)
        self.assertTrue(by_url["https://www.hao6v.cc/v/2233.html"].is_classic)

    def test_no_unknown_when_disabled(self):
        items = HomeParser(HOME_HTML, "https://www.hao6v.cc/").parse(include_unknown=False)
        self.assertEqual(len(items), 4)


class TestTabBlocks(unittest.TestCase):
    """区块名来自标签按钮（tabN_btn_M ↔ tabN_div_M 配对），而不是 h1-h4。"""

    def _items(self):
        return {i.detail_url: i for i in
                HomeParser(TABS_HTML, "https://www.hao6v.cc/").parse()}

    def test_tab_names_become_blocks(self):
        by_url = self._items()
        self.assertEqual(len(by_url), 3)
        self.assertEqual(by_url["https://www.hao6v.cc/dy/1.html"].block, "最新电影")
        an = by_url["https://www.hao6v.cc/zydy/2.html"]
        self.assertEqual(an.block, "动画")
        self.assertEqual(an.date, "09-07")
        self.assertEqual(an.title, "《吞噬星空》更新240")

    def test_same_link_prefers_specific_block(self):
        """同一链接同时出现在“最新电视剧更新”与“美剧”时，取更具体的“美剧”。"""
        coach = self._items()["https://www.hao6v.cc/mj/3.html"]
        self.assertEqual(coach.block, "美剧")
        self.assertEqual(coach.title, "《足球教练》第四季06")
        self.assertTrue(coach.is_red)


class TestDetailParser(unittest.TestCase):
    def test_magnets_with_episode_labels(self):
        ms = parse_detail_magnets(DETAIL_HTML)
        self.assertEqual(len(ms), 2)
        self.assertEqual(ms[0].label, "第01集")
        self.assertEqual(ms[1].label, "第02集")

    def test_desc(self):
        desc = parse_detail_desc(DETAIL_HTML)
        self.assertIn("大地", desc)
        self.assertIn("◎年", desc)
        self.assertGreater(len(desc), 10)

    def test_various_download_links(self):
        """测试详情页提取 ed2k, thunder, .torrent 等多种下载协议资源。"""
        html = """<div>
        <a href="http://xz.66vod.net:889/2017/test.torrent">全集.1080p.WEB-DL.torrent</a>
        <a href="ed2k://|file|%E7%B9%81%E8%8A%B1.EP01.1080p.mkv|1000|ABC|/">第01集</a>
        <a href="thunder://QUFodHRwOi8veHh4L2FiYy5tcDdaWg==">迅雷高速下载</a>
        <a href="ftp://ygdy8:ygdy8@yg45.dydytt.net:1234/test.mp4">FTP经典电影</a>
        <a href="MAGNET:?dn=Movie.Name&XT=URN:BTIH:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC">大写参数磁力</a>
        </div>"""
        ms = parse_detail_magnets(html)
        self.assertEqual(len(ms), 5)
        self.assertEqual(ms[0].kind, "magnet")
        self.assertEqual(ms[0].label, "大写参数磁力")
        self.assertEqual(ms[1].kind, "ed2k")
        self.assertEqual(ms[1].label, "第01集")
        self.assertEqual(ms[2].kind, "thunder")
        self.assertEqual(ms[2].label, "迅雷高速下载")
        self.assertEqual(ms[3].kind, "torrent")
        self.assertIn("test.torrent", ms[3].url)
        self.assertEqual(ms[4].kind, "ftp")
        self.assertIn("ftp://", ms[4].url)


if __name__ == "__main__":
    unittest.main()
