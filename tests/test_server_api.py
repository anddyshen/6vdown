"""服务端业务与接口单元测试。"""
from __future__ import annotations

import unittest
from src.server.service import ServerService


class TestServerService(unittest.TestCase):
    def setUp(self):
        self.service = ServerService()

    def test_get_sites(self):
        sites = self.service.get_sites()
        self.assertIsInstance(sites, list)
        self.assertGreater(len(sites), 0)
        # 必须有一个默认站点
        has_current = any(s["is_current"] for s in sites)
        self.assertTrue(has_current)

    def test_get_workbench_items(self):
        items = self.service.get_workbench_items()
        self.assertIsInstance(items, list)

    def test_list_subscriptions(self):
        subs = self.service.list_subscriptions()
        self.assertIsInstance(subs, list)

    def test_config_operations(self):
        cfg = self.service.get_config()
        self.assertIn("quality_priority", cfg)
        # 测试更新配置
        updated = self.service.update_config({"test_docker_flag": True})
        self.assertTrue(updated.get("test_docker_flag"))

    def test_parse_status(self):
        status = self.service.get_parse_status()
        self.assertIn("is_parsing", status)
        self.assertIn("logs", status)


if __name__ == "__main__":
    unittest.main()

