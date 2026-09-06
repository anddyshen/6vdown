"""Unit tests for pinyin initial search helpers."""
import unittest

from src.pinyin_search import initials, match, clear_cache


class PinyinSearchTest(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_initials_cjk(self):
        self.assertEqual(initials("电影"), "dy")

    def test_initials_mixed(self):
        self.assertEqual(initials("2026动作惊悚HD"), "dzjs")

    def test_match_substring(self):
        self.assertTrue(match(["2026高分剧情《猫鼬》"], "猫鼬"))
        self.assertTrue(match(["2026高分剧情《猫鼬》"], "2026"))
        self.assertFalse(match(["动作惊悚"], "dongzuo"))

    def test_match_pinyin_initials(self):
        self.assertTrue(match(["动作惊悚"], "dz"))
        self.assertTrue(match(["动作惊悚"], "dzjs"))
        self.assertTrue(match(["2026高分剧情《猫鼬》"], "gfjq"))
        self.assertFalse(match(["喜剧"], "dz"))

    def test_match_empty(self):
        self.assertTrue(match(["任意"], ""))

    def test_match_multi_field(self):
        fields = ["一些不相关", "动画电影 中文名"]
        self.assertTrue(match(fields, "dhdy"))
        self.assertFalse(match(["动作"], "xj"))


if __name__ == "__main__":
    unittest.main()
