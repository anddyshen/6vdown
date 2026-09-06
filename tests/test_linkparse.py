"""链接解析单测。"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from c2down.linkparse import parse_text, classify_http, magnet_hash  # noqa: E402

M1 = ("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
      "&dn=Test+Movie&tr=http://tracker.example.com:8080/announce")


class TestLinkParse(unittest.TestCase):
    def test_magnet_only(self):
        r = parse_text(M1)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].kind, "magnet")

    def test_http_torrent(self):
        r = parse_text("a http://x.com/a/b.torrent b")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].sub, "torrent")

    def test_http_pt_direct(self):
        r = parse_text("https://pt.example.com/download.php?id=3&passkey=abc")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].sub, "pt")

    def test_http_web(self):
        r = parse_text("看 https://news.example.com/a/b 一下")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].sub, "web")

    def test_mixed(self):
        text = f"先一个 {M1} 再一个 http://t.cn/x.torrent 完"
        r = parse_text(text)
        kinds = [x.kind for x in r]
        self.assertIn("magnet", kinds)
        self.assertIn("http", kinds)

    def test_tracker_not_split_from_magnet(self):
        # &tr=http://... 属于磁力自身，不应单独成为 http 条目
        r = parse_text(M1)
        self.assertEqual(len(r), 1)

    def test_magnet_hash(self):
        self.assertEqual(
            magnet_hash(M1),
            "0123456789abcdef0123456789abcdef01234567",
        )


if __name__ == "__main__":
    unittest.main()
