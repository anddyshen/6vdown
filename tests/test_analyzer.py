"""AutoProfile 本地规则推导测试：用四个真实站点的样本验证探测质量。

判据不是“与人写规则逐字相同”，而是：
  ① 推导出的规则能通过 generic 引擎校验；
  ② 试解析出的条目数/标题/详情 URL 与内置模块一致；
  ③ 模式选择正确（rows / date_anchor）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from src.site.modules.analyzer import (  # noqa: E402
    analyze, build_rule, detect_block_source, detect_date,
    detect_link_pattern, detect_row_candidates, detect_title_source,
    rule_to_module, sample_rows,
)
from src.site.modules.generic import GenericModule, clean_date_text  # noqa: E402
from src.site.modules.hao6v import Hao6vModule  # noqa: E402
from src.site.modules.dygang import DygangModule  # noqa: E402
from src.site.modules.dyg7 import Dyg7Module  # noqa: E402
from src.site.modules.lou1 import Lou1Module  # noqa: E402

from test_dygang import HOME_HTML as DYGANG_HTML, SITE as DYGANG_SITE  # noqa: E402
from test_dyg7 import PAGE_MOVIE, SITE as DYG7_SITE  # noqa: E402
from test_lou1 import LIST_HTML as LOU_LIST, SITE as LOU_SITE  # noqa: E402
from test_increment import SITE as HAO6V_SITE, home_html as hao6v_home  # noqa: E402

HAO6V_HTML = hao6v_home(5, "09-02")


def _snap(items, with_block: bool = True) -> set:
    """解析结果快照。区块归属是启发式的（向导里由用户确认），
    因此默认只比对 标题/日期/详情 URL。"""
    if with_block:
        return {(it.title, it.date, it.block, it.detail_url) for it in items}
    return {(it.title, it.date, it.detail_url) for it in items}


class TestProbes(unittest.TestCase):
    def test_link_pattern_dyg7(self):
        pat = detect_link_pattern(PAGE_MOVIE)
        self.assertIn(".html", pat)

    def test_link_pattern_dygang(self):
        pat = detect_link_pattern(DYGANG_HTML)
        self.assertIn(".htm", pat)

    def test_link_pattern_lou1(self):
        pat = detect_link_pattern(LOU_LIST)
        self.assertIn("thread-", pat)

    def test_row_candidates_dyg7(self):
        pat = detect_link_pattern(PAGE_MOVIE)
        cands = detect_row_candidates(PAGE_MOVIE, pat)
        self.assertTrue(cands)
        row_re = cands[0][0]
        rows = sample_rows(PAGE_MOVIE, row_re)
        self.assertGreaterEqual(len(rows), 3)
        self.assertIn("p1 m1", row_re.replace("\\", ""))

    def test_row_candidates_lou1(self):
        pat = detect_link_pattern(LOU_LIST)
        cands = detect_row_candidates(LOU_LIST, pat)
        self.assertTrue(cands)
        self.assertIn("media thread", cands[0][0].replace("\\", ""))

    def test_row_candidates_dygang_is_table_layout(self):
        """dygang 是 table 行布局（无带 class 的行容器）→ 不应产出 rows 候选。"""
        pat = detect_link_pattern(DYGANG_HTML)
        cands = detect_row_candidates(DYGANG_HTML, pat)
        self.assertEqual(cands, [],
                         "table 行布局没有 tag+class 行容器，应走日期锚点模式")

    def test_date_scope(self):
        mode, _re = detect_date(PAGE_MOVIE, "")
        self.assertEqual(mode, "rows")     # 无日期 → rows 且 date_re 空
        mode2, _re2 = detect_date(DYGANG_HTML, "")
        self.assertEqual(mode2, "date_anchor")

    def test_title_source_prefers_attr(self):
        pat = detect_link_pattern(PAGE_MOVIE)
        cands = detect_row_candidates(PAGE_MOVIE, pat)
        rows = sample_rows(PAGE_MOVIE, cands[0][0])
        title_re = detect_title_source(rows)
        self.assertIn("title", title_re)

    def test_block_source_heading(self):
        kind, regex, _m = detect_block_source(DYGANG_HTML)
        self.assertEqual(kind, "heading")
        self.assertIn("h(", regex.replace("\\", ""))

    def test_block_source_row_forum(self):
        kind, regex, name_map = detect_block_source(LOU_LIST)
        self.assertEqual(kind, "row")
        self.assertIn("forum", regex)
        self.assertEqual(name_map.get("最新电影"), "最新电影")

    def test_block_source_map_from_nav(self):
        """分类导航 <a href="/dy/">电影</a> → 路径→区块映射（含别名）。"""
        nav = ('<html><body><ul class="nav">'
               '<li><a href="/dy/">电影</a></li>'
               '<li><a href="/dsj/">电视剧</a></li>'
               '<li><a href="/dongman/">动漫</a></li>'
               '</ul></body></html>')
        kind, _regex, mapping = detect_block_source(nav)
        self.assertEqual(kind, "map")
        self.assertEqual(mapping.get("/dy/"), "最新电影")
        self.assertEqual(mapping.get("/dsj/"), "更新电视剧")
        self.assertEqual(mapping.get("/dongman/"), "动画")

    def test_block_source_nav_only_when_label_known(self):
        kind, _regex, mapping = detect_block_source(PAGE_MOVIE)
        self.assertEqual(kind, "none", "该样本无可识别的导航文字 → 不臆造区块")

    def test_clean_date_text_forms(self):
        self.assertEqual(clean_date_text("2026-10-07"), "2026-10-07")
        self.assertEqual(clean_date_text("[09-02]"), "09-02")
        self.assertEqual(clean_date_text("2026年10月7日"), "2026-10-07")
        self.assertEqual(clean_date_text("09/02"), "09-02")


class TestBuildRuleParity(unittest.TestCase):
    """推导规则经 generic 引擎解析，结果与内置模块一致。

    比对 标题/日期/详情 URL；区块归属属于启发式结果（向导里人工确认），
    仅在信号可靠时（论坛行级版块名）单独断言。
    """

    def _parse_with(self, rule: dict, html: str, base: str, entry: str = ""):
        module = rule_to_module(rule)
        self.assertIsNotNone(module, "推导规则必须通过校验")
        return module.parse_list(html, base, entry_url=entry or base)

    def test_dyg7(self):
        entry = DYG7_SITE + "/dy/"
        rule = build_rule(entry, PAGE_MOVIE)
        self.assertEqual(rule["extract"]["mode"], "rows")
        self.assertIn("title", rule["extract"]["title_re"],
                      "完整片名来自 title 属性（链接文字还带状态）")
        got = self._parse_with(rule, PAGE_MOVIE, DYG7_SITE, entry)
        want = Dyg7Module().parse_list(PAGE_MOVIE, DYG7_SITE, entry)
        self.assertEqual(_snap(got, False), _snap(want, False))
        self.assertGreaterEqual(len(got), 3)

    def test_dygang_date_anchor(self):
        rule = build_rule(DYGANG_SITE, DYGANG_HTML)
        self.assertEqual(rule["extract"]["mode"], "date_anchor")
        self.assertEqual(rule["extract"]["row_re"], "")
        got = self._parse_with(rule, DYGANG_HTML, DYGANG_SITE)
        want = DygangModule().parse_list(DYGANG_HTML, DYGANG_SITE)
        self.assertEqual(_snap(got, False), _snap(want, False))
        self.assertGreaterEqual(len(got), 3)

    def test_lou1(self):
        rule = build_rule(LOU_SITE + "forum-1.htm", LOU_LIST)
        self.assertEqual(rule["extract"]["mode"], "rows")
        self.assertIn("thread-", rule["extract"]["link_re"])
        got = self._parse_with(rule, LOU_LIST, LOU_SITE,
                               LOU_SITE + "forum-1.htm")
        want = Lou1Module().parse_list(LOU_LIST, LOU_SITE)
        self.assertEqual(_snap(got), _snap(want))
        self.assertEqual(len(got), 3, "置顶/站务公告必须被自然跳过")
        self.assertEqual({it.block for it in got}, {"最新电影"},
                         "行级版块名 → 区块映射（含 高清/网盘 别名）")

    def test_hao6v(self):
        rule = build_rule(HAO6V_SITE, HAO6V_HTML)
        self.assertEqual(rule["extract"]["mode"], "rows")
        got = self._parse_with(rule, HAO6V_HTML, HAO6V_SITE)
        want = Hao6vModule().parse_list(HAO6V_HTML, HAO6V_SITE)
        self.assertEqual(_snap(got, False), _snap(want, False))
        self.assertGreaterEqual(len(got), 2)


class _FakeFetcher:
    """假抓取器：命中预置页返回，否则返回 default（无 default 则报错）。"""

    def __init__(self, pages, default=""):
        self.pages = dict(pages)
        self.default = default
        self.calls = []

    def get(self, url, timeout=18, cache=False):
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url], url
        if self.default:
            return self.default, url
        raise RuntimeError("404 " + url)


class TestAnalyzePipeline(unittest.TestCase):
    """完整 analyze() 流程（假抓取器，无网络）。"""

    DETAIL_OK = ("<html><head><meta name=\"description\" "
                 "content=\"◎片 名：测试\"></head><body>"
                 "<a href=\"magnet:?xt=urn:btih:"
                 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\">磁力</a>"
                 "</body></html>")

    def _genuine_page(self):
        """真实站点页面都在数千字符以上；样本太短需补足。"""
        return PAGE_MOVIE + "<!--" + ("padding " * 600) + "-->"

    def test_pipeline_ok(self):
        entry = DYG7_SITE + "/dy/"
        detail = DYG7_SITE + "/dy/jqp/25355.html"
        res = analyze(entry, fetcher=_FakeFetcher({entry: self._genuine_page()},
                                                  default=self.DETAIL_OK),
                      max_details=2, polite_delay=0)
        self.assertTrue(res["ok"], res.get("warnings"))
        self.assertEqual(res["confidence"]["mode"], "rows")
        self.assertGreaterEqual(res["confidence"]["items"], 3)
        self.assertEqual(res["confidence"]["magnet_ratio"], 1.0)
        self.assertIn(detail, res["samples"]["detail_urls"])
        self.assertEqual(res["warnings"], [])

    def test_pipeline_no_detail_resources_warns(self):
        entry = DYG7_SITE + "/dy/"
        res = analyze(entry,
                      fetcher=_FakeFetcher({entry: self._genuine_page()},
                                           default="<html><body>无资源</body></html>"),
                      max_details=2, polite_delay=0)
        self.assertTrue(res["ok"], res.get("warnings"))
        self.assertEqual(res["confidence"]["magnet_ratio"], 0.0)
        self.assertTrue(any("详情页未解析到" in w for w in res["warnings"]))

    def test_pipeline_fetch_failure(self):
        res = analyze("https://bad.invalid/", fetcher=_FakeFetcher({}),
                      polite_delay=0)
        self.assertFalse(res["ok"])
        self.assertTrue(any("入口抓取失败" in w for w in res["warnings"]))

    def test_pipeline_no_links(self):
        res = analyze("https://x.example/", fetcher=_FakeFetcher(
            {"https://x.example/": "<html><body>" + ("x" * 4000)
             + "</body></html>"}), polite_delay=0)
        self.assertFalse(res["ok"])
        self.assertTrue(any("详情链接模式" in w for w in res["warnings"]))


if __name__ == "__main__":
    unittest.main()
