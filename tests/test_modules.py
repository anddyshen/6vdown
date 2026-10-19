"""站点模块系统单测：注册表 / hao6v 模块行为一致 / 站点实例 CRUD / 旧库迁移。

覆盖第一阶段（模块化重构）：
- registry 能取到内置 hao6v 模块，未知 ID 返回 None；
- hao6v 模块的 parse_list / parse_detail 与原 HomeParser 行为一致；
- site_instances 默认站点自动创建、增删改启停；
- 旧版数据库（无 site_instances / site_key）打开后自动迁移且数据不丢。
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database  # noqa: E402
from src.models import ParseItem, SiteInstance, site_from_row  # noqa: E402
from src.site.modules import get_module, list_modules  # noqa: E402
from src.site.modules.hao6v import Hao6vModule  # noqa: E402
from src.site.parser import HomeParser, parse_detail_desc, parse_detail_magnets  # noqa: E402
from src.site.service import SiteParseService  # noqa: E402

SITE = "https://www.hao6v.cc/"

_PAD = "<!--" + ("v6 padding " * 400) + "-->"

HOME_HTML = """<html><body>""" + _PAD + """
<div class="col2"><div class="box">
<ul id="tab"><li class="curr" id="tab1_btn_0">最新电影</li></ul>
<ul class="lt" id="tab1_div_0"><li><span>[09-01]</span>
<a href="/dy/9001.html">2025剧情《寻她》4K.HD中字</a></li></ul>
<h3>★最新更新电视剧★</h3>
<ul id="tab2"><li class="curr" id="tab2_btn_0">最新电视剧更新</li>
<li id="tab2_btn_2" onmouseover="etabit(this)">美剧</li></ul>
<ul class="lt" id="tab2_div_0"><li><span>[09-02]</span><a href="/mj/36047.html">
<font color='#FF0000'>《足球教练》第四季05</font></a></li></ul>
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


class TestRegistry(unittest.TestCase):
    def test_get_builtin_hao6v(self):
        m = get_module("hao6v")
        self.assertIsNotNone(m)
        self.assertEqual(m.meta.module_id, "hao6v")
        self.assertEqual(m.meta.entry_mode, "mirror")

    def test_get_unknown_module(self):
        self.assertIsNone(get_module("no-such-module"))
        self.assertIsNone(get_module(""))

    def test_list_modules_contains_hao6v(self):
        ids = [meta.module_id for meta in list_modules()]
        self.assertIn("hao6v", ids)


class TestHao6vModule(unittest.TestCase):
    def setUp(self):
        self.mod = Hao6vModule()

    def test_parse_list_matches_homeparser(self):
        """模块产出必须与直接使用 HomeParser 完全一致（重构零行为变化）。"""
        via_module = self.mod.parse_list(HOME_HTML, SITE, include_unknown=True)
        via_parser = HomeParser(HOME_HTML, SITE).parse(include_unknown=True)
        self.assertEqual(
            [(i.title, i.date, i.block, i.detail_url, i.is_red)
             for i in via_module],
            [(i.title, i.date, i.block, i.detail_url, i.is_red)
             for i in via_parser],
        )
        self.assertEqual(len(via_module), 2)

    def test_parse_detail_matches_functions(self):
        item = ParseItem(title="足球教练")
        self.mod.parse_detail(DETAIL_HTML, item)
        self.assertEqual([m.url for m in item.magnets],
                         [m.url for m in parse_detail_magnets(DETAIL_HTML)])
        self.assertEqual(item.desc, parse_detail_desc(DETAIL_HTML))
        self.assertEqual(len(item.magnets), 2)


class TestSiteInstanceModel(unittest.TestCase):
    def test_entries_filters_empty(self):
        s = SiteInstance(entry_urls=["", "https://a.com/", None])
        self.assertEqual(s.entries(), ["https://a.com/"])

    def test_site_from_row(self):
        class _Row(dict):
            def __getitem__(self, k):
                return dict.__getitem__(self, k)

        row = _Row(id=3, module_id="dygang", name="电影港",
                   entry_urls='["https://www.dygang.tv/", ""]',
                   enabled=1, note="n", created_at=123)
        s = site_from_row(row)
        self.assertEqual(s.id, 3)
        self.assertEqual(s.module_id, "dygang")
        self.assertEqual(s.entries(), ["https://www.dygang.tv/"])


class TestSiteInstancesDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_site_auto_created(self):
        sid = self.db.ensure_default_site()
        sites = self.db.list_sites()
        self.assertIn(sid, [s.id for s in sites])
        default = self.db.get_site(sid)
        self.assertEqual(default.module_id, "hao6v")
        self.assertTrue(default.enabled)
        self.assertTrue(default.is_current, "默认站点应为当前解析站点")
        self.assertEqual(default.entries(), [])
        # 幂等：重复调用不产生重复行
        self.assertEqual(self.db.ensure_default_site(), sid)
        self.assertEqual(len([s for s in self.db.list_sites()
                              if s.module_id == "hao6v"]), 1)

    def test_upsert_enable_delete(self):
        sid = self.db.ensure_default_site()
        new_id = self.db.upsert_site(SiteInstance(
            module_id="hao6v", name="临时站",
            entry_urls=["https://a.example/", "https://b.example/"],
            note="测试"))
        self.assertNotEqual(new_id, sid)
        got = self.db.get_site(new_id)
        self.assertEqual(got.entries(),
                         ["https://a.example/", "https://b.example/"])
        self.db.set_site_enabled(new_id, False)
        enabled_ids = [s.id for s in self.db.list_sites(enabled_only=True)]
        self.assertIn(sid, enabled_ids)
        self.assertNotIn(new_id, enabled_ids)
        got.name = "改名"
        self.db.upsert_site(got)
        self.assertEqual(self.db.get_site(new_id).name, "改名")
        self.db.delete_site(new_id)
        self.assertIsNone(self.db.get_site(new_id))


class TestLegacyDbMigration(unittest.TestCase):
    """旧库（无 site_instances / 无 site_key）打开后必须平滑迁移。"""

    _OLD_SCHEMA = """
    CREATE TABLE download_hosts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT,
      address TEXT, port INTEGER, username TEXT, password TEXT,
      is_active INTEGER, created_at INTEGER);
    CREATE TABLE mirror_sites(
      id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE,
      enabled INTEGER, is_current INTEGER, status TEXT,
      checked_at INTEGER, created_at INTEGER, note TEXT);
    CREATE TABLE task_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER, title TEXT,
      link TEXT, source TEXT, host_name TEXT, host_type TEXT,
      status TEXT, message TEXT);
    CREATE TABLE parse_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT, site_url TEXT,
      detail_url TEXT UNIQUE, title TEXT, date TEXT, block TEXT,
      is_red INTEGER, is_classic INTEGER, detail_ok INTEGER, desc TEXT,
      magnets_json TEXT, first_seen INTEGER, last_seen INTEGER,
      prev_title TEXT);
    CREATE TABLE parse_runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, site_url TEXT,
      started_at INTEGER, finished_at INTEGER, total INTEGER,
      new_count INTEGER, status TEXT);
    CREATE TABLE subscriptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT,
      detail_url TEXT UNIQUE, status TEXT, last_ep TEXT,
      emby_series_id TEXT, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE subscription_history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, sub_id INTEGER,
      episode_label TEXT, magnet_url TEXT, quality TEXT, pushed_at INTEGER);
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
    """

    def test_migration_keeps_data(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = os.path.join(self.tmp.name, "legacy.db")
        conn = sqlite3.connect(path)
        conn.executescript(self._OLD_SCHEMA)
        conn.execute(
            "INSERT INTO parse_records(site_url,detail_url,title,date,block)"
            " VALUES('https://www.hao6v.cc/','/dy/1.html','旧数据','09-01','最新电影')")
        conn.commit()
        conn.close()

        db = Database(path)  # 打开即迁移
        try:
            sites = db.list_sites()
            self.assertGreaterEqual(len(sites), 1, "必须自动创建默认站点实例")
            self.assertIn("hao6v", {s.module_id for s in sites})
            self.assertTrue(any(s.is_current for s in sites))
            cols = {r["name"] for r in
                    db._conn().execute("PRAGMA table_info(parse_records)")}
            self.assertIn("site_key", cols)
            sub_cols = {r["name"] for r in
                        db._conn().execute("PRAGMA table_info(subscriptions)")}
            self.assertIn("site_key", sub_cols)
            items = db.list_parse_items("https://www.hao6v.cc/")
            self.assertEqual(len(items), 1, "旧解析记录不得丢失")
            self.assertEqual(items[0].title, "旧数据")
        finally:
            db._conn().close()
            self.tmp.cleanup()


class TestServiceUsesModule(unittest.TestCase):
    """服务层：默认站点走 hao6v 模块；入口型站点可被独立解析。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.fetcher = FakeFetcher()
        self.svc = SiteParseService(self.db, self.fetcher)  # type: ignore[arg-type]
        self.fetcher.pages = {
            SITE: HOME_HTML,
            SITE + "dy/9001.html": DETAIL_HTML,
            SITE + "mj/36047.html": DETAIL_HTML,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_with_default_site(self):
        s = self.svc.run(polite_delay=0)
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(s["sites"][0]["site"], SITE)
        self.assertEqual(s["new"], 2)
        self.assertEqual(len(self.svc.fetcher.calls) >= 1, True)
        self.assertIsNotNone(self.svc._instance)
        self.assertEqual(self.svc._instance.module_id, "hao6v")

    def test_run_with_entry_site_instance(self):
        """入口型站点实例：禁用默认站后，按 entry_urls 抓取并落库。"""
        sid = self.db.ensure_default_site()
        self.db.set_site_enabled(sid, False)
        entry = "https://entry.example/"
        self.db.upsert_site(SiteInstance(
            module_id="hao6v", name="入口站", entry_urls=[entry]))
        self.fetcher.pages = {
            entry: HOME_HTML,
            entry + "dy/9001.html": DETAIL_HTML,
            entry + "mj/36047.html": DETAIL_HTML,
        }
        s = self.svc.run(polite_delay=0)
        self.assertTrue(s["ok"], s.get("error"))
        rows = [r for r in s["sites"] if r["name"] == "入口站"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["site"], entry)
        self.assertEqual(s["new"], 2)
        self.assertEqual(self.svc._instance.name, "入口站")

    def test_missing_module_reports_error(self):
        sid = self.db.ensure_default_site()
        self.db.set_site_enabled(sid, False)
        self.db.upsert_site(SiteInstance(
            module_id="ghost-module", name="坏模块站",
            entry_urls=["https://x.example/"]))
        s = self.svc.run(polite_delay=0)
        self.assertFalse(s["ok"])
        self.assertIn("坏模块站", s["error"])


class TestCurrentSite(unittest.TestCase):
    """当前解析站点：is_current 切换 / 无当前时回落 / 内置站点种子。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_builtin_sites_seeded(self):
        sites = {s.module_id: s for s in self.db.list_sites()}
        self.assertIn("hao6v", sites)
        self.assertIn("dygang", sites, "dygang 内置站点必须自动补写")
        dyg = sites["dygang"]
        self.assertTrue(dyg.enabled)
        self.assertEqual(dyg.entries(), ["https://www.dygang.tv/"])
        self.assertFalse(dyg.is_current)
        self.assertTrue(sites["hao6v"].is_current, "默认站点应为当前")

    def test_current_site_switch(self):
        dyg = next(s for s in self.db.list_sites() if s.module_id == "dygang")
        self.db.set_current_site(dyg.id)
        cur = self.db.current_site()
        self.assertEqual(cur.module_id, "dygang")
        # 无 is_current 时回落第一个启用站点
        with self.db._lock, self.db._conn() as c:
            c.execute("UPDATE site_instances SET is_current=0")
        cur = self.db.current_site()
        self.assertTrue(cur.enabled)

    def test_delete_builtin_site_is_dismissed(self):
        dyg = next(s for s in self.db.list_sites() if s.module_id == "dygang")
        self.db.delete_site(dyg.id)
        self.assertIsNone(self.db.get_site(dyg.id))
        self.assertEqual(self.db.get_setting("site_dismissed:dygang"), "1")
        self.db.ensure_builtin_sites()
        self.assertIsNone(
            next((s for s in self.db.list_sites() if s.module_id == "dygang"), None),
            "用户删过的内置站点不得被重新补写")


class TestServiceCurrentSite(unittest.TestCase):
    """服务层：未勾选=全部启用站点；勾选后仅解析所选；失效站点降级不中断。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.fetcher = FakeFetcher()
        self.svc = SiteParseService(self.db, self.fetcher)  # type: ignore[arg-type]
        self.fetcher.pages = {
            SITE: HOME_HTML,
            SITE + "dy/9001.html": DETAIL_HTML,
            SITE + "mj/36047.html": DETAIL_HTML,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _dygang(self):
        return next(s for s in self.db.list_sites() if s.module_id == "dygang")

    def test_default_runs_all_enabled(self):
        """未勾选（enabled_sites 为空）= 全部启用站点，hao6v 优先。"""
        s = self.svc.run(polite_delay=0)
        self.assertTrue(s["ok"], s.get("error"))
        mods = [r["module"] for r in s["sites"]]
        self.assertIn("hao6v", mods)
        self.assertIn("dygang", mods)
        self.assertIn("dyg7", mods)
        self.assertEqual(mods[0], "hao6v", "当前站点（hao6v）应排最前")
        self.assertEqual(s["sites"][0]["site"], SITE)

    def test_selected_sites_only(self):
        """只勾选 dygang → 仅解析 dygang，不碰 hao6v 镜像池。"""
        dyg = self._dygang()
        entry = "https://www.dygang.tv/"
        self.fetcher.pages = {entry: HOME_HTML}
        s = self.svc.run(polite_delay=0, sites=[dyg.id])
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(len(s["sites"]), 1)
        self.assertEqual(s["sites"][0]["module"], "dygang")
        self.assertEqual(s["sites"][0]["site"], entry)
        self.assertNotIn(SITE, self.fetcher.calls, "不得抓取未勾选站点")

    def test_selection_order_and_invalid_ids(self):
        """勾选顺序决定解析顺序；无效 id 被忽略。"""
        dyg = self._dygang()
        hao = next(s for s in self.db.list_sites() if s.module_id == "hao6v")
        entry = "https://www.dygang.tv/"
        self.fetcher.pages = {entry: HOME_HTML, SITE: HOME_HTML}
        s = self.svc.run(polite_delay=0, sites=[dyg.id, 9999, hao.id],
                         fetch_detail=False)
        self.assertEqual([r["module"] for r in s["sites"]],
                         ["dygang", "hao6v"])

    def test_fallback_when_current_site_dead(self):
        dyg = self._dygang()
        self.db.set_current_site(dyg.id)
        # dygang 入口不在假抓取器里 → 全部失败 → 降级回 hao6v 镜像池
        s = self.svc.run(polite_delay=0)
        self.assertTrue(s["ok"], s.get("error"))
        hao = [r for r in s["sites"] if r["module"] == "hao6v"]
        self.assertEqual(len(hao), 1)
        self.assertEqual(hao[0]["site"], SITE)
        self.assertTrue(any(r.get("error") for r in s["sites"]),
                        "失效站点应记录错误但不应中断整体")

    def test_merged_items_dedup(self):
        """两个站点返回相同 detail_url 时合并列表只保留一条。"""
        dyg = self._dygang()
        entry = "https://www.dygang.tv/"
        self.fetcher.pages = {entry: HOME_HTML, SITE: HOME_HTML}
        s = self.svc.run(polite_delay=0, fetch_detail=False)
        urls = [it.detail_url for it in s["items"]]
        self.assertEqual(len(urls), len(set(urls)), "合并列表不得有重复详情页")


class TestParseRecordsUnique(unittest.TestCase):
    """parse_records 唯一约束：detail_url 全局唯一 → (site_url, detail_url) 联合唯一。

    多入口站点（电影港新版 8 个分类页）下同一详情页会归属不同入口，
    全局唯一会导致 INSERT 冲突。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def _constraint_compact(self, db=None):
        db = db or self.db
        row = db._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type=? AND name=?",
            ("table", "parse_records")).fetchone()
        return (row["sql"] or "").replace(" ", "").lower()

    def test_same_detail_url_different_sites(self):
        from src.models import ParseItem

        a = ParseItem(title="A", detail_url="https://x.example/1.html")
        b = ParseItem(title="B", detail_url="https://x.example/1.html")
        self.db.upsert_parse_records("https://a.example/", [a])
        self.db.upsert_parse_records("https://b.example/", [b])
        self.assertEqual(len(self.db.list_parse_items("https://a.example/")), 1)
        self.assertEqual(len(self.db.list_parse_items("https://b.example/")), 1)
        self.assertEqual(len(self.db.list_parse_items(
            ["https://a.example/", "https://b.example/"])), 2)

    def test_legacy_global_unique_is_migrated(self):
        path = os.path.join(self.tmp.name, "legacy.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE parse_records(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " site_url TEXT, detail_url TEXT UNIQUE, title TEXT, date TEXT,"
            " block TEXT, is_red INTEGER DEFAULT 0, is_classic INTEGER DEFAULT 0,"
            " detail_ok INTEGER DEFAULT 0, desc TEXT,"
            " magnets_json TEXT DEFAULT '[]', first_seen INTEGER,"
            " last_seen INTEGER DEFAULT 0, prev_title TEXT DEFAULT '');"
            "INSERT INTO parse_records(site_url,detail_url,title) "
            "VALUES('https://old.example/','/1.html','旧数据');")
        conn.commit()
        conn.close()

        db = Database(path)  # 打开即重建
        try:
            self.assertIn("unique(site_url,detail_url)",
                          self._constraint_compact(db))
            rows = db.list_parse_items("https://old.example/")
            self.assertEqual(len(rows), 1, "重建迁移不得丢数据")
            self.assertEqual(rows[0].title, "旧数据")
            # 同一 detail_url 在另一个站点下不再冲突
            from src.models import ParseItem

            db.upsert_parse_records("https://new.example/",
                                    [ParseItem(title="新", detail_url="/1.html")])
            self.assertEqual(len(db.list_parse_items("https://new.example/")), 1)
        finally:
            db._conn().close()


class TestDetailCacheAndConcurrency(unittest.TestCase):
    """详情抓取：跨入口相同 URL 只抓一次；并发参数可用。"""

    LOU_ROW = (
        '<li class="media thread tap hidden-sm" data-href="{tid}.htm">'
        '<div class="subject break-all">'
        '<a href="forum-1.htm" title="最新电影" class="text-secondary small">[最新电影]</a>'
        '<a href="{tid}.htm" class="text-title">[BT下载]测试电影[1080p]</a>'
        '<span class="date text-grey">2026-10-18</span>'
        '</div></li>'
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.fetcher = FakeFetcher()
        self.svc = SiteParseService(self.db, self.fetcher)  # type: ignore[arg-type]

    def tearDown(self):
        self.tmp.cleanup()

    def _pages(self):
        e1 = "https://www.1lou.me/forum-1.htm"
        e2 = "https://www.1lou.me/forum-3.htm"
        detail = "https://www.1lou.me/thread-100.htm"
        return e1, e2, detail

    def _prepare(self):
        e1, e2, detail = self._pages()
        row = self.LOU_ROW.format(tid="thread-100")
        pad = "<!--" + ("forum padding " * 300) + "-->"
        page = (f'<html><body>{pad}'
                f'<ul class="list-unstyled threadlist mb-0">{row}</ul></body></html>')
        self.fetcher.pages = {
            e1: page, e2: page,
            detail: '<html><body><div class="message break-all">'
                    '<p>◎片　　名　测试电影</p>'
                    '<a href="magnet:?xt=urn:btih:'
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">第01集</a>'
                    '</div></body></html>',
        }

    def test_same_detail_fetched_once_across_entries(self):
        e1, e2, detail = self._pages()
        self._prepare()
        lou = next(s for s in self.db.list_sites() if s.module_id == "lou1")
        s = self.svc.run(sites=[lou.id], concurrency=1)
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(self.fetcher.calls.count(detail), 1,
                         "同一详情页跨入口只应抓取一次")
        for entry in (e1, e2):
            rows = self.db.list_parse_items(entry)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0].magnets), 1, "复用条目也要带磁力")

    def test_concurrent_path_also_dedups(self):
        e1, e2, detail = self._pages()
        self._prepare()
        lou = next(s for s in self.db.list_sites() if s.module_id == "lou1")
        s = self.svc.run(sites=[lou.id], concurrency=4)
        self.assertTrue(s["ok"], s.get("error"))
        self.assertEqual(self.fetcher.calls.count(detail), 1)
        self.assertEqual(s["new"], 2, "两个入口各入库一条")

    def test_cache_cleared_between_runs(self):
        e1, e2, detail = self._pages()
        self._prepare()
        lou = next(s for s in self.db.list_sites() if s.module_id == "lou1")
        self.svc.run(sites=[lou.id], concurrency=2)
        calls_after_first = self.fetcher.calls.count(detail)
        # 第二次解析：无新增 → 不应再抓详情
        self.svc.run(sites=[lou.id], concurrency=2)
        self.assertEqual(self.fetcher.calls.count(detail), calls_after_first)


if __name__ == "__main__":
    unittest.main()
