"""AI 助手客户端：OpenAI 兼容协议（外部 API / 本地 Ollama、LM Studio）。

用途只有一个——给新站点生成解析规则 JSON。安全与稳定性边界：
- 只发送**用户主动分析**的站点页面样本（已去掉 script/style，默认截断 60KB）；
- API Key 用 Windows DPAPI 加密存配置（与下载主机密码同一机制）；
- 输出必须是严格 JSON，取回后由 `rule_store.validate_rule` 本地校验，
  **校验不过一律丢弃**；AI 失败自动降级到本地 AutoProfile 推导。

provider:
  - external：外部 OpenAI 兼容服务（DeepSeek / 智谱 /  moonshot / OpenAI …）
  - local：本机 Ollama / LM Studio（默认 http://localhost:11434/v1，无需 Key）
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import requests

from ..dpapi import decrypt_text, encrypt_text

DEFAULT_URL_EXTERNAL = "https://api.deepseek.com/v1"
DEFAULT_URL_LOCAL = "http://localhost:11434/v1"
DEFAULT_MODEL_EXTERNAL = "deepseek-chat"
DEFAULT_MODEL_LOCAL = "qwen2.5:7b"

# 页面样本上限（字符）：够模型看清结构，又不至于烧掉上下文
SAMPLE_LIMIT = 60000


class AiError(Exception):
    """AI 调用失败（网络/协议/解析/校验），调用方应降级到本地推导。"""


# ---------------------------------------------------------------- 配置
def provider_defaults(provider: str) -> tuple:
    """(base_url, model, 是否需要 Key)。"""
    if provider == "local":
        return DEFAULT_URL_LOCAL, DEFAULT_MODEL_LOCAL, False
    return DEFAULT_URL_EXTERNAL, DEFAULT_MODEL_EXTERNAL, True


def api_key_of(cfg) -> str:
    """读取明文 Key（DPAPI 解密）。"""
    return decrypt_text(cfg.get("ai_api_key_enc", "") or "")


def set_api_key(cfg, plain: str) -> None:
    """写入 Key（DPAPI 加密；空串清空）。"""
    cfg["ai_api_key_enc"] = encrypt_text((plain or "").strip())


def is_enabled(cfg) -> bool:
    """AI 助手是否可用（启用 + 填了服务地址）。"""
    if not cfg.get("ai_enabled", False):
        return False
    return bool(str(cfg.get("ai_base_url") or "").strip())


def _endpoint(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        raise AiError("未配置 AI 服务地址（base_url）")
    if b.endswith("/chat/completions"):
        return b
    return b + "/chat/completions"


# ---------------------------------------------------------------- 协议
def chat(cfg, messages: list, timeout: int = 90,
         temperature: float = 0.1) -> str:
    """OpenAI 兼容 chat/completions，返回 assistant 文本内容。"""
    base = str(cfg.get("ai_base_url") or "").strip()
    model = str(cfg.get("ai_model") or "").strip()
    if not model:
        raise AiError("未配置模型名（model）")
    headers = {"Content-Type": "application/json"}
    key = api_key_of(cfg)
    if key:
        headers["Authorization"] = "Bearer " + key
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    try:
        resp = requests.post(_endpoint(base), json=payload, headers=headers,
                             timeout=timeout)
    except Exception as e:
        raise AiError(f"请求失败：{type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise AiError(f"服务返回 {resp.status_code}：{(resp.text or '')[:200]}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise AiError(f"响应解析失败：{type(e).__name__}: {e}") from e


def test_connection(cfg, timeout: int = 20) -> tuple:
    """测试连接：返回 (ok, 说明)。"""
    try:
        text = chat(cfg, [{"role": "user", "content": "ping"}],
                    timeout=timeout)
    except AiError as e:
        return False, str(e)
    except Exception as e:      # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return True, ("连接正常" + (f"，模型回复：{text.strip()[:40]}" if text.strip()
                              else ""))


# ---------------------------------------------------------------- 样本与提示
def sanitize_html(html: str, limit: int = SAMPLE_LIMIT) -> str:
    """去噪并截断页面样本：script/style/注释，压缩空行。"""
    text = html or ""
    text = re.sub(r"(?is)<script\b.*?</script>", "", text)
    text = re.sub(r"(?is)<style\b.*?</style>", "", text)
    text = re.sub(r"(?is)<!--.*?-->", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    if len(text) > limit:
        text = text[:limit] + "\n<!-- 样本已截断 -->"
    return text


def _examples(limit: int = 2) -> str:
    """内置参考规则作 few-shot（随包分发，保证与引擎同步）。"""
    out = []
    try:
        from .modules.rule_store import bundled_dir, load_rule_file

        d = bundled_dir()
        for name in ("dyg7.json", "lou1.json"):
            data = load_rule_file(os.path.join(d, name))
            if not data:
                continue
            data = dict(data)
            data.pop("desc", None)
            out.append(json.dumps(data, ensure_ascii=False))
            if len(out) >= limit:
                break
    except Exception:
        return ""
    return "\n\n".join(out)


_SYSTEM_PROMPT = """你是一个“网页列表解析规则生成器”。用户会给你一个影视/BT 站点的
列表页 HTML 样本，你必须输出一个**严格 JSON**（不要任何解释、不要 Markdown 标记），
用于驱动一个正则规则引擎从同类页面提取条目。

规则 JSON 结构（字段全为可选，除注明外）：
{
  "module_id": "英文小写唯一ID",
  "name": "站点显示名",
  "encoding": "auto|gb18030|utf-8",
  "entry_mode": "entries|mirror",
  "entry_urls": ["https://入口地址/"],
  "max_pages": 1,
  "page_template": "{entry}index_{page}.html",
  "extract": {
    "mode": "rows|date_anchor",
    "row_re": "行容器正则（含一个捕获组或整体匹配；rows 模式必填）",
    "link_re": "详情页链接正则（必须含一个捕获组取 URL）",
    "title_re": "标题正则（含一个捕获组；留空则用链接文字）",
    "status_re": "状态正则（如 更新至18集/HD，含一个捕获组）",
    "date_re": "日期正则，形如 (\\\\d{4})-(\\\\d{1,2})-(\\\\d{1,2}) 或 \\\\[(\\\\d{1,2})-(\\\\d{1,2})\\\\]",
    "block_re": "区块标题/tab 按钮正则（名称捕获组放最后）",
    "block_row_re": "行级区块名正则（论坛每行自带版块名时用）",
    "block_name_map": {"版块名": "最新电影"},
    "block_map": {"/入口路径/": "最新电影"},
    "skip_row_re": "需要整行跳过的正则（如置顶公告）",
    "min_title_len": 2,
    "title_qual_re": "标题必须命中的正则（留空不限制）",
    "title_status_join": true,
    "alt_complete": false
  },
  "detail": {
    "magnet_re": "magnet:\\\\?xt=urn:[a-z0-9]+:[A-Za-z0-9_-]{16,}",
    "pan_res": ["pan.quark.cn", "pan.baidu.com"],
    "attach_res": ["attach-download", "/download/"],
    "desc_mode": "meta|info|text|none"
  }
}

要点：
1. link_re 必须能定位到**详情页**链接（排除导航、分类、用户、静态资源），且只取 URL；
2. rows 模式：row_re 每一行 = 一个条目，行内应能同时匹配到 link_re（必要）与
   title_re/date_re/status_re（可选）；
3. 列表页没有日期但页面里有日期锚点（日期文本与条目相邻）时用 date_anchor 模式，
   此时 row_re 留空、date_re 必填；
4. 正则用单引号包裹的 JSON 字符串写，注意反斜杠转义；
5. 不要臆造 URL 前缀，相对链接保持原样（引擎会自动补全）；
6. 若页面需要登录/JS 渲染导致看不到条目，就输出你能确定的部分，engine 验证会失败，
   用户会改用其它方式。

参考示例（两个真实站点的规则）：
{examples}
"""


def build_messages(entry_url: str, html: str, hint: str = "") -> list:
    """构造对话消息：系统提示（含 few-shot）+ 用户样本。"""
    system = _SYSTEM_PROMPT.replace("{examples}", _examples() or "（示例缺失）")
    user = [f"入口地址：{entry_url}\n"]
    if hint:
        user.append(f"本地自动推导的参考结果（可作参考，也可推翻）：\n{hint}\n")
    user.append("列表页 HTML 样本：\n" + sanitize_html(html))
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user)}]


# ---------------------------------------------------------------- 解析与生成
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_rule_text(text: str) -> dict:
    """从模型输出中解析出规则 dict；失败抛 AiError。"""
    raw = (text or "").strip()
    if not raw:
        raise AiError("模型返回空内容")
    m = _FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise AiError("模型输出中没有 JSON 对象")
    try:
        data = json.loads(raw[start:end + 1])
    except Exception as e:
        raise AiError(f"JSON 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise AiError("模型输出的 JSON 不是对象")
    return data


def generate_rule(cfg, entry_url: str, html: str, hint: str = "",
                  timeout: int = 90) -> dict:
    """调用 AI 生成规则 dict（已补全入口地址）；失败抛 AiError。"""
    if not is_enabled(cfg):
        raise AiError("AI 助手未启用或未配置服务地址")
    content = chat(cfg, build_messages(entry_url, html, hint), timeout=timeout)
    rule = parse_rule_text(content)
    rule["entry_urls"] = [u for u in (rule.get("entry_urls") or []) if u] \
        or [entry_url]
    rule.setdefault("name", "")
    return rule
