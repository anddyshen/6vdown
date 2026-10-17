"""定时自动检查与订阅同步控制器。"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .log import get_logger

log = get_logger("scheduler")


class AutoParseController:
    """定时触发自动检查与订阅解析的控制器。"""

    def __init__(self, callback: Optional[Callable[[], None]] = None, interval_minutes: int = 240):
        self.callback = callback
        self.interval_minutes = max(5, int(interval_minutes))
        self._timer: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._enabled = False

    def set_interval(self, minutes: int) -> None:
        self.interval_minutes = max(5, int(minutes))

    def set_callback(self, cb: Callable[[], None]) -> None:
        self.callback = cb

    def start(self) -> bool:
        """启动后台定时循环。"""
        if self._enabled:
            return True
        if not self.callback:
            return False
        self._stop.clear()
        self._timer = threading.Thread(target=self._run_loop, daemon=True, name="AutoParseScheduler")
        self._timer.start()
        self._enabled = True
        log.info("AutoParseController 已启动，循环周期: %d 分钟", self.interval_minutes)
        return True

    def stop(self) -> None:
        if self._timer and self._timer.is_alive():
            self._stop.set()
        self._enabled = False
        log.info("AutoParseController 已停止")

    def is_active(self) -> bool:
        return self._enabled

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            # 按照配置的间隔等待
            wait_sec = self.interval_minutes * 60
            if self._stop.wait(wait_sec):
                break
            if self.callback and self._enabled:
                try:
                    log.info("定时器触发：开始执行订阅与更新检查...")
                    self.callback()
                except Exception as e:
                    log.warning("定时触发检查异常: %s", e)

    @staticmethod
    def next_run_text() -> str:
        return "定时自动检查已激活（按配置周期循环）"
