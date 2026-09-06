"""定时自动解析：接口预留（本期不启用，后续版本可挂接）。

用法（后续版本）：
    sched = AutoParseController(callback=controller.run_parse_background)
    sched.set_interval(minutes=30)   # 读取设置 parse_interval_min
    sched.start()  /  sched.stop()
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .log import get_logger

log = get_logger("scheduler")


class AutoParseController:
    """定时触发自动解析的控制器接口。

    本期仅在设置页展示占位与间隔控件（disabled），不启动后台线程。
    start() 在未实现前会返回 False，保证“留出接口”但不会误触发。
    """

    def __init__(self, callback: Optional[Callable[[], None]] = None,
                 interval_minutes: int = 30):
        self.callback = callback
        self.interval_minutes = max(1, int(interval_minutes))
        self._timer: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._enabled = False

    def set_interval(self, minutes: int) -> None:
        self.interval_minutes = max(1, int(minutes))

    def set_callback(self, cb: Callable[[], None]) -> None:
        self.callback = cb

    def start(self) -> bool:
        """启动定时器。当前版本未启用，返回 False。"""
        if self._enabled:
            return True
        if not self.callback:
            return False
        # 预留实现：
        #   self._stop.clear(); self._timer = threading.Thread(...); self._timer.start()
        log.info("AutoParseController.start() 被调用——定时自动解析将在后续版本启用。")
        self._enabled = True
        return True

    def stop(self) -> None:
        if self._timer and self._timer.is_alive():
            self._stop.set()
        self._enabled = False

    def is_active(self) -> bool:
        return self._enabled

    @staticmethod
    def next_run_text() -> str:
        return "定时自动解析将在后续版本提供（接口已预留）"
