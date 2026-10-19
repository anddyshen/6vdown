"""关键词搜索单测：搜索请求描述（search_spec）与结果解析（parse_search）。

不依赖真实网络：结果页样本按实测结构内联，请求用假抓取器。
覆盖：
- 四个内置模块的搜索入口（URL / 方法 / 表单参数 / 编码）；
- 搜索结果页解析（标题、日期、详情 URL、区块归属）；
- 分页抓取与跨页去重、结果上限；
- 规则模块（generic）的 search 段与结果规则覆盖；
- 服务层 search() 汇总与搜索历史。
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database  # noqa: E402
from src.models import MagnetLink, ParseItem  # noqa: E402
from src.site.fetcher import SiteFetcher  # noqa: E402
from src.site.modules import get_module, register_module  # noqa: E402
from src.site.modules.base import ModuleMeta, SearchSpec, SiteModule  # noqa: E402
from src.site.modules.generic import GenericModule, GenericRule  # noqa: E402
from src.site.modules.registry import reload_external_modules  # noqa: E402
from src.site.modules.rule_store import validate_rule  # noqa: E402
from src.site.service import SiteParseService, _resource_key  # noqa: E402

# ---------------------------------------------------------------- 样本
# hao6v：标题链接在 <span class="blue14"> 内，href 不带引号，日期在随后单元格
HAO6V_HTML = """
<table width="100%" border="0" align="center" cellpadding="3" cellspacing="1">
  <tr><td height="25">系统搜索到约有<strong>8</strong>项符合<strong>阿凡达</strong>的查询结果</td></tr>
</table>
<table width="100%" border="0" align="center" cellpadding="3" cellspacing="1">
  <tr>
    <td width="41%" height="25"><font color="#663333">・[<a href=/dy/>2026最新电影</a>]<span class="blue14"><a href=/dy/2026-03-29/49243.html target=_blank><font color='#FF0000'>2025高分科幻《阿凡达：火与烬》1080p.国英双语.BD中英双字</font></a></span></font></td>
    <td width="59%"><font color="#666666">发布时间：2026-05-21 17:30:38</font></td>
  </tr>
  <tr><td>◎译　　名　阿凡达：火与烬</td></tr>
  <tr><td><a href="/dy/2026-03-29/49243.html" target="_blank">/dy/2026-03-29/49243.html</a></td></tr>
</table>
<table width="100%" border="0" align="center" cellpadding="3" cellspacing="1">
  <tr>
    <td width="41%" height="25"><font color="#663333">・[<a href=/dy/>2026最新电影</a>]<span class="blue14"><a href=/dy/2025-11-07/48219.html target=_blank>2025纪录片《火与水：阿凡达电影制作特辑》1080p.HD中字</a></span></font></td>
    <td width="59%"><font color="#666666">发布时间：2025-11-09 14:23:19</font></td>
  </tr>
</table>
"""

# dygang：图片链接（含 alt） → 日期 → 标题链接(class=classlinkclass)
DYGANG_HTML = """
<table width='100%' border='0' cellspacing='0' cellpadding='0'><tr>
  <td width='50%'><table width="388" border="0" cellspacing="2" cellpadding="0">
    <tr>
      <td width="132" rowspan="2"><table class="border1" cellspacing="0" cellpadding="3" border="0"><tbody><tr><td>
        <a href="/ys/20260329/59392.htm" target="_blank"><img src="https://tu.66tutup.com:667/2025/6973.jpg" alt="阿凡达：火与烬" width="120" height="150" border="0" /></a></td></tr></tbody></table>
        <table border="0" align="center" cellpadding="3" cellspacing="0"><tbody><tr><td>2026-05-21</td></tr></tbody></table></td>
      <td width="250"><a href="/ys/20260329/59392.htm" target="_blank" class="classlinkclass">阿凡达：火与烬</a></td>
    </tr>
    <tr><td valign="top">简介：◎译　　名　阿凡达：火与烬</td></tr>
  </table></td>
  <td width='50%'><table width="388" border="0" cellspacing="2" cellpadding="0">
    <tr>
      <td width="132" rowspan="2"><table class="border1" cellspacing="0" cellpadding="3" border="0"><tbody><tr><td>
        <a href="/jilupian/20251109/58371.htm" target="_blank"><img src="https://tu.66tutup.com:667/2025/3803.jpg" alt="火与水" width="120" height="150" border="0" /></a></td></tr></tbody></table>
        <table border="0" align="center" cellpadding="3" cellspacing="0"><tbody><tr><td>2025-11-09</td></tr></tbody></table></td>
      <td width="250"><a href="/jilupian/20251109/58371.htm" target="_blank" class="classlinkclass">火与水：阿凡达电影制作特辑</a></td>
    </tr>
  </table></td>
</tr></table>
"""

# dyg7：搜索结果与分类列表页同构（li.p1 m1 + p.name + p.other）
DYG7_HTML = """
<ul>
  <li class="p1 m1"><a class="link-hover" href="/dy/khp/23252.html" title="阿凡达：火与烬"><img class="lazy" data-original="x.jpg" src="load.gif" alt="阿凡达：火与烬"><span class="video-bg"></span><span class="lzbz">
        <p class="name">阿凡达：火与烬</p>
        <p class="actor"></p>
        <p class="actor">/</p>
        </span>
        <p class="other"><i>正片</i></p>
        </a> </li>
  <li class="p1 m1"><a class="link-hover" href="/dy/jlp/22927.html" title="火与水：阿凡达电影制作特辑"><img class="lazy" data-original="y.jpg" src="load.gif" alt="火与水"><span class="video-bg"></span><span class="lzbz">
        <p class="name">火与水：阿凡达电影制作特辑</p>
        <p class="actor">/</p>
        </span>
        <p class="other"><i>HD</i></p>
        </a> </li>
</ul>
"""

LOU1_JSON = """
{"ok": true, "data": {"query": "阿凡达", "page": 1, "page_size": 50,
 "total": 317, "hits": [
  {"tid": 260277, "fid": 3, "subject": "阿凡达.Avatar (2009) 1080p Bluray",
   "username": "HjybHq", "create_date": 1702155588, "views": 5199,
   "posts": 0, "files": 1, "thread_url": "/thread-260277.htm"},
  {"tid": 262710, "fid": 17, "subject": "阿凡达：水之道[2160p]",
   "username": "G2W59L", "create_date": 1702161824, "views": 7243,
   "posts": 0, "files": 2, "thread_url": "/thread-262710.htm"}
 ]}}
"""


class _FakeFetcher:
    """按 (url, data) 返回预设页面，并记录请求。"""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls = []

    def get(self, url, timeout=18, cache=False, encoding=None):
        self.calls.append(("GET", url, encoding))
        return self.pages.get(url, ""), url

    def post(self, url, data=None, timeout=18, encoding=None, referer="",
             cache=False, headers=None):
        self.calls.append(("POST", url, encoding))
        return self.pages.get(url, ""), url


class TestSearchSpec(unittest.TestCase):
    """各模块搜索请求描述。"""

    def test_hao6v_post_gb2312(self):
        spec = get_module("hao6v").search_spec("阿凡达")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.method, "POST")
        self.assertTrue(spec.url.endswith("/e/search/index.php"))
        self.assertEqual(spec.data.get("keyboard"), "阿凡达")
        self.assertEqual(spec.data.get("tbname"), "article")
        self.assertEqual(spec.data.get("tempid"), "1")
        self.assertEqual(spec.encoding, "gb2312")
        self.assertTrue(spec.referer)

    def test_dygang_post_gb2312(self):
        spec = get_module("dygang").search_spec("阿凡达")
        self.assertEqual(spec.method, "POST")
        self.assertTrue(spec.url.startswith("https://www.dygang.tv/"))
        self.assertEqual(spec.data.get("keyboard"), "阿凡达")
        self.assertEqual(spec.encoding, "gb2312")

    def test_dyg7_post_utf8(self):
        spec = get_module("dyg7").search_spec("阿凡达")
        self.assertEqual(spec.method, "POST")
        self.assertTrue(spec.url.startswith("https://www.dyg7.com/"))
        self.assertEqual(spec.data.get("keyboard"), "阿凡达")
        self.assertEqual(spec.encoding, "utf-8")

    def test_lou1_get_json_api(self):
        spec = get_module("lou1").search_spec("阿凡达", page=3)
        self.assertEqual(spec.method, "GET")
        self.assertTrue(spec.url.endswith("search/api/search.php"))
        self.assertEqual(spec.data.get("q"), "阿凡达")
        self.assertEqual(spec.data.get("page"), "3")

    def test_paging_adds_page_param(self):
        first = get_module("dygang").search_spec("X", page=1)
        second = get_module("dygang").search_spec("X", page=2)
        self.assertNotIn("page", first.data)
        self.assertEqual(second.data.get("page"), "2")

    def test_base_module_has_no_search(self):
        from src.site.modules.base import SiteModule

        class _Bare(SiteModule):
            pass

        self.assertFalse(_Bare.supports_search)
        self.assertIsNone(_Bare().search_spec("x"))
        self.assertEqual(_Bare().search("x", None), [])


class TestParseSearchResults(unittest.TestCase):
    """结果页解析：标题 / 日期 / 详情 URL。"""

    def test_hao6v(self):
        items = get_module("hao6v").parse_search(HAO6V_HTML,
                                                  "https://www.hao6v.cc/")
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertIn("阿凡达：火与烬", first.title)
        self.assertEqual(first.date, "2026-05-21")
        self.assertEqual(first.detail_url,
                         "https://www.hao6v.cc/dy/2026-03-29/49243.html")
        self.assertTrue(first.is_red)       # 标题带 <font color='#FF0000'>
        self.assertEqual(first.block, "最新电影")

    def test_hao6v_ignores_nav_links(self):
        html = ("<div id='header'><a href='/dy/2012-12-07/19512.html'>"
                "公告区</a></div>" + HAO6V_HTML)
        items = get_module("hao6v").parse_search(html,
                                                  "https://www.hao6v.cc/")
        self.assertEqual(len(items), 2)
        self.assertNotIn("公告区", [i.title for i in items])

    def test_dygang(self):
        items = get_module("dygang").parse_search(DYGANG_HTML,
                                                  "https://www.dygang.tv/")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "阿凡达：火与烬")
        self.assertEqual(items[0].date, "2026-05-21")
        self.assertTrue(items[0].detail_url.endswith("/ys/20260329/59392.htm"))

    def test_dyg7(self):
        items = get_module("dyg7").parse_search(DYG7_HTML,
                                                "https://www.dyg7.com/")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "阿凡达：火与烬")
        self.assertTrue(items[0].detail_url.endswith("/dy/khp/23252.html"))

    def test_lou1_json(self):
        items = get_module("lou1").parse_search(LOU1_JSON,
                                                "https://www.1lou.me/")
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0].detail_url.endswith("/thread-260277.htm"))
        want = time.strftime("%Y-%m-%d", time.localtime(1702155588))
        self.assertEqual(items[0].date, want)          # create_date → 本地日期
        self.assertEqual(items[0].block, "最新电影")       # fid=3
        self.assertEqual(items[1].block, "动画")           # fid=17

    def test_lou1_bad_json_returns_empty(self):
        self.assertEqual(get_module("lou1").parse_search("not json", "x"), [])


class TestSearchPaging(unittest.TestCase):
    """search() 的分页、取消与去重。"""

    def test_merges_pages_and_dedupes(self):
        page1 = DYG7_HTML
        page2 = DYG7_HTML.replace("23252", "99999").replace("阿凡达：火与烬",
                                                           "其它片名")
        m = get_module("dyg7")
        # 直接喂两页：第一次返回 page1，第二次返回 page2
        seq = [page1, page2]

        class _SeqFetcher:
            calls = []

            def get(self, *a, **k):
                return "", ""

            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                _SeqFetcher.calls.append(dict(data))
                return seq[min(len(_SeqFetcher.calls) - 1, len(seq) - 1)], url

        items = m.search("阿凡达", _SeqFetcher(), max_pages=2)
        urls = [i.detail_url for i in items]
        self.assertEqual(len(urls), len(set(urls)))     # 跨页无重复
        self.assertEqual(len(items), 3)                 # 2 + 1 条新增
        self.assertIn("page", _SeqFetcher.calls[1])     # 第 2 页带 page 参数

    def test_stop_when_page_has_no_new_item(self):
        class _SameFetcher:
            n = 0

            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                _SameFetcher.n += 1
                return DYG7_HTML, url

        m = get_module("dyg7")
        items = m.search("阿凡达", _SameFetcher(), max_pages=5)
        self.assertEqual(len(items), 2)                 # 第 2 页无新增即停
        self.assertEqual(_SameFetcher.n, 2)

    def test_cancel_stops_immediately(self):
        class _CancelFetcher:
            n = 0

            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                _CancelFetcher.n += 1
                return DYG7_HTML, url

        m = get_module("dyg7")
        items = m.search("阿凡达", _CancelFetcher(), max_pages=3,
                       cancel=lambda: True)
        self.assertEqual(items, [])
        self.assertEqual(_CancelFetcher.n, 0)


class TestGenericSearchRule(unittest.TestCase):
    """规则模块的 search 段。"""

    def _rule(self, search: dict) -> GenericRule:
        data = {
            "module_id": "demo", "name": "demo", "encoding": "utf-8",
            "entry_mode": "entries", "entry_urls": ["https://demo.example/"],
            "extract": {"mode": "rows", "row_re": r"<li>(.*?)</li>",
                        "link_re": r'href="([^"]+\.html)"'},
            "detail": {"desc_mode": "meta"},
            "search": search,
        }
        self.assertEqual(validate_rule(data), [])
        return GenericRule.from_dict(data)

    def test_disabled_by_default(self):
        rule = GenericRule.from_dict({
            "module_id": "demo", "name": "demo",
            "extract": {"mode": "rows", "row_re": "x", "link_re": "y"}})
        self.assertFalse(GenericModule(rule).supports_search)

    def test_get_with_placeholders(self):
        rule = self._rule({
            "enabled": True, "url": "https://demo.example/search.php",
            "method": "GET",
            "params": {"q": "{keyword}", "page": "{page}"}})
        mod = GenericModule(rule)
        self.assertTrue(mod.supports_search)
        spec = mod.search_spec("阿凡达", page=2)
        self.assertEqual(spec.method, "GET")
        self.assertEqual(spec.data["q"], "阿凡达")
        self.assertEqual(spec.data["page"], "2")

    def test_result_rule_overrides_extract(self):
        rule = self._rule({
            "enabled": True, "url": "https://demo.example/search.php",
            "method": "POST", "params": {"keyboard": "{keyword}"},
            "encoding": "utf-8",
            "result": {"mode": "rows", "row_re": r"<div class=\"it\">(.*?)</div>",
                       "link_re": r'href="([^"]+\.html)"'}})
        mod = GenericModule(rule)
        html = ('<div class="it"><a href="/a/1.html">条目一</a></div>'
                '<li><a href="/b/2.html">不该被匹配</a></li>')
        items = mod.parse_search(html, "https://demo.example/")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "条目一")

    def test_validate_rejects_bad_search(self):
        data = {"module_id": "demo", "name": "demo",
                "extract": {"mode": "rows", "row_re": "x", "link_re": "y"},
                "search": {"enabled": True}}
        self.assertTrue(any("search.url" in e for e in validate_rule(data)))


class TestServiceSearch(unittest.TestCase):
    """服务层编排：汇总、不支持搜索的站点、历史记录。"""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db = Database(path=os.path.join(self._dir, "t.db"))

    def test_empty_keyword(self):
        svc = SiteParseService(self.db, _FakeFetcher({}))
        res = svc.search("   ")
        self.assertFalse(res["ok"])
        self.assertTrue(res["errors"])

    def test_history_recorded(self):
        class _Fetcher(_FakeFetcher):
            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                return DYG7_HTML, url

        svc = SiteParseService(self.db, _Fetcher({}))
        res = svc.search("阿凡达", min_interval=0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 2)
        self.assertIn("阿凡达", self.db.list_search_history())

    def test_history_cleared(self):
        class _Fetcher(_FakeFetcher):
            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                return DYG7_HTML, url

        svc = SiteParseService(self.db, _Fetcher({}))
        svc.search("阿凡达", min_interval=0)
        self.db.clear_search_history()
        self.assertEqual(self.db.list_search_history(), [])


class TestLou1ResourceKind(unittest.TestCase):
    """1LOU 详情页：种子附件（可发送）与网盘（仅复制）的区分。"""

    HTML = (
        '<div class="message break-all">'
        '<a href="attach-download-3000427.htm">沙丘.2021.2160p.torrent</a>'
        '<a href="https://pan.quark.cn/s/abc">夸克网盘</a>'
        '<a href="attach-download-999.htm">阿里云盘</a>'
        '<p>◎译　　名　沙丘</p>'
        '</div>')

    def test_classify_attach(self):
        from src.site.modules.lou1 import classify_attach

        self.assertEqual(classify_attach("xx.torrent",
                                        "attach-download-1.htm"), "torrent")
        self.assertEqual(classify_attach("夸克网盘",
                                        "https://pan.quark.cn/s/x"), "pan")
        # 站内附件无后缀 → 默认按种子处理（点击即下载 .torrent）
        self.assertEqual(classify_attach("电影名",
                                        "https://www.1lou.me/"
                                        "attach-download-3000427.htm"),
                         "torrent")

    def test_extract_resources(self):
        from src.site.modules.lou1 import extract_resources

        got = extract_resources(self.HTML, "https://www.1lou.me/")
        kinds = [m.kind for m in got]
        self.assertEqual(kinds, ["torrent", "pan", "pan"])
        self.assertEqual([m.sendable() for m in got],
                         [True, False, False])

    def test_desc_from_message(self):
        from src.site.modules.lou1 import extract_desc

        self.assertIn("◎译", extract_desc(self.HTML))

    def test_plain_text_pan_url(self):
        """网盘地址常写成纯文本（不在 <a href> 里），也必须能提取。"""
        from src.site.modules.lou1 import extract_resources

        html = ('<div class="message break-all">'
                '<p>链接：https://pan.quark.cn/s/6e2d268cc722</p>'
                '<p>提取码：abcd</p></div>'
                '<div class="footer"><a href="https://pan.quark.cn/s/nav">'
                '导航里的不相关链接</a></div>')
        got = extract_resources(html, "https://www.1lou.me/")
        pan = [m for m in got if m.kind == "pan"]
        self.assertEqual(len(pan), 1)
        # 正文里的“提取码：abcd”会自动补成 ?pwd=abcd
        self.assertEqual(pan[0].url,
                         "https://pan.quark.cn/s/6e2d268cc722?pwd=abcd")

    def test_three_common_pan_formats(self):
        """夸克 / 百度（带 pwd）/ 阿里云盘（带 www）三种最常见格式。"""
        from src.site.modules.lou1 import extract_resources

        html = (
            '<div class="message break-all">'
            '<p>1、夸克下载  '
            'https://pan.quark.cn/s/217fc8fd1ded?pwd=4wLk</p>'
            '<p>2、百度下载  '
            'https://pan.baidu.com/s/1bi9UnCcRO2FA7Akm8SNzpA?pwd=1111</p>'
            '<p>3、阿里云盘 '
            'https://www.aliyundrive.com/s/a6EGG8d8sF1</p>'
            '</div>')
        got = extract_resources(html, "https://www.1lou.me/")
        urls = [m.url for m in got if m.kind == "pan"]
        self.assertEqual(len(urls), 3)
        self.assertIn("https://pan.quark.cn/s/217fc8fd1ded?pwd=4wLk", urls)
        self.assertIn(
            "https://pan.baidu.com/s/1bi9UnCcRO2FA7Akm8SNzpA?pwd=1111", urls)
        self.assertIn("https://www.aliyundrive.com/s/a6EGG8d8sF1", urls)

    def test_pwd_appended_from_text(self):
        """URL 没带 pwd、正文另起一行写“提取码：xxxx”时自动补上。"""
        from src.site.modules.lou1 import extract_resources

        html = ('<div class="message break-all">'
                '<p>百度网盘 https://pan.baidu.com/s/1abcDEF</p>'
                '<p>提取码：9x2k</p></div>')
        got = extract_resources(html, "https://www.1lou.me/")
        pan = [m.url for m in got if m.kind == "pan"]
        self.assertEqual(pan, ["https://pan.baidu.com/s/1abcDEF?pwd=9x2k"])

    def test_pan_title_prefix(self):
        from src.ui.search_page import _is_pan

        self.assertTrue(_is_pan("[夸克下载][阿凡达][4K]"))
        self.assertTrue(_is_pan("[网盘电影][某电影]"))
        self.assertFalse(_is_pan("【2026-01-01】阿凡达.Avatar"))
        self.assertFalse(_is_pan("阿凡达.Avatar 1080p"))


class TestLou1PanBoardSearch(unittest.TestCase):
    """1LOU 搜索要补搜网盘版块（fid=13/14），且网盘条目排在最前。

    实测：全站搜索按时间倒序，普通种子帖会挤满前几页，
    搜“阿凡达”前 50 条 0 条网盘，而网盘电影版块有 6 条。
    """

    def _hits(self, tid, fid, subject):
        return {"tid": tid, "fid": fid, "subject": subject,
                "thread_url": "thread-%d.htm" % tid, "create_date": 0}

    def test_searches_pan_boards_and_puts_pan_first(self):
        from src.site.modules import get_module

        normal = self._hits(1, 1, "阿凡达.Avatar.2009.1080p.BluRay")
        pan13_1 = self._hits(2, 13, "[夸克下载][阿凡达][全2部]")
        pan13_2 = self._hits(3, 13, "[夸克下载][阿凡达：水之道]")
        pan14 = self._hits(4, 14, "[夸克下载][火与水：阿凡达特辑]")

        class _Fetcher:
            def __init__(self):
                self.urls = []

            def get(self, url, encoding=None, **kw):
                self.urls.append(url)
                if "fid=13" in url:
                    hits = [pan13_1, pan13_2]
                elif "fid=14" in url:
                    hits = [pan14]
                else:
                    hits = [normal]
                return json.dumps({"ok": True, "data": {"hits": hits}}), url

        f = _Fetcher()
        items = get_module("lou1").search("阿凡达", f, max_pages=1)
        titles = [i.title for i in items]
        self.assertEqual(len(f.urls), 3)                  # 全站 + 两个网盘版块
        self.assertIn("fid=13", f.urls[1])
        self.assertIn("fid=14", f.urls[2])
        self.assertEqual(len(titles), 4)
        self.assertTrue(all("夸克下载" in t for t in titles[:3]))  # 网盘置前
        self.assertIn("阿凡达.Avatar.2009.1080p.BluRay", titles)

    def test_pan_hit_not_duplicated(self):
        from src.site.modules import get_module

        pan = self._hits(2, 13, "[夸克下载][阿凡达][全2部]")
        normal = self._hits(1, 1, "阿凡达.Avatar.2009")

        class _Fetcher:
            def get(self, url, encoding=None, **kw):
                hits = [normal, pan] if "fid=13" in url else (
                    [] if "fid=14" in url else [normal, pan])
                return json.dumps({"ok": True, "data": {"hits": hits}}), url

        items = get_module("lou1").search("阿凡达", _Fetcher(), max_pages=1)
        urls = [i.detail_url for i in items]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len(items), 2)

    def test_board_failure_does_not_break_search(self):
        from src.site.modules import get_module

        normal = self._hits(1, 1, "阿凡达.Avatar.2009")

        class _Fetcher:
            def get(self, url, encoding=None, **kw):
                if "fid=13" in url:
                    raise RuntimeError("boom")
                return json.dumps({"ok": True,
                                   "data": {"hits": [normal]}}), url

        logs = []
        items = get_module("lou1").search("阿凡达", _Fetcher(), max_pages=1,
                                          log_cb=logs.append)
        self.assertEqual(len(items), 1)                   # 全站结果仍在
        self.assertTrue(any("网盘版块" in line for line in logs))


class TestFetcherPost(unittest.TestCase):
    """POST 表单必须自带 Content-Type，否则 PHP 不解析 $_POST。"""

    def test_dict_form_sets_content_type(self):
        captured = {}

        class _Resp:
            content = b"<html>ok</html>"
            url = "https://x.test/e/search/index.php"

            def raise_for_status(self):
                pass

        class _Sess:
            def post(self, url, data=None, timeout=None, headers=None):
                captured.update(url=url, data=data, headers=headers)
                return _Resp()

            def get(self, url, timeout=8):
                return _Resp()

        f = SiteFetcher()
        f.session = _Sess()
        html, _ = f.post("https://x.test/e/search/index.php",
                         data={"keyboard": "阿凡达"}, encoding="gb2312",
                         referer="https://x.test/")
        self.assertEqual(html, "<html>ok</html>")
        sent = captured["headers"] or {}
        self.assertEqual(sent.get("Content-Type"),
                         "application/x-www-form-urlencoded")
        self.assertEqual(sent.get("Referer"), "https://x.test/")
        # 表单体必须按站点编码（gb2312）而非 UTF-8
        self.assertIn("%B0%A2%B7%B2%B4%EF",
                      captured["data"].decode("ascii"))


class TestFetcherWarmup(unittest.TestCase):
    """会话预热：失败静默，成功即建立 cookie 会话。"""

    class _Sess:
        def __init__(self, ok=True):
            self.ok = ok
            self.seen = []

        def get(self, url, timeout=8):
            self.seen.append(url)
            if not self.ok:
                raise OSError("network down")
            return None

    def test_warmup_ok(self):
        f = SiteFetcher()
        s = self._Sess(True)
        f.session = s
        self.assertTrue(f.warmup("https://example.com/"))
        self.assertEqual(s.seen, ["https://example.com/"])

    def test_warmup_never_raises(self):
        f = SiteFetcher()
        f.session = self._Sess(False)
        self.assertFalse(f.warmup("https://example.com/"))
        self.assertFalse(f.warmup(""))          # 空 URL 直接返回 False


class _FakeSearchModule(SiteModule):
    """用于编排测试的假模块（POST 搜索 + 详情抓磁力）。"""

    def __init__(self):
        self.meta = ModuleMeta(module_id="dyg7", name="fake",
                               entry_mode="entries")

    supports_search = True

    def search_spec(self, keyword, page=1, base=""):
        return SearchSpec(url="https://x.example/e/search/index.php",
                          method="POST", data={"keyboard": keyword},
                          encoding="utf-8", referer="https://x.example/",
                          base="https://x.example/")

    def parse_search(self, text, base_url):
        return [ParseItem(title=f"条目{i}",
                          detail_url=f"{base_url}{i}.html")
                for i in (1, 2, 3)]

    def parse_detail(self, html, item):
        item.magnets = [MagnetLink(label="磁力", url="magnet:?xt=urn:btih:1",
                                   kind="magnet")]


class TestServiceSearchOptions(unittest.TestCase):
    """服务层：结果上限与自动抓详情。"""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db = Database(path=os.path.join(self._dir, "t.db"))
        register_module(_FakeSearchModule())

    def tearDown(self):
        reload_external_modules()

    def test_limit_truncates(self):
        svc = SiteParseService(self.db, _FakeFetcher({}))
        res = svc.search("阿凡达", sites=[3], limit=2)
        self.assertEqual(res["sites"][0]["total"], 2)

    def test_cache_reused_within_ttl(self):
        class _F(_FakeFetcher):
            calls = []

            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                _F.calls.append(url)
                return DYG7_HTML, url

        svc = SiteParseService(self.db, _F({}))
        a = svc.search("阿凡达", sites=[3], cache_ttl=120, min_interval=0)
        b = svc.search("阿凡达", sites=[3], cache_ttl=120, min_interval=0)
        self.assertEqual(len(_F.calls), 1)
        self.assertEqual(a["total"], b["total"])
        self.assertTrue(b.get("cached"))

    def test_cache_disabled_when_ttl_zero(self):
        class _F(_FakeFetcher):
            calls = []

            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                _F.calls.append(url)
                return DYG7_HTML, url

        svc = SiteParseService(self.db, _F({}))
        svc.search("阿凡达", sites=[3], cache_ttl=0)
        svc.search("阿凡达", sites=[3], cache_ttl=0)
        self.assertEqual(len(_F.calls), 2)

    def test_auto_detail_fetches_magnets(self):
        class _F(_FakeFetcher):
            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                return "<li class='p1 m1'><p class='name'>条目1</p></li>", url

        svc = SiteParseService(self.db, _F({}))
        res = svc.search("阿凡达", sites=[3], auto_detail=2)
        self.assertTrue(res["ok"])
        self.assertTrue(res["items"])
        self.assertTrue(res["items"][0].magnets)


class _DatedModule(SiteModule):
    """搜索结果带日期：验证自动解析按“时间倒序”抓最上面的条目。"""

    supports_search = True

    def __init__(self):
        self.meta = ModuleMeta(module_id="dyg7", name="fake",
                               entry_mode="entries")

    def search_spec(self, keyword, page=1, base=""):
        return SearchSpec(url="https://x.example/e/search/index.php",
                          method="POST", data={"keyboard": keyword},
                          base="https://x.example/")

    def parse_search(self, text, base_url):
        rows = (("老片", "2020-01-01"), ("新片", "2026-07-01"),
                ("中期", "2024-05-01"), ("[网盘电影]网盘片", "2026-06-01"))
        return [ParseItem(title=t, date=d,
                          detail_url="%s%d.html" % (base_url, i))
                for i, (t, d) in enumerate(rows)]

    def parse_detail(self, html, item):
        item.magnets = [MagnetLink(label="夸克",
                                   url="https://pan.quark.cn/s/x",
                                   kind="pan")]


class TestAutoDetailOrder(unittest.TestCase):
    """自动解析顺序必须与界面一致：日期倒序，先抓最上面的。"""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db = Database(path=os.path.join(self._dir, "t.db"))
        register_module(_DatedModule())

    def tearDown(self):
        reload_external_modules()

    def test_newest_items_parsed_first(self):
        class _F(_FakeFetcher):
            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                return "<html>detail</html>", url

        svc = SiteParseService(self.db, _F({}))
        res = svc.search("阿凡达", sites=[3], auto_detail=2,
                         min_interval=0)
        parsed = [it.title for it in res["items"] if it.magnets]
        self.assertEqual(set(parsed), {"新片", "[网盘电影]网盘片"})

    def test_pan_title_alone_does_not_jump_queue(self):
        """网盘标记不再插队：更旧的网盘帖不会被优先解析。"""
        class _F(_FakeFetcher):
            def post(self, url, data=None, timeout=18, encoding=None,
                     referer="", cache=False, headers=None):
                return "<html>detail</html>", url

        svc = SiteParseService(self.db, _F({}))
        res = svc.search("阿凡达", sites=[3], auto_detail=1,
                         min_interval=0)
        parsed = [it.title for it in res["items"] if it.magnets]
        self.assertEqual(parsed, ["新片"])


class TestResourceKey(unittest.TestCase):
    """跨站点资源指纹。"""

    def test_ignores_scheme_www_query_case(self):
        self.assertEqual(
            _resource_key("HTTPS://WWW.Example.com/a/1.html?x=1"),
            _resource_key("http://example.com/a/1.html"))

    def test_empty(self):
        self.assertEqual(_resource_key(""), "")


if __name__ == "__main__":
    unittest.main()
