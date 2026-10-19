"""电影港新版 dyg7.com 模块单测（按实测页面结构还原的样本）。

覆盖：
- 分类列表项提取（li.p1 m1 + a.link-hover[title] + p.other 状态）；
- 入口 → 区块映射（国剧/日韩剧/美剧/更新电视剧/短剧/动画/综艺/最新电影）；
- “正片”不并入标题、“更新至N集”等状态并入标题（用于更新判定）；
- 翻页 URL 规则 index_N.html 与“整页无新增即停”；
- 详情页磁力/简介提取；无日期字段（date 为空）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.site.modules import get_module, list_modules  # noqa: E402
from src.site.modules.dyg7 import (  # noqa: E402
    Dyg7Module, block_for_entry, page_url, parse_list,
)

SITE = "https://www.dyg7.com"


def _item(href, name, status="正片"):
    """还原一个列表项（实测嵌套结构）。"""
    return f"""<li class="p1 m1"><a class="link-hover" href="{href}" title="{name}">
<img class="lazy" data-original="https://tu.66tutup.com:667/2026/3990.jpg"
 src="/skin/dygang/images/load.gif" alt="{name}"><span class="video-bg"></span>
<span class="lzbz">
<p class="name">{name}</p>
<p class="actor"></p>
<p class="actor">/</p>
</span>
<p class="other"><i>{status}</i></p>
</a> </li>"""


def _list_page(items, pagination=""):
    return f"""<html><head><meta charset="utf-8"><title>电影港</title></head><body>
<div class="sy-jg mb"><p class="px"><a class="time on" href="/e/action/ListInfo.php">最新</a></p></div>
<div class="index-area clearfix">
<ul>
{''.join(items)}
</ul>
</div>
{pagination}
</body></html>"""


PAGE_MOVIE = _list_page([
    _item("/dy/jqp/25355.html", "登峰传奇：丹增诺盖"),
    _item("/dy/tvplay/25354.html", "阳光舞者"),
    _item("/dy/aqp/25353.html", "一生所爱", status="HD"),
])

PAGE_GUOJU = _list_page([
    _item("/dsj/dlj/25371.html", "醉梦"),
    _item("/dsj/dlj/25370.html", "把黑夜点燃", status="更新至18集"),
])

PAGE_DUANJU = _list_page([_item("/duanju/1001.html", "短剧A", status="全集")])
PAGE_ZONGYI = _list_page([_item("/zyjm/2001.html", "综艺B")])

DETAIL_HTML = """<html><head>
<meta name="description" content="◎片 名：登峰传奇：丹增诺盖 ◎年 代：2026 ◎类 别：剧情">
</head><body>
<div class="ct-l"><p><img src="x.jpg"></p>
<div>◎片　　名：登峰传奇：丹增诺盖</div></div>
<p>【下载地址】</p>
<table><tr><td>磁力：<a href="magnet:?xt=urn:btih:2939e80744cf5d465c27b06d16fd391294fa6ba0">1080p.HD中字.mp4</a></td></tr></table>
</body></html>"""


class TestDyg7Parsing(unittest.TestCase):
    def test_basic_extraction(self):
        items = parse_list(PAGE_MOVIE, SITE, SITE + "/dy/")
        rows = {it.detail_url: it for it in items}
        self.assertEqual(len(items), 3)
        it = rows[SITE + "/dy/jqp/25355.html"]
        self.assertEqual(it.title, "登峰传奇：丹增诺盖")
        self.assertEqual(it.block, "最新电影")
        self.assertEqual(it.date, "", "该站无日期字段，date 必须为空")

    def test_status_merged_into_title(self):
        """正片不并入；HD/更新至N集/全集等状态并入标题（供更新判定）。"""
        rows = {it.detail_url: it for it in
                parse_list(PAGE_GUOJU, SITE, SITE + "/dsj/dlj/")}
        self.assertEqual(rows[SITE + "/dsj/dlj/25371.html"].title, "醉梦")
        self.assertEqual(rows[SITE + "/dsj/dlj/25370.html"].title,
                         "把黑夜点燃（更新至18集）")
        rows2 = {it.detail_url: it for it in
                 parse_list(PAGE_DUANJU, SITE, SITE + "/duanju/")}
        self.assertEqual(rows2[SITE + "/duanju/1001.html"].title, "短剧A（全集）")

    def test_block_mapping(self):
        cases = [
            ("/dy/", "最新电影"),
            ("/dy/jqp/", "最新电影"),
            ("/dsj/dlj/", "国剧"),
            ("/dsj/rhj/", "日韩剧"),
            ("/dsj/omj/", "美剧"),
            ("/dsj/", "更新电视剧"),
            ("/duanju/", "短剧"),
            ("/dongman/", "动画"),
            ("/zyjm/", "综艺"),
            ("/unknown/", "其他"),
        ]
        for path, expect in cases:
            self.assertEqual(block_for_entry(SITE + path), expect, path)

    def test_classic_flag(self):
        html = _list_page([_item("/dy/jqp/1.html", "经典老片 1987")])
        rows = {it.detail_url: it for it in
                parse_list(html, SITE, SITE + "/dy/")}
        self.assertTrue(rows[SITE + "/dy/jqp/1.html"].is_classic)

    def test_page_url(self):
        self.assertEqual(page_url("https://www.dyg7.com/dy/", 2),
                         "https://www.dyg7.com/dy/index_2.html")
        self.assertEqual(page_url("https://www.dyg7.com/dy/", 1), "")
        self.assertEqual(page_url("", 3), "")


class _FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, timeout=18, cache=False):
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError("not found: " + url)
        return self.pages[url], url


class TestDyg7Pagination(unittest.TestCase):
    def test_second_page_appended_and_stops(self):
        mod = Dyg7Module()
        page2 = _list_page([_item("/dy/jqp/25300.html", "旧片1")])
        fetcher = _FakeFetcher({
            "https://www.dyg7.com/dy/index_2.html": page2,
            "https://www.dyg7.com/dy/index_3.html": _list_page([]),
        })
        items = mod.parse_list_pages(PAGE_MOVIE, SITE, SITE + "/dy/",
                                     fetcher=fetcher, max_pages=2)
        urls = {it.detail_url for it in items}
        self.assertIn(SITE + "/dy/jqp/25300.html", urls, "第 2 页新条目应合并")
        self.assertEqual(len(urls), 4)
        self.assertEqual(fetcher.calls,
                         ["https://www.dyg7.com/dy/index_2.html"],
                         "max_pages=2 时只翻一页")

    def test_stops_when_page_has_no_new(self):
        mod = Dyg7Module()
        fetcher = _FakeFetcher({
            "https://www.dyg7.com/dy/index_2.html": PAGE_MOVIE,  # 全是旧条目
        })
        items = mod.parse_list_pages(PAGE_MOVIE, SITE, SITE + "/dy/",
                                     fetcher=fetcher, max_pages=5)
        self.assertEqual(len(items), 3, "整页无新增应停止翻页")
        self.assertEqual(len(fetcher.calls), 1)

    def test_stops_on_fetch_error(self):
        mod = Dyg7Module()
        fetcher = _FakeFetcher({})  # 全部 404
        items = mod.parse_list_pages(PAGE_MOVIE, SITE, SITE + "/dy/",
                                     fetcher=fetcher, max_pages=3)
        self.assertEqual(len(items), 3)


class TestDyg7DetailAndMeta(unittest.TestCase):
    def test_parse_detail(self):
        mod = Dyg7Module()
        from src.models import ParseItem

        it = ParseItem(title="登峰传奇")
        mod.parse_detail(DETAIL_HTML, it)
        self.assertEqual(len(it.magnets), 1)
        self.assertIn("登峰传奇", it.desc)

    def test_meta_and_registry(self):
        m = Dyg7Module()
        self.assertEqual(m.meta.module_id, "dyg7")
        self.assertEqual(m.meta.entry_mode, "entries")
        self.assertEqual(m.max_list_pages, 2)
        self.assertEqual(len(m.meta.default_entry_urls), 8)
        self.assertIsNotNone(get_module("dyg7"))
        ids = [meta.module_id for meta in list_modules()]
        for mid in ("hao6v", "dygang", "dyg7"):
            self.assertIn(mid, ids)


if __name__ == "__main__":
    unittest.main()
