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

    def test_host_lifecycle(self):
        # 1. 保存新主机
        host_id = self.service.save_host({
            "type": "qb",
            "name": "单元测试主机",
            "address": "127.0.0.1",
            "port": 8080,
            "username": "admin",
            "password": "secret_password",
            "is_active": False,
        })
        self.assertGreater(host_id, 0)

        # 2. 修改主机但不传密码，密码应被保留
        self.service.save_host({
            "id": host_id,
            "type": "qb",
            "name": "单元测试主机改名",
            "address": "127.0.0.1",
            "port": 8080,
            "username": "admin",
            "password": "",  # 留空
            "is_active": False,
        })
        hosts = [h for h in self.service.db.list_hosts() if h.id == host_id]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].password, "secret_password")
        self.assertEqual(hosts[0].name, "单元测试主机改名")

        # 3. 激活主机
        self.service.activate_host(host_id)
        cur_active = self.service.db.active_host()
        self.assertIsNotNone(cur_active)
        self.assertEqual(cur_active.id, host_id)

        # 4. 删除主机
        self.service.delete_host(host_id)
        hosts_after = [h for h in self.service.db.list_hosts() if h.id == host_id]
        self.assertEqual(len(hosts_after), 0)

    def test_reset_cache(self):
        ok = self.service.reset_cache()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

