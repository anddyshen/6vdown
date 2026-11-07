"""增量解析单测：同一详情页的“续集更新”必须被识别、抓取并写回。

回归用例：《足球教练》第四季05（09-02）→ 第四季06（09-10）时详情页 URL 不变，
旧逻辑只按 detail_url 判重，导致更新被漏掉。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database  # noqa: E402
from src.site.service import SiteParseService  # noqa: E402

SITE = "https://www.hao6v.cc/"
COACH_URL = "https://www.hao6v.cc/mj/36047.html"
MOVIE_URL = "https://www.hao6v.cc/dy/9001.html"

_PAD = "<!--" + ("v6 padding " * 400) + "-->"


def home_html(episode: int, date: str) -> str:
    """首页：一个不变的电影 + 一个集数会前进的美剧（同一详情页 URL）。"""
    return f"""<html><body>{_PAD}
<div class="col2"><div class="box">
<ul id="tab"><li class="curr" id="tab1_btn_0">最新电影</li></ul>
<ul class="lt" id="tab1_div_0"><li><span>[09-01]</span>
<a href="/dy/9001.html">2025剧情《寻她》4K.HD中字</a></li></ul>
<h3>★最新更新电视剧★</h3>
<ul id="tab2"><li class="curr" id="tab2_btn_0">最新电视剧更新</li>
<li id="tab2_btn_2" onmouseover="etabit(this)">美剧</li></ul>
<ul class="lt" id="tab2_div_0"><li><span>[{date}]</span><a href="/mj/36047.html">
<font color='#FF0000'>《足球教练》第四季{episode:02d}</font></a></li></ul>
<ul class="lt" id="tab2_div_2" style="display:none;"><li><span>[{date}]</span>
<a href="/mj/36047.html"><font color='#FF0000'>《足球教练》第四季{episode:02d}</font></a></li></ul>
</div></div></body></html>"""


DETAIL_HTML = """<html><head>
<meta name="description" content="◎片 名：足球教练 第四季  ◎年 代：2026">
</head><body>
<a href="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">第01集</a>
<a href="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">第02集</a>
</body></html>"""


class FakeFetcher:
    """假抓取器：按 URL 返回预置 HTML。"""

    def __init__(self):
        self.pages = {}
        self.calls = []

    def get(self, url, timeout=18, cache=False):
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError("not found: " + url)
        return self.pages[url], url


class TestIncrement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.fetcher = FakeFetcher()
        self.svc = SiteParseService(self.db, self.fetcher)  # type: ignore[arg-type]

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, episode: int, date: str) -> None:
        self.fetcher.pages = {
            SITE: home_html(episode, date),
            MOVIE_URL: DETAIL_HTML,
            COACH_URL: DETAIL_HTML,
        }

    def _run(self, **kw):
        return self.svc.run(polite_delay=0, **kw)

    def _by_url(self, site: str) -> dict:
        return {it.detail_url: it for it in self.db.list_parse_items(site)}

    def test_first_run_all_new(self):
        self._prepare(5, "09-02")
        s = self._run()
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(s["new"], 2)
        self.assertEqual(s["updated"], 0)
        rows = self._by_url(SITE)
        self.assertIn(COACH_URL, rows)
        self.assertEqual(rows[COACH_URL].title, "《足球教练》第四季05")
        self.assertEqual(len(rows[COACH_URL].magnets), 2)

    def test_same_url_episode_update_is_detected(self):
        self._prepare(5, "09-02")
        self._run()

        # 站点把《足球教练》更新到第四季06（详情页 URL 不变）
        self._prepare(6, "09-10")
        s = self._run()
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(s["new"], 0, "同一详情页不应被算作新增")
        self.assertEqual(s["updated"], 1, "集数前进必须被识别为更新")
        self.assertIn(COACH_URL, s["updated_urls"])

        rows = self._by_url(SITE)
        self.assertEqual(len(rows), 2, "更新不应产生重复记录")
        coach = rows[COACH_URL]
        self.assertEqual(coach.title, "《足球教练》第四季06")
        self.assertEqual(coach.date, "09-10")
        self.assertEqual(coach.prev_title, "《足球教练》第四季05")
        self.assertEqual(len(coach.magnets), 2, "更新后必须重新抓取磁力")
        self.assertTrue(coach.is_red, "红链标记应保留")
        self.assertGreater(coach.last_seen, 0)

    def test_second_run_without_changes_reports_nothing(self):
        self._prepare(5, "09-02")
        self._run()
        s = self._run()
        self.assertEqual(s["new"], 0)
        self.assertEqual(s["updated"], 0)
        self.assertEqual(len(self._by_url(SITE)), 2)

    def test_pan_only_item_retried_for_magnets(self):
        """测试：初始只有网盘链接的条目，后续解析会自动重试补抓新增的磁力。"""
        pan_only_detail = """<html><body>
        <a href="https://pan.quark.cn/s/123456">夸克网盘</a>
        </body></html>"""
        self.fetcher.pages = {
            SITE: home_html(5, "09-02"),
            MOVIE_URL: DETAIL_HTML,
            COACH_URL: pan_only_detail,
        }
        s1 = self._run()
        self.assertEqual(s1["new"], 2)
        rows1 = self._by_url(SITE)
        coach1 = rows1[COACH_URL]
        self.assertEqual(len(coach1.magnets), 1)
        self.assertEqual(coach1.magnets[0].kind, "pan")

        # 站点在详情页中追加了磁力链接（首页标题和日期均未变）
        with_magnet_detail = """<html><body>
        <a href="https://pan.quark.cn/s/123456">夸克网盘</a>
        <a href="magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc">第01集</a>
        </body></html>"""
        self.fetcher.pages[COACH_URL] = with_magnet_detail
        s2 = self._run()
        # 应该被判定为更新补抓，并包含在 updated_urls 中
        self.assertIn(COACH_URL, s2["updated_urls"])
        rows2 = self._by_url(SITE)
        coach2 = rows2[COACH_URL]
        self.assertEqual(len(coach2.magnets), 2)
        kinds = [m.kind for m in coach2.magnets]
        self.assertIn("magnet", kinds)
        self.assertIn("pan", kinds)

    def test_update_parse_item_by_detail_url(self):
        """测试根据 detail_url 精准更新磁力与详情信息。"""
        from src.models import MagnetLink, ParseItem

        self._prepare(5, "09-02")
        self._run()
        it = ParseItem(
            detail_url=COACH_URL,
            desc="新描述",
            magnets=[MagnetLink(label="更新集", url="magnet:?xt=urn:btih:dddddddddddddddddddddddddddddddddddddddd", kind="magnet")]
        )
        ok = self.db.update_parse_item_by_detail_url(it)
        self.assertTrue(ok)
        rows = self._by_url(SITE)
        updated = rows[COACH_URL]
        self.assertEqual(updated.desc, "新描述")
        self.assertEqual(len(updated.magnets), 1)
        self.assertEqual(updated.magnets[0].label, "更新集")


if __name__ == "__main__":
    unittest.main()
