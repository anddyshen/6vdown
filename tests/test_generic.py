"""通用规则引擎回归测试：规则 JSON 必须与内置模块输出逐字段一致。

样本 HTML 直接复用各站点模块的单测样本（tests/test_*.py），
规则用 src/site/modules/rules/*.json（内置参考规则）。
这同时验证两件事：引擎正确性 + 规则语言表达力足以覆盖 4 类真实站点。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from src.site.modules.generic import GenericModule  # noqa: E402
from src.site.modules.hao6v import Hao6vModule  # noqa: E402
from src.site.modules.dygang import DygangModule  # noqa: E402
from src.site.modules.dyg7 import Dyg7Module  # noqa: E402
from src.site.modules.lou1 import Lou1Module  # noqa: E402
from src.site.modules import get_module, registry  # noqa: E402
from src.site.modules.rule_store import (  # noqa: E402
    bundled_dir, load_bundled_modules, load_rule_file, rule_from_dict,
    save_rule, validate_rule,
)

# 复用各站点单测里的真实结构样本
from test_dygang import HOME_HTML as DYGANG_HTML, SITE as DYGANG_SITE  # noqa: E402
from test_dyg7 import (  # noqa: E402
    DETAIL_HTML as DYG7_DETAIL, PAGE_DUANJU, PAGE_GUOJU, PAGE_MOVIE, SITE as DYG7_SITE,
)
from test_lou1 import (  # noqa: E402
    LIST_HTML as LOU_LIST, SITE as LOU_SITE, THREAD_HTML as LOU_THREAD,
)
from test_increment import (  # noqa: E402
    DETAIL_HTML as HAO6V_DETAIL, SITE as HAO6V_SITE, home_html as hao6v_home,
)

HAO6V_HTML = hao6v_home(5, "09-02")


def _rule(module_id: str) -> GenericModule:
    path = os.path.join(bundled_dir(), f"{module_id}.json")
    data = load_rule_file(path)
    assert data, f"缺少参考规则 {path}"
    return GenericModule(rule_from_dict(data), source="builtin")


def _snap(items) -> list:
    """比对快照：标题/日期/区块/URL/红链/经典（磁力 label 属展示性字段不比）。"""
    return sorted(
        (it.title, it.date, it.block, it.detail_url, it.is_red, it.is_classic)
        for it in items)


class TestHao6vRuleParity(unittest.TestCase):
    def test_list_parity(self):
        builtin = Hao6vModule().parse_list(HAO6V_HTML, HAO6V_SITE)
        generic = _rule("hao6v").parse_list(HAO6V_HTML, HAO6V_SITE)
        self.assertEqual(_snap(builtin), _snap(generic))
        self.assertEqual(len(generic), 2)

    def test_detail_parity(self):
        from src.models import ParseItem

        b, g = ParseItem(title="x"), ParseItem(title="x")
        Hao6vModule().parse_detail(HAO6V_DETAIL, b)
        _rule("hao6v").parse_detail(HAO6V_DETAIL, g)
        self.assertEqual([m.url for m in b.magnets], [m.url for m in g.magnets])
        self.assertEqual(len(g.magnets), 2)


class TestDygangRuleParity(unittest.TestCase):
    def test_list_parity(self):
        builtin = DygangModule().parse_list(DYGANG_HTML, DYGANG_SITE)
        generic = _rule("dygang").parse_list(DYGANG_HTML, DYGANG_SITE)
        self.assertEqual(_snap(builtin), _snap(generic))
        self.assertEqual(len(generic), 3)

    def test_alt_completion(self):
        generic = _rule("dygang").parse_list(DYGANG_HTML, DYGANG_SITE)
        titles = {it.title for it in generic}
        self.assertIn("偷天父子兵", titles)


class TestDyg7RuleParity(unittest.TestCase):
    def test_movie_page_parity(self):
        entry = DYG7_SITE + "/dy/"
        builtin = Dyg7Module().parse_list(PAGE_MOVIE, DYG7_SITE, entry)
        generic = _rule("dyg7").parse_list(PAGE_MOVIE, DYG7_SITE, entry)
        self.assertEqual(_snap(builtin), _snap(generic))

    def test_tv_page_status_join_parity(self):
        entry = DYG7_SITE + "/dsj/dlj/"
        builtin = Dyg7Module().parse_list(PAGE_GUOJU, DYG7_SITE, entry)
        generic = _rule("dyg7").parse_list(PAGE_GUOJU, DYG7_SITE, entry)
        self.assertEqual(_snap(builtin), _snap(generic))
        titles = {it.title for it in generic}
        self.assertIn("把黑夜点燃（更新至18集）", titles)

    def test_block_map_parity(self):
        entry = DYG7_SITE + "/duanju/"
        builtin = Dyg7Module().parse_list(PAGE_DUANJU, DYG7_SITE, entry)
        generic = _rule("dyg7").parse_list(PAGE_DUANJU, DYG7_SITE, entry)
        self.assertEqual(_snap(builtin), _snap(generic))
        self.assertEqual(generic[0].block, "短剧")

    def test_detail_parity(self):
        from src.models import ParseItem

        b, g = ParseItem(title="x"), ParseItem(title="x")
        Dyg7Module().parse_detail(DYG7_DETAIL, b)
        _rule("dyg7").parse_detail(DYG7_DETAIL, g)
        self.assertEqual([m.url for m in b.magnets], [m.url for m in g.magnets])
        self.assertEqual(len(g.magnets), 1)


class TestLou1RuleParity(unittest.TestCase):
    def test_list_parity(self):
        builtin = Lou1Module().parse_list(LOU_LIST, LOU_SITE)
        generic = _rule("lou1").parse_list(LOU_LIST, LOU_SITE)
        self.assertEqual(_snap(builtin), _snap(generic))
        self.assertEqual(len(generic), 3, "置顶公告必须被跳过")

    def test_detail_parity(self):
        from src.models import ParseItem

        b, g = ParseItem(title="x", detail_url=LOU_SITE + "thread-1.htm"), \
            ParseItem(title="x", detail_url=LOU_SITE + "thread-1.htm")
        Lou1Module().parse_detail(LOU_THREAD, b)
        _rule("lou1").parse_detail(LOU_THREAD, g)
        self.assertEqual([(m.kind, m.url) for m in b.magnets],
                         [(m.kind, m.url) for m in g.magnets])
        self.assertEqual(len(g.magnets), 4)


class TestRuleValidation(unittest.TestCase):
    def test_bundled_rules_all_valid(self):
        mods = load_bundled_modules()
        ids = {m.meta.module_id for m in mods}
        self.assertEqual(ids, {"hao6v", "dygang", "dyg7", "lou1"})
        for m in mods:
            self.assertTrue(m.meta.name)
            self.assertFalse(m.meta.builtin)

    def test_missing_fields(self):
        errors = validate_rule({"name": "x"})
        self.assertTrue(any("module_id" in e for e in errors))
        errors = validate_rule({"module_id": "x", "name": "y",
                                "entry_mode": "entries"})
        self.assertTrue(any("entry_urls" in e for e in errors))

    def test_bad_regex(self):
        errors = validate_rule({
            "module_id": "x", "name": "y", "entry_mode": "entries",
            "entry_urls": ["https://a.com/"],
            "extract": {"mode": "rows", "row_re": "(unclosed",
                        "link_re": "a"},
        })
        self.assertTrue(any("row_re" in e for e in errors))

    def test_module_id_charset(self):
        errors = validate_rule({"module_id": "坏 id!", "name": "y"})
        self.assertTrue(any("module_id" in e for e in errors))

    def test_from_dict_roundtrip(self):
        rule = rule_from_dict(load_rule_file(
            os.path.join(bundled_dir(), "dyg7.json")))
        again = GenericModule.__new__(GenericModule)  # 仅验证 to_dict 结构
        d = rule.to_dict()
        self.assertEqual(d["extract"]["block_map"]["/dy/"], "最新电影")
        self.assertEqual(d["max_pages"], 2)


class TestUserRuleOverridesBuiltin(unittest.TestCase):
    """用户规则（data/modules/<id>.json）覆盖同 ID 内置模块——向导保存路径的核心。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        import src.site.modules.rule_store as store

        self.store = store
        self._orig_dir = store.rules_dir
        store.rules_dir = lambda: self.tmp.name
        self.addCleanup(self._restore)

    def _restore(self):
        self.store.rules_dir = self._orig_dir
        registry.reload_external_modules()   # 还原注册表全局状态

    def test_saved_rule_becomes_selectable_module(self):
        data = load_rule_file(os.path.join(bundled_dir(), "dyg7.json"))
        data["name"] = "电影港新版（自定义）"
        path = save_rule(data)
        self.assertTrue(os.path.isfile(path))

        registry.reload_external_modules()
        mod = get_module("dyg7")
        self.assertIsNotNone(mod)
        self.assertFalse(mod.meta.builtin, "用户规则应覆盖内置模块")
        self.assertEqual(mod.meta.name, "电影港新版（自定义）")

        # 覆盖后解析结果不变（仍与内置模块一致）
        got = mod.parse_list(PAGE_MOVIE, DYG7_SITE, entry_url=DYG7_SITE + "/dy/")
        want = Dyg7Module().parse_list(PAGE_MOVIE, DYG7_SITE,
                                       entry_url=DYG7_SITE + "/dy/")
        self.assertEqual({(it.title, it.detail_url) for it in got},
                         {(it.title, it.detail_url) for it in want})

    def test_bad_rule_file_is_skipped(self):
        with open(os.path.join(self.tmp.name, "broken.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"module_id": "broken", "extract": {"link_re": ""}}')
        registry.reload_external_modules()
        self.assertIsNone(get_module("broken"), "坏规则不得进入注册表")


if __name__ == "__main__":
    unittest.main()
