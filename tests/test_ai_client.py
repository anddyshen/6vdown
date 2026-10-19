"""AI 助手客户端与“本地/AI 双路径”推导测试（不访问真实 API）。

重点验证安全边界：
- Key 走 DPAPI 加密，配置里不落明文；
- 模型输出先本地校验（结构 + 实测解析条数），不过关一律降级本地推导；
- AI 不可用/报错时不能让向导崩掉。
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from src.config import Config  # noqa: E402
from src.site import ai_client  # noqa: E402
from src.site.modules import analyzer  # noqa: E402
from src.site.modules.analyzer import build_rule, derive_rule  # noqa: E402

from test_dyg7 import PAGE_MOVIE, SITE as DYG7_SITE  # noqa: E402

ENTRY = DYG7_SITE + "/dy/"
# 让推导稳定通过（真实页面都在数千字符以上）
PAGE = PAGE_MOVIE + "<!--" + ("padding " * 600) + "-->"


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeRequests:
    """替换 ai_client.requests：记录请求、返回预置响应。"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        return self.response


def _ok_reply(content: str) -> _FakeResponse:
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def _cfg(tmp, **over) -> Config:
    cfg = Config(os.path.join(tmp, "config.json"))
    cfg["ai_enabled"] = True
    cfg["ai_provider"] = "external"
    cfg["ai_base_url"] = "https://api.example.com/v1"
    cfg["ai_model"] = "test-model"
    cfg["ai_api_key_enc"] = ""
    for key, val in over.items():
        cfg[key] = val
    return cfg


class TestApiKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)

    def test_key_encrypted_in_config(self):
        cfg = _cfg(self.tmp.name)
        ai_client.set_api_key(cfg, "sk-secret-123")
        raw = open(cfg.path, "w")
        raw.close()
        cfg.save()
        disk = open(cfg.path, encoding="utf-8").read()
        self.assertNotIn("sk-secret-123", disk)
        self.assertEqual(ai_client.api_key_of(cfg), "sk-secret-123")

    def test_empty_key(self):
        cfg = _cfg(self.tmp.name)
        ai_client.set_api_key(cfg, "")
        self.assertEqual(cfg["ai_api_key_enc"], "")
        self.assertEqual(ai_client.api_key_of(cfg), "")


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = ai_client.requests

    def tearDown(self):
        ai_client.requests = self._orig

    def test_endpoint_and_auth_header(self):
        cfg = _cfg(self.tmp.name)
        ai_client.set_api_key(cfg, "sk-1")
        fake = _FakeRequests(_ok_reply("hi"))
        ai_client.requests = fake
        self.assertEqual(ai_client.chat(cfg, [{"role": "user", "content": "x"}]),
                         "hi")
        call = fake.calls[0]
        self.assertEqual(call["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-1")

    def test_endpoint_not_duplicated(self):
        cfg = _cfg(self.tmp.name, ai_base_url="https://x.com/v1/chat/completions")
        fake = _FakeRequests(_ok_reply("ok"))
        ai_client.requests = fake
        ai_client.chat(cfg, [{"role": "user", "content": "x"}])
        self.assertEqual(fake.calls[0]["url"], "https://x.com/v1/chat/completions")

    def test_http_error(self):
        cfg = _cfg(self.tmp.name)
        ai_client.requests = _FakeRequests(_FakeResponse(401, {}, "unauthorized"))
        with self.assertRaises(ai_client.AiError) as ctx:
            ai_client.chat(cfg, [{"role": "user", "content": "x"}])
        self.assertIn("401", str(ctx.exception))

    def test_malformed_response(self):
        cfg = _cfg(self.tmp.name)
        ai_client.requests = _FakeRequests(_FakeResponse(200, {"no": "choices"}))
        with self.assertRaises(ai_client.AiError):
            ai_client.chat(cfg, [{"role": "user", "content": "x"}])

    def test_missing_model(self):
        cfg = _cfg(self.tmp.name, ai_model="")
        with self.assertRaises(ai_client.AiError):
            ai_client.chat(cfg, [{"role": "user", "content": "x"}])

    def test_test_connection(self):
        cfg = _cfg(self.tmp.name)
        ai_client.requests = _FakeRequests(_ok_reply("pong"))
        ok, msg = ai_client.test_connection(cfg)
        self.assertTrue(ok)
        self.assertIn("pong", msg)
        ai_client.requests = _FakeRequests(_FakeResponse(500, {}, "boom"))
        ok, msg = ai_client.test_connection(cfg)
        self.assertFalse(ok)
        self.assertIn("500", msg)


class TestSanitizeAndParse(unittest.TestCase):
    def test_sanitize_removes_scripts_and_truncates(self):
        html = ("<html><script>var a=1;</script><style>.x{}</style>"
                "<!-- note --><li>条目</li>" + "x" * 100)
        out = ai_client.sanitize_html(html, limit=50)
        self.assertNotIn("var a", out)
        self.assertNotIn(".x{", out)
        self.assertNotIn("note", out)
        self.assertIn("条目", out)
        self.assertIn("样本已截断", out)

    def test_parse_fenced_json(self):
        rule = ai_client.parse_rule_text(
            "好的，规则如下：\n```json\n{\"module_id\": \"a\"}\n```\n说明完毕")
        self.assertEqual(rule["module_id"], "a")

    def test_parse_plain_json(self):
        self.assertEqual(ai_client.parse_rule_text('{"module_id": "b"}')["module_id"],
                         "b")

    def test_parse_invalid(self):
        with self.assertRaises(ai_client.AiError):
            ai_client.parse_rule_text("我不是 JSON")
        with self.assertRaises(ai_client.AiError):
            ai_client.parse_rule_text("")


class TestGenerateRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = ai_client.requests
        self.cfg = _cfg(self.tmp.name)

    def tearDown(self):
        ai_client.requests = self._orig

    def _good_rule(self):
        rule = build_rule(ENTRY, PAGE)
        self.assertTrue(rule)
        return rule

    def test_generate_ok_and_entry_filled(self):
        rule = self._good_rule()
        rule["entry_urls"] = []           # 模型可能漏掉入口
        ai_client.requests = _FakeRequests(
            _ok_reply("```json\n" + json.dumps(rule, ensure_ascii=False) + "\n```"))
        got = ai_client.generate_rule(self.cfg, ENTRY, PAGE)
        self.assertEqual(got["entry_urls"], [ENTRY])
        self.assertEqual(got["module_id"], rule["module_id"])

    def test_generate_requires_enabled(self):
        cfg = _cfg(self.tmp.name, ai_enabled=False)
        with self.assertRaises(ai_client.AiError):
            ai_client.generate_rule(cfg, ENTRY, PAGE)

    def test_prompt_contains_sample_and_no_login_data(self):
        rule = self._good_rule()
        ai_client.requests = _FakeRequests(
            _ok_reply(json.dumps(rule, ensure_ascii=False)))
        ai_client.generate_rule(self.cfg, ENTRY, PAGE)
        body = ai_client.requests.calls[0]["json"]
        text = json.dumps(body, ensure_ascii=False)
        self.assertIn(ENTRY, text)
        self.assertIn("登峰传奇", text)          # 样本已发送
        self.assertIn("严格 JSON", text)          # 系统提示：要求严格 JSON
        self.assertIn("date_anchor", text)        # 两种模式都讲清楚了
        self.assertNotIn("Authorization", text)   # Key 只放在 header，不进正文
        # few-shot 示例来自内置参考规则（保证与引擎同步）
        self.assertIn("block_name_map", text)


class TestDeriveRuleFallback(unittest.TestCase):
    """derive_rule：AI 不可靠时一律降级本地，且必须产出可用规则。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = ai_client.requests
        self.cfg = _cfg(self.tmp.name)

    def tearDown(self):
        ai_client.requests = self._orig

    def test_local_path(self):
        res = derive_rule(ENTRY, PAGE, cfg=self.cfg, use_ai=False)
        self.assertEqual(res["source"], "local")
        self.assertGreaterEqual(len(res["rule"]["entry_urls"]), 1)
        self.assertEqual(res["notes"], [])

    def test_ai_disabled_falls_back(self):
        cfg = _cfg(self.tmp.name, ai_enabled=False)
        res = derive_rule(ENTRY, PAGE, cfg=cfg, use_ai=True)
        self.assertEqual(res["source"], "local")
        self.assertTrue(res["rule"])

    def test_ai_error_falls_back(self):
        ai_client.requests = _FakeRequests(_FakeResponse(500, {}, "boom"))
        res = derive_rule(ENTRY, PAGE, cfg=self.cfg, use_ai=True)
        self.assertEqual(res["source"], "local")
        self.assertTrue(any("AI 生成失败" in n for n in res["notes"]))

    def test_ai_invalid_rule_falls_back(self):
        bad = {"module_id": "x", "name": "y", "entry_mode": "entries",
               "entry_urls": [ENTRY],
               "extract": {"mode": "rows", "row_re": "", "link_re": "a"}}
        ai_client.requests = _FakeRequests(_ok_reply(json.dumps(bad)))
        res = derive_rule(ENTRY, PAGE, cfg=self.cfg, use_ai=True)
        self.assertEqual(res["source"], "local")
        self.assertTrue(any("校验" in n for n in res["notes"]))

    def test_ai_rule_parses_nothing_falls_back(self):
        """AI 规则结构合法但一条都解析不出来 → 不能采用。"""
        rule = self._good_rule()
        rule["extract"]["row_re"] = "<li class=\"no-such-row\">.*?</li>"
        ai_client.requests = _FakeRequests(_ok_reply(json.dumps(rule)))
        res = derive_rule(ENTRY, PAGE, cfg=self.cfg, use_ai=True)
        self.assertEqual(res["source"], "local")
        self.assertTrue(any("试解析" in n or "解析到" in n for n in res["notes"]))

    def test_ai_accepted_when_valid(self):
        rule = self._good_rule()
        ai_client.requests = _FakeRequests(_ok_reply(
            "```json\n" + json.dumps(rule, ensure_ascii=False) + "\n```"))
        res = derive_rule(ENTRY, PAGE, cfg=self.cfg, use_ai=True)
        self.assertEqual(res["source"], "ai")
        self.assertEqual(res["notes"], [])
        self.assertEqual(res["rule"]["module_id"], rule["module_id"])

    def _good_rule(self):
        rule = build_rule(ENTRY, PAGE)
        self.assertTrue(rule)
        return rule


if __name__ == "__main__":
    unittest.main()
