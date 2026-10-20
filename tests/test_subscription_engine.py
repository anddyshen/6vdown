"""订阅决策引擎与 Emby 差量比对测试。"""
from __future__ import annotations

import unittest

from src.models import MagnetLink, ParseItem, Subscription
from src.subscription_engine import (
    analyze_subscription_updates,
    detect_quality,
    filter_subscription_updates,
    pick_best_magnet,
)


class TestSubscriptionEngine(unittest.TestCase):
    def setUp(self):
        self.sub = Subscription(id=1, title="繁花", detail_url="https://test/fan_hua.html")

    def test_detect_quality(self):
        self.assertEqual(detect_quality("繁花.第01集.4K.2160p.mkv"), "4K")
        self.assertEqual(detect_quality("繁花.第01集.1080p.HD.mp4"), "1080P")
        self.assertEqual(detect_quality("繁花.第01集.720p.HD.mp4"), "720P")
        self.assertEqual(detect_quality("繁花.第01集.mp4"), "OTHER")

    def test_pick_best_magnet_priority(self):
        m_4k = MagnetLink(label="繁花.第01集.4K.mkv", url="magnet:?xt=urn:btih:4k")
        m_1080 = MagnetLink(label="繁花.第01集.1080P.mkv", url="magnet:?xt=urn:btih:1080p")
        m_720 = MagnetLink(label="繁花.第01集.720P.mkv", url="magnet:?xt=urn:btih:720p")

        # 默认 1080P 优先
        best, q = pick_best_magnet([m_4k, m_1080, m_720], ["1080P", "4K", "720P", "OTHER"])
        self.assertEqual(best.url, m_1080.url)
        self.assertEqual(q, "1080P")

        # 调整为 4K 优先
        best4k, q4k = pick_best_magnet([m_4k, m_1080, m_720], ["4K", "1080P", "720P", "OTHER"])
        self.assertEqual(best4k.url, m_4k.url)
        self.assertEqual(q4k, "4K")

    def test_scenario_1_no_emby_focuses_latest_episode(self):
        """场景 1：无 Emby 模式下，仅推送未下载过的最新一集，不倾倒全页面历史。"""
        # 页面包含第1集到第12集
        magnets = [
            MagnetLink(label="繁花.第12集.1080P.mkv", url="magnet:?xt=urn:btih:ep12_1080"),
            MagnetLink(label="繁花.第12集.4K.mkv", url="magnet:?xt=urn:btih:ep12_4k"),
            MagnetLink(label="繁花.第11集.1080P.mkv", url="magnet:?xt=urn:btih:ep11_1080"),
            MagnetLink(label="繁花.第10集.1080P.mkv", url="magnet:?xt=urn:btih:ep10_1080"),
        ]
        item = ParseItem(title="繁花 更新至第12集", detail_url=self.sub.detail_url, magnets=magnets)

        # 假设本地已经推送过第10集和第11集
        pushed_urls = {"magnet:?xt=urn:btih:ep10_1080", "magnet:?xt=urn:btih:ep11_1080"}
        pushed_eps = {"第10集", "第11集"}

        up = analyze_subscription_updates(
            sub=self.sub,
            item=item,
            is_magnet_pushed_fn=lambda sid, u: u in pushed_urls,
            is_ep_pushed_fn=lambda sid, lbl: lbl in pushed_eps,
            priority_order=["1080P", "4K", "720P", "OTHER"],
            emby_existing=None,
        )

        self.assertIsNotNone(up)
        # 聚焦最新一集
        self.assertIsNotNone(up.latest_candidate)
        self.assertEqual(up.latest_candidate["ep_label"], "第12集")
        self.assertEqual(up.latest_candidate["quality"], "1080P")
        self.assertEqual(up.latest_candidate["magnet_url"], "magnet:?xt=urn:btih:ep12_1080")
        # 历史已推送过的集数不作为漏集
        self.assertEqual(len(up.missing_history), 0)

    def test_scenario_2_emby_linked_with_missing_history(self):
        """场景 2：连接 Emby 库，Emby 库仅存至第 10 集，网站出到了第 12 集。"""
        magnets = [
            MagnetLink(label="繁花.第12集.1080P.mkv", url="magnet:?xt=urn:btih:ep12_1080"),
            MagnetLink(label="繁花.第11集.1080P.mkv", url="magnet:?xt=urn:btih:ep11_1080"),
            MagnetLink(label="繁花.第10集.1080P.mkv", url="magnet:?xt=urn:btih:ep10_1080"),
            MagnetLink(label="繁花.第09集.1080P.mkv", url="magnet:?xt=urn:btih:ep09_1080"),
        ]
        item = ParseItem(title="繁花 更新至第12集", detail_url=self.sub.detail_url, magnets=magnets)

        # Emby 库内已有第 1 到 10 集 (Season 1)
        emby_inventory = {(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8), (1, 9), (1, 10)}

        up = analyze_subscription_updates(
            sub=self.sub,
            item=item,
            is_magnet_pushed_fn=lambda sid, u: False,
            is_ep_pushed_fn=lambda sid, lbl: False,
            priority_order=["1080P", "4K", "720P", "OTHER"],
            emby_existing=emby_inventory,
        )

        self.assertIsNotNone(up)
        self.assertTrue(up.has_emby)
        # 1. 主行动点：最新一集（第 12 集）
        self.assertIsNotNone(up.latest_candidate)
        self.assertEqual(up.latest_candidate["ep_label"], "第12集")

        # 2. 回溯提示：检测到 Emby 缺了第 11 集
        self.assertEqual(len(up.missing_history), 1)
        self.assertEqual(up.missing_history[0]["ep_label"], "第11集")

    def test_scenario_2_emby_all_caught_up(self):
        """场景 2：Emby 库内已经拥有网站的所有剧集，静默跳过无弹窗。"""
        magnets = [
            MagnetLink(label="繁花.第12集.1080P.mkv", url="magnet:?xt=urn:btih:ep12_1080"),
            MagnetLink(label="繁花.第11集.1080P.mkv", url="magnet:?xt=urn:btih:ep11_1080"),
        ]
        item = ParseItem(title="繁花 更新至第12集", detail_url=self.sub.detail_url, magnets=magnets)

        emby_inventory = {(1, 11), (1, 12)}

        up = analyze_subscription_updates(
            sub=self.sub,
            item=item,
            is_magnet_pushed_fn=lambda sid, u: False,
            is_ep_pushed_fn=lambda sid, lbl: False,
            priority_order=["1080P", "4K", "720P", "OTHER"],
            emby_existing=emby_inventory,
        )

        self.assertIsNone(up)


if __name__ == "__main__":
    unittest.main()

