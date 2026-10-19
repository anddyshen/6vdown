"""模块健康度自检测试：连续异常告警、恢复清零、服务层自动记录。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from src.database import Database  # noqa: E402
from src.site.modules import health  # noqa: E402
from src.site.service import SiteParseService  # noqa: E402

from test_modules import FakeFetcher, HOME_HTML, SITE  # noqa: E402


class TestHealthRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_record_ok(self):
        info = health.mark(self.db, "hao6v", 30, 0.9)
        self.assertEqual(info["runs"], 1)
        self.assertEqual(info["fails"], 0)
        self.assertFalse(info["warn"])
        self.assertEqual(health.load(self.db, "hao6v")["last_items"], 30)

    def test_consecutive_zero_warns(self):
        health.mark(self.db, "dyg7", 0, None)      # 1 次不算（阈值 2）
        self.assertFalse(health.load(self.db, "dyg7")["warn"])
        health.mark(self.db, "dyg7", 0, None)      # 2 次 → 告警
        info = health.load(self.db, "dyg7")
        self.assertTrue(info["warn"])
        self.assertEqual(info["fails"], 2)
        self.assertIn("改版", health.describe(info))

    def test_success_resets_streak(self):
        health.mark(self.db, "dyg7", 0, None)
        health.mark(self.db, "dyg7", 0, None)
        self.assertTrue(health.load(self.db, "dyg7")["warn"])
        health.mark(self.db, "dyg7", 25, 1.0)
        info = health.load(self.db, "dyg7")
        self.assertEqual(info["fails"], 0)
        self.assertFalse(info["warn"])
        self.assertIn("正常", health.describe(info))

    def test_low_magnet_ratio_warns(self):
        info = health.mark(self.db, "lou1", 40, 0.05)
        self.assertTrue(info["warn"])
        self.assertIn("命中率", health.describe(info))

    def test_unhealthy_list_and_reset(self):
        health.mark(self.db, "a", 0, None)
        health.mark(self.db, "a", 0, None)
        health.mark(self.db, "b", 10, 1.0)
        bad = dict(health.unhealthy(self.db, ["a", "b"]))
        self.assertEqual(list(bad), ["a"])
        health.reset(self.db, "a")
        self.assertFalse(health.load(self.db, "a")["warn"])

    def test_describe_unknown(self):
        self.assertEqual(health.describe(health.load(self.db, "nope")),
                         "尚未解析")

    def test_corrupt_payload_safe(self):
        self.db.set_setting(health.KEY_PREFIX + "x", "{not json")
        self.assertEqual(health.load(self.db, "x")["runs"], 0)


class TestServiceRecordsHealth(unittest.TestCase):
    """解析一次后，服务层应自动写入该站点模块的健康度。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.fetcher = FakeFetcher()
        self.fetcher.pages = {SITE: HOME_HTML}
        self.svc = SiteParseService(self.db, self.fetcher)

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_written_after_run(self):
        hao = next(s for s in self.db.list_sites() if s.module_id == "hao6v")
        self.svc.run(sites=[hao.id], fetch_detail=False, polite_delay=0)
        info = health.load(self.db, "hao6v")
        self.assertEqual(info["runs"], 1)
        self.assertGreater(info["last_items"], 0)
        self.assertFalse(info["warn"])

    def test_zero_result_recorded(self):
        hao = next(s for s in self.db.list_sites() if s.module_id == "hao6v")
        self.fetcher.pages = {SITE: "<html><body>" + ("x" * 5000) + "</body></html>"}
        self.svc.run(sites=[hao.id], fetch_detail=False, polite_delay=0)
        self.assertEqual(health.load(self.db, "hao6v")["fails"], 1)


if __name__ == "__main__":
    unittest.main()
