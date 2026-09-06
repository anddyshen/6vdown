"""站点首页/详情解析器单测（构造两类模板 HTML）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from c2down.site.parser import (  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
