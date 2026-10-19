"""网盘识别公共模块单测（src/site/netdisk.py）。

覆盖：
- 域名清单/URL 判定（含子域、大小写、非网盘地址）；
- 网盘名推断（用于 label）；
- 正文提取：纯文本与 <a> 链接、?pwd= 与“提取码：xxxx”补全、去重。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.site.modules.base import trim_search_items  # noqa: E402
from src.site.netdisk import (  # noqa: E402
    PAN_HOSTS, PAN_URL_RE, extract_pan_links, is_netdisk_url, looks_pan_title,
    netdisk_name,
)


class TestNetdiskDetect(unittest.TestCase):
    def test_hosts_are_lowercase_and_unique(self):
        self.assertEqual(len(PAN_HOSTS), len(set(PAN_HOSTS)))
        for host in PAN_HOSTS:
            self.assertEqual(host, host.lower())

    def test_is_netdisk_url(self):
        yes = [
            "https://pan.quark.cn/s/abc123",
            "http://pan.baidu.com/s/1xyz?pwd=1234",
            "https://www.aliyundrive.com/s/xyz",
            "https://www.alipan.com/s/xyz",
            "https://drive.uc.cn/s/xyz",
            "https://cloud.189.cn/t/xyz",
            "https://pan.xunlei.com/s/xyz",
            "https://115.com/s/xyz",
            "https://share.weiyun.com/xyz",
            "https://PAN.Quark.CN/s/upper",
        ]
        for url in yes:
            with self.subTest(url=url):
                self.assertTrue(is_netdisk_url(url))
        no = [
            "", None, "magnet:?xt=urn:btih:abc",
            "https://www.1lou.me/thread-1.htm",
            "https://pan.quark.cn.evil.com/s/abc",
            "ftp://pan.quark.cn/s/abc",
        ]
        for url in no:
            with self.subTest(url=url):
                self.assertFalse(is_netdisk_url(url))

    def test_netdisk_name(self):
        cases = {
            "https://pan.quark.cn/s/a": "夸克网盘",
            "https://pan.baidu.com/s/a": "百度网盘",
            "https://www.alipan.com/s/a": "阿里云盘",
            "https://drive.uc.cn/s/a": "UC网盘",
            "https://cloud.189.cn/t/a": "天翼云盘",
            "https://115.com/s/a": "115网盘",
            "https://share.weiyun.com/a": "腾讯微云",
            "https://example.com/a": "网盘链接",
        }
        for url, name in cases.items():
            with self.subTest(url=url):
                self.assertEqual(netdisk_name(url), name)


class TestNetdiskExtract(unittest.TestCase):
    def test_url_re_matches_both_forms(self):
        html = ('<a href="https://pan.quark.cn/s/aaa">夸克</a>'
                ' 备用 https://pan.baidu.com/s/bbb 结束')
        urls = [m.group(0) for m in PAN_URL_RE.finditer(html)]
        self.assertEqual(len(urls), 2)
        self.assertIn("pan.quark.cn/s/aaa", urls[0])
        self.assertIn("pan.baidu.com/s/bbb", urls[1])

    def test_extract_from_text_appends_pwd(self):
        html = "资源：https://pan.quark.cn/s/abc123\n提取码：x7k9"
        links = extract_pan_links(html)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://pan.quark.cn/s/abc123?pwd=x7k9")
        self.assertEqual(links[0].kind, "pan")
        self.assertEqual(links[0].label, "夸克网盘")

    def test_existing_pwd_not_duplicated(self):
        html = "https://pan.baidu.com/s/1abc?pwd=8888"
        links = extract_pan_links(html)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://pan.baidu.com/s/1abc?pwd=8888")

    def test_duplicate_urls_collapsed(self):
        html = ('https://pan.quark.cn/s/dup 和 '
                'https://pan.quark.cn/s/dup 是同一个')
        self.assertEqual(len(extract_pan_links(html)), 1)

    def test_no_pan_returns_empty(self):
        self.assertEqual(extract_pan_links("<p>无资源</p>"), [])

    def test_all_supported_hosts(self):
        """常见网盘（含 1LOU 实际写法）逐行给出时都要识别。"""
        urls = [
            "https://pan.quark.cn/s/217fc8fd1ded?pwd=4wLk",
            "https://pan.baidu.com/s/1bi9UnCcRO2FA7Akm8SNzpA?pwd=1111",
            "https://www.aliyundrive.com/s/a6EGG8d8sF1",
            "https://www.alipan.com/s/new001",
            "https://drive.uc.cn/s/abc123",
            "https://cloud.189.cn/t/xyz789",
            "https://pan.xunlei.com/s/xl000",
            "https://115.com/s/abc#code",
            "https://share.weiyun.com/wy000",
            "https://caiyun.139.com/m/i?1A2B3C",
            "https://www.123pan.com/s/123abc",
        ]
        html = "<br>".join("下载 %s" % u for u in urls)
        got = [ln.url for ln in extract_pan_links(html)]
        for u in urls:
            with self.subTest(url=u):
                self.assertIn(u, got)

    def test_pwd_not_misattributed_to_previous_url(self):
        """提取码只补给紧邻的那条链接，前面链接不能误配。"""
        html = ("https://www.123pan.com/s/aaa\n"
                "https://wwi.lanzou.com/ibbb\n提取码：k9m2")
        links = extract_pan_links(html)
        self.assertEqual(links[0].url, "https://www.123pan.com/s/aaa")
        self.assertEqual(links[1].url,
                         "https://wwi.lanzou.com/ibbb?pwd=k9m2")


class TestPanTitle(unittest.TestCase):
    def test_prefix_marker(self):
        yes = [
            "[夸克下载][阿凡达][全2部]",
            "[网盘电影]阿凡达",
            "【百度网盘】某剧",
            "[阿里云盘][某片]",
            "[UC网盘]某片",
            "[天翼云盘]某片",
            "[迅雷云盘]某片",
            "[115网盘]某片",
            "[微云]某片",
            "[移动云盘]某片",
        ]
        for t in yes:
            with self.subTest(title=t):
                self.assertTrue(looks_pan_title(t))
        no = [
            "", "阿凡达.Avatar.2009.1080p.BluRay",
            "阿凡达[国语配音/中文字幕].Avatar.2009",
            "【2023-12-10】阿凡达",
        ]
        for t in no:
            with self.subTest(title=t):
                self.assertFalse(looks_pan_title(t))


def _item(title):
    from src.models import ParseItem

    return ParseItem(title=title, detail_url="https://x/" + title[:4])


class TestTrimSearchItems(unittest.TestCase):
    def test_limit_keeps_pan_items(self):
        items = ([_item("普通种子%d" % i) for i in range(5)]
                 + [_item("[夸克下载]网盘片")])
        kept = trim_search_items(items, 3)
        self.assertEqual(len(kept), 3)
        self.assertEqual(kept[0].title, "[夸克下载]网盘片")   # 网盘置前
        self.assertTrue(all("普通种子" in i.title for i in kept[1:]))

    def test_no_limit_returns_all(self):
        items = [_item("普通%d" % i) for i in range(3)]
        self.assertEqual(trim_search_items(items, 0), items)
        self.assertEqual(trim_search_items(items, 10), items)


if __name__ == "__main__":
    unittest.main()
