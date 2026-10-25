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

    def test_token_auth_logic(self):
        from src.server.app import create_app, VerifyRequest, LoginRequest
        app = create_app()
        verify_route = [r for r in app.routes if getattr(r, "path", "") == "/api/auth/verify"][0]
        login_route = [r for r in app.routes if getattr(r, "path", "") == "/api/auth/login"][0]
        # 默认无密码状态
        res = verify_route.endpoint(VerifyRequest(token=""))
        self.assertTrue(res["ok"])
        self.assertFalse(res["token_required"])

        # 默认免密登录直接放行
        login_res = login_route.endpoint(LoginRequest(username="admin", password=""))
        self.assertTrue(login_res["ok"])

    def test_operation_logs_and_incremental(self):
        # 1. 测试记录并读取操作日志
        self.service.db.add_operation_log("download", "推送到下载器", "测试下载任务", "success")
        logs = self.service.db.list_operation_logs(limit=10)
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]["category"], "download")

        # 2. 测试增量信息初始状态
        incr = self.service.get_latest_incremental()
        self.assertIn("urls", incr)
        self.assertIn("run_time", incr)

    def test_send_download_with_subscription(self):
        # 验证带 sub_id 的下载请求不会因为缺少 record_subscription_push 抛出异常
        sub_id = self.service.add_subscription("测试剧集", "https://example.com/test")
        res = self.service.send_download(
            url="magnet:?xt=urn:btih:dummy&dn=TestEpisode.S01E01.1080p.mkv",
            sub_id=sub_id,
            ep_label="第01集",
            quality="1080P",
            title="测试剧集",
        )
        self.assertIn("ok", res)
        # 验证数据库中存在推送记录
        history = self.service.db.get_pushed_labels(sub_id)
        if res.get("ok"):
            self.assertIn("第01集", history)

        # 验证操作日志中包含详细下载名称（包含剧名或文件名）
        logs = self.service.db.list_operation_logs(category="download", limit=5)
        self.assertGreater(len(logs), 0)
        recent_log = logs[0]
        self.assertIn("测试剧集", recent_log["detail"])
        self.assertIn("TestEpisode.S01E01.1080p.mkv", recent_log["detail"])

    def test_format_download_name_rules(self):
        from src.linkparse import format_download_name
        # 规则 1：无文件名，使用解析出的影视名 + 分集标签 + 画质
        n1 = format_download_name("magnet:?xt=urn:btih:abc", title="凡人修仙传", ep_label="第120集", quality="1080P")
        self.assertEqual(n1, "《凡人修仙传》 第120集 [1080P]")

        # 规则 2：Magnet 自带 &dn= 文件名且与剧名不重复（由于已包含 E01，不重复追加 (第01集)）
        n2 = format_download_name(
            "magnet:?xt=urn:btih:abc&dn=Joy.of.Life.S02E01.1080p.mkv",
            title="庆余年 第二季",
            ep_label="第01集",
        )
        self.assertEqual(n2, "《庆余年 第二季》 Joy.of.Life.S02E01.1080p.mkv")

        # 规则 3：Magnet 自带 &dn= 且文件名内已有剧名与集数
        n3 = format_download_name(
            "magnet:?xt=urn:btih:abc&dn=%E7%99%BD%E5%A4%9C%E7%A0%B4%E6%99%93.EP01.1080p.mkv",
            title="白夜破晓",
            ep_label="第01集",
        )
        self.assertEqual(n3, "白夜破晓.EP01.1080p.mkv")

        # 规则 4：分集标签自身就是完整文件名
        n4 = format_download_name("magnet:?xt=urn:btih:abc", title="热辣滚烫", ep_label="HD1080P国语中字.mp4")
        self.assertEqual(n4, "《热辣滚烫》 HD1080P国语中字.mp4")


if __name__ == "__main__":
    unittest.main()

