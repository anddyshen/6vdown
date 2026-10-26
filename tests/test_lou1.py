"""BT之家 1lou.me 论坛模块单测（按实测页面结构还原的样本）。

覆盖：
- 版块页列表提取（li.media thread + text-title + forum title + span.date）；
- 桌面/移动双模板去重；置顶公告等非资源版块跳过；
- 版块名 → 区块映射；
- 帖子详情三类资源：磁力 / .torrent 附件（可发送）/ 网盘（仅复制）；
- “回复后可见”标注；简介 ◎ 块提取。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import MagnetLink, ParseItem  # noqa: E402
from src.site.modules import get_module, list_modules  # noqa: E402
from src.site.modules.lou1 import (  # noqa: E402
    Lou1Module, extract_desc, extract_resources, parse_list,
)

SITE = "https://www.1lou.me/"


def _row(tid, title, forum, date, variant="hidden-sm"):
    """还原一个列表行（实测含桌面/移动两套模板）。"""
    return f"""<li class="media thread tap {variant}" data-href="thread-{tid}.htm" data-tid="{tid}">
<div class="media-body">
<div class="subject break-all">
<a href="forum-1.htm" target="_blank" title="{forum}" class="text-secondary small {variant}">[{forum}]</a>
<a href="thread-{tid}.htm" target="_blank" class="text-title">{title}</a>
<span class="text-right small float-right text-grey mr-2">
<span class="haya-post-info-username ">
<a target="_blank" href="user-20918.htm" class="username text-grey mr-1  {variant}" uid="20918">Eddie wang</a>
<span class="date text-grey {variant}" title="发布于 {date} 22:14">{date} 22:14</span>
</span>
<span class="ml-2" title="浏览 9391620"><i class="icon-eye"></i> 9391620</span>
</span>
</div>
</div>
</li>"""


LIST_HTML = f"""<html><head><meta charset="utf-8"><title>BT之家</title></head><body>
<div class="card-body">
<ul class="list-unstyled threadlist mb-0">
{_row(786931, "【2023-12-13】关于：欢迎各位新老会员访问BT之家1LOU站", "站务专区", "2025-06-29")}
{_row(1067906, "[BT下载][导火线@0时盗数][BD-MKV/6G][英语中字][1080p][2026最新]", "最新电影", "2026-10-18")}
{_row(1067906, "[BT下载][导火线@0时盗数][BD-MKV/6G][英语中字][1080p][2026最新]", "最新电影", "2026-10-18", variant="hidden-lg")}
{_row(1067884, "[BT下载][海洋奇缘：启航][BD-MKV/2G][英语中字][1080p]", "高清电影", "2026-10-17")}
{_row(1067878, "[网盘电影][某电影][夸克网盘]", "网盘电影", "2026-10-16")}
</ul>
</div>
</body></html>"""

THREAD_HTML = """<html><head><meta charset="utf-8">
<meta name="description" content="[BT下载][导火线@0时盗数][BD-MKV/6G][英语中字][1080p]">
<title>导火线-BT之家</title></head><body>
<div class="message break-all" isfirst="1">
<p><img src="https://qpic.ws/images/2026/09/06/diFKc8.jpg" border="0" /></p>
<p>◎译　　名　导火线</p><p>◎片　　名　Flash Point</p><p>◎年　　代　2007</p>
<p>◎类　　别　动作</p><p>◎IMDb评分 7.1/10</p>
<p>【下载地址】</p>
<p>磁力：<a href="magnet:?xt=urn:btih:2939e80744cf5d465c27b06d16fd391294fa6ba0">导火线.2007.BD-MKV.6G.mp4</a></p>
<p>附件：<a href="attach-download-12345.htm">导火线.2007.BD-MKV.torrent</a>
<a href="attach-download-12346.htm">封面.jpg</a></p>
<p>网盘：<a href="https://pan.quark.cn/s/abcd1234">夸克网盘</a></p>
</div>
</body></html>"""

HIDDEN_HTML = """<html><head><meta charset="utf-8"><title>隐藏帖</title></head><body>
<div class="message break-all" isfirst="1">
<p>◎片　　名　某电影</p>
<p>本内容需回复后可见，请登录后查看下载链接</p>
</div></body></html>"""


class TestLou1List(unittest.TestCase):
    def setUp(self):
        self.items = parse_list(LIST_HTML, SITE)

    def _by_url(self):
        return {it.detail_url: it for it in self.items}

    def test_basic_and_dedup(self):
        rows = self._by_url()
        self.assertEqual(len(rows), 3, "双模板重复行必须去重")
        it = rows[SITE + "thread-1067906.htm"]
        self.assertEqual(it.title,
                         "[BT下载][导火线@0时盗数][BD-MKV/6G][英语中字][1080p][2026最新]")
        self.assertEqual(it.date, "2026-10-18")
        self.assertEqual(it.block, "最新电影")

    def test_skip_announcements(self):
        """站务专区置顶公告必须被跳过。"""
        urls = set(self._by_url())
        self.assertNotIn(SITE + "thread-786931.htm", urls)

    def test_block_mapping(self):
        rows = self._by_url()
        self.assertEqual(rows[SITE + "thread-1067884.htm"].block, "最新电影")
        self.assertEqual(rows[SITE + "thread-1067878.htm"].block, "最新电影")

    def test_leading_bracket_stripped(self):
        html = f"<ul>{_row(1, '【2026-01-01】测试电影[HD]', '最新电影', '2026-01-01')}</ul>"
        rows = {it.detail_url: it for it in parse_list(html, SITE)}
        self.assertEqual(rows[SITE + "thread-1.htm"].title, "测试电影[HD]")


class TestLou1Detail(unittest.TestCase):
    def setUp(self):
        self.mod = Lou1Module()
        self.item = ParseItem(title="导火线",
                              detail_url=SITE + "thread-1067906.htm")

    def test_resources_three_kinds(self):
        self.mod.parse_detail(THREAD_HTML, self.item)
        kinds = [(m.kind, m.label) for m in self.item.magnets]
        self.assertEqual(len(self.item.magnets), 4)
        self.assertEqual(kinds[0][0], "magnet")
        self.assertEqual(kinds[1][0], "torrent")
        self.assertEqual(kinds[2][0], "pan")   # 非种子附件 → 仅复制
        self.assertEqual(kinds[3][0], "pan")   # 网盘 → 仅复制
        sendable = [m for m in self.item.magnets if m.sendable()]
        self.assertEqual(len(sendable), 2, "磁力+种子附件才可发送")

    def test_resource_urls(self):
        self.mod.parse_detail(THREAD_HTML, self.item)
        urls = [m.url for m in self.item.magnets]
        self.assertIn(SITE + "attach-download-12345.htm", urls)
        self.assertIn("https://pan.quark.cn/s/abcd1234", urls)

    def test_desc_prefers_info_block(self):
        self.mod.parse_detail(THREAD_HTML, self.item)
        self.assertIn("◎译", self.item.desc)
        self.assertIn("导火线", self.item.desc)
        self.assertIn("Flash Point", self.item.desc)

    def test_hidden_thread_note(self):
        item = ParseItem(title="隐藏帖", detail_url=SITE + "thread-1.htm")
        self.mod.parse_detail(HIDDEN_HTML, item)
        self.assertEqual(len(item.magnets), 0)
        self.assertIn("回复后可见", item.desc)

    def test_extract_helpers(self):
        mags = extract_resources(THREAD_HTML, SITE)
        self.assertTrue(all(isinstance(m, MagnetLink) for m in mags))
        self.assertIn("导火线", extract_desc(THREAD_HTML))

    def test_extract_tail_attachments(self):
        """测试在帖子正文 message 之外/网页尾部的附件列表与 .torrent 链接提取。"""
        html = """<html><body>
        <div class="message break-all"><p>这是正文内容</p></div>
        <fieldset class="fieldset"><legend>附件列表：</legend>
        <ul class="attachlist">
          <li aid="382067"><a href="attach-download-382067.htm" target="_blank">繁花.Ep01-10.1080p.WEB-DL.H264.torrent</a></li>
          <li aid="382068"><a href="attach-download-382068.htm" target="_blank"><i class="icon filetype torrent"></i></a> 繁花.Ep11-20.torrent</li>
        </ul>
        </fieldset>
        </body></html>"""
        res = extract_resources(html, SITE, "繁花")
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].url, "https://www.1lou.me/attach-download-382067.htm")
        self.assertEqual(res[0].kind, "torrent")
        self.assertIn("繁花.Ep01-10", res[0].label)
        self.assertEqual(res[1].url, "https://www.1lou.me/attach-download-382068.htm")
        self.assertEqual(res[1].kind, "torrent")
        self.assertIn("繁花.Ep11-20.torrent", res[1].label)


class TestLou1Meta(unittest.TestCase):
    def test_meta_and_registry(self):
        m = Lou1Module()
        self.assertEqual(m.meta.module_id, "lou1")
        self.assertEqual(m.meta.entry_mode, "entries")
        self.assertEqual(m.max_list_pages, 1)
        self.assertEqual(len(m.meta.default_entry_urls), 8)
        self.assertIsNotNone(get_module("lou1"))
        ids = [meta.module_id for meta in list_modules()]
        for mid in ("hao6v", "dygang", "dyg7", "lou1"):
            self.assertIn(mid, ids)


if __name__ == "__main__":
    unittest.main()
