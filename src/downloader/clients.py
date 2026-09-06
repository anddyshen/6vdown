"""qBittorrent / Transmission / Aria2 三客户端实现（requests）。"""
from __future__ import annotations

import json

import requests

from ..models import DownloadHost
from ..log import get_logger
from .base import BaseClient, SendResult

log = get_logger("downloader")
_UA = "6vdown/0.1 (magnet helper)"


def _err(e: Exception, where: str = "") -> SendResult:
    msg = f"{where}: {type(e).__name__}: {e}" if where else f"{type(e).__name__}: {e}"
    log.warning(msg)
    return SendResult(ok=False, message=msg)


class QBittorrentClient(BaseClient):
    """qBittorrent Web UI (API v2)。"""

    label = "qBittorrent"

    def _session(self, timeout: int):
        s = requests.Session()
        s.headers.update({"User-Agent": _UA})
        s.timeout = timeout
        return s

    def _login(self, s, timeout: int) -> SendResult:
        try:
            r = s.post(f"{self.base}/api/v2/auth/login",
                       data={"username": self.host.username or "",
                             "password": self.host.password or ""},
                       timeout=timeout)
            text = (r.text or "").strip()
            if "Ok" in text or (r.status_code == 200 and "Fails" not in text):
                return SendResult(True, "登录成功")
            return SendResult(False, f"qBittorrent 登录失败（HTTP {r.status_code}）")
        except Exception as e:
            return _err(e, "连接 qBittorrent 失败")

    def add(self, url: str, timeout: int = 25) -> SendResult:
        try:
            s = self._session(timeout)
            r = self._login(s, timeout)
            if not r.ok:
                return r
            resp = s.post(f"{self.base}/api/v2/torrents/add",
                          data={"urls": url}, timeout=timeout)
            text = (resp.text or "").strip()
            if resp.status_code == 200:
                return SendResult(True, "已发送至 qBittorrent", text[:120])
            return SendResult(False, f"添加失败 HTTP {resp.status_code}: {text[:120]}")
        except Exception as e:
            return _err(e, "qBittorrent 添加任务失败")

    def test(self, timeout: int = 8) -> SendResult:
        try:
            s = self._session(timeout)
            r = self._login(s, timeout)
            if not r.ok:
                return r
            v = s.get(f"{self.base}/api/v2/app/version", timeout=timeout)
            if v.status_code == 200 and v.text.strip():
                return SendResult(True, f"qBittorrent 连接正常，版本 {v.text.strip()[:40]}")
            return SendResult(False, f"qBittorrent 响应异常（HTTP {v.status_code}）")
        except Exception as e:
            return _err(e, "测试 qBittorrent 连接失败")

class TransmissionClient(BaseClient):
    """Transmission RPC。"""

    label = "Transmission"
    rpc_path = "/transmission/rpc"

    def _rpc(self, method: str, arguments: dict, timeout: int) -> SendResult:
        s = requests.Session()
        s.headers.update({"User-Agent": _UA})
        auth = None
        if self.host.username:
            auth = (self.host.username, self.host.password or "")
        sid = ""
        try:
            r0 = s.get(f"{self.base}{self.rpc_path}", timeout=timeout, auth=auth)
            sid = r0.headers.get("X-Transmission-Session-Id", "")
        except Exception:
            pass
        headers = {"X-Transmission-Session-Id": sid} if sid else {}
        payload = {"method": method, "arguments": arguments}
        resp = s.post(f"{self.base}{self.rpc_path}", data=json.dumps(payload),
                      headers={**headers, "Content-Type": "application/json"},
                      timeout=timeout, auth=auth)
        if resp.status_code == 409:
            sid = resp.headers.get("X-Transmission-Session-Id", "")
            resp = s.post(f"{self.base}{self.rpc_path}", data=json.dumps(payload),
                          headers={"X-Transmission-Session-Id": sid,
                                   "Content-Type": "application/json"},
                          timeout=timeout, auth=auth)
        try:
            body = resp.json()
        except Exception:
            return SendResult(False, f"Transmission 返回异常（HTTP {resp.status_code}）")
        if body.get("result") == "success":
            return SendResult(True, "success")
        return SendResult(False, f"Transmission: {body.get('result', resp.text[:100])}")

    def add(self, url: str, timeout: int = 25) -> SendResult:
        try:
            r = self._rpc("torrent-add", {"filename": url}, timeout)
            if r.ok:
                return SendResult(True, "已发送至 Transmission")
            return r
        except Exception as e:
            return _err(e, "Transmission 添加任务失败")

    def test(self, timeout: int = 8) -> SendResult:
        try:
            r = self._rpc("session-get", {}, timeout)
            if r.ok:
                return SendResult(True, "Transmission 连接正常")
            return SendResult(False, r.message)
        except Exception as e:
            return _err(e, "测试 Transmission 连接失败")


class Aria2Client(BaseClient):
    """Aria2 JSON-RPC。"""

    label = "Aria2"
    rpc_path = "/jsonrpc"

    def _params(self, args: list) -> list:
        if self.host.username:  # 用户名栏存 rpc-secret
            return [f"token:{self.host.username}", *args]
        return args

    def _call(self, method: str, args: list, timeout: int) -> SendResult:
        payload = {"jsonrpc": "2.0", "id": "6vdown", "method": method,
                   "params": self._params(args)}
        resp = requests.post(f"{self.base}{self.rpc_path}",
                             data=json.dumps(payload), timeout=timeout,
                             headers={"User-Agent": _UA,
                                      "Content-Type": "application/json"})
        try:
            body = resp.json()
        except Exception:
            return SendResult(False, f"Aria2 返回异常（HTTP {resp.status_code}）")
        if "error" in body:
            return SendResult(False, f"Aria2: {body['error'].get('message', body['error'])}")
        return SendResult(True, "success", json.dumps(body.get("result", ""), ensure_ascii=False))

    def add(self, url: str, timeout: int = 30) -> SendResult:
        try:
            r = self._call("aria2.addUri", [[url]], timeout)
            if r.ok:
                return SendResult(True, "已发送至 Aria2")
            return r
        except Exception as e:
            return _err(e, "Aria2 添加任务失败")

    def test(self, timeout: int = 8) -> SendResult:
        try:
            r = self._call("aria2.getVersion", [], timeout)
            if r.ok:
                return SendResult(True, "Aria2 连接正常")
            return SendResult(False, r.message)
        except Exception as e:
            return _err(e, "测试 Aria2 连接失败")

