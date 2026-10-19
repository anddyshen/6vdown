"""抓取器解码单测：GBK / UTF-8 自适应。

重点回归：部分 CDN 节点“meta 声明 gb2312、实际输出 UTF-8”，
旧逻辑按声明解码会得到乱码且不报错；新策略优先采用干净的 UTF-8 解码。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.site.fetcher import decode_bytes  # noqa: E402

_GBK_DECL = ('<html><head><meta http-equiv="Content-Type" '
             'content="text/html; charset=gb2312" /></head>'
             '<body>电影港高清下载</body></html>')
_UTF8_DECL = ('<html><head><meta charset="utf-8"></head>'
              '<body>BT之家社区</body></html>')


class TestDecodeBytes(unittest.TestCase):
    def test_real_gbk_page(self):
        text = decode_bytes(_GBK_DECL.encode("gb18030"))
        self.assertIn("电影港高清下载", text)

    def test_utf8_bytes_with_gbk_declaration(self):
        """声明 gb2312 但实际是 UTF-8（CDN 节点不一致）→ 必须解出正常中文。"""
        text = decode_bytes(_GBK_DECL.encode("utf-8"))
        self.assertIn("电影港高清下载", text)

    def test_utf8_page(self):
        text = decode_bytes(_UTF8_DECL.encode("utf-8"))
        self.assertIn("BT之家社区", text)

    def test_gbk_bytes_with_utf8_declaration(self):
        text = decode_bytes(_UTF8_DECL.encode("gb18030"))
        self.assertIn("BT之家社区", text)

    def test_broken_bytes_do_not_raise(self):
        text = decode_bytes(b"\xff\xfe\x00 garbage \xc4\xe3\xba\xc3")
        self.assertIsInstance(text, str)

    def test_ascii_only(self):
        text = decode_bytes(b"<html><body>plain</body></html>")
        self.assertEqual(text, "<html><body>plain</body></html>")


if __name__ == "__main__":
    unittest.main()
