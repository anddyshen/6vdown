"""Qt 后台任务封装：解析线程、发送任务、镜像探测、连接测试。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

from ..log import get_logger

log = get_logger("workers")


class ParseWorker(QThread):
    """后台解析任务（命令行滚动输出通过 log_line 信号实时发回）。"""

    log_line = Signal(str)
    done = Signal(dict)

    def __init__(self, service, enabled_blocks=None, include_unknown=True,
                 fetch_detail=True, polite_delay=0.3, parent=None):
        super().__init__(parent)
        self._service = service
        self._blocks = enabled_blocks
        self._unknown = include_unknown
        self._detail = fetch_detail
        self._delay = polite_delay

    def run(self) -> None:  # noqa: D102
        try:
            summary = self._service.run(
                enabled_blocks=self._blocks,
                include_unknown=self._unknown,
                fetch_detail=self._detail,
                polite_delay=self._delay,
                log_cb=lambda s: self.log_line.emit(s),
                cancel=lambda: self.isInterruptionRequested(),
            )
            self.done.emit(summary)
        except Exception as e:
            log.exception("解析线程异常")
            self.done.emit({"ok": False, "error": f"{type(e).__name__}: {e}"})

    def cancel(self) -> None:
        self.requestInterruption()


class TaskSignals(QObject):
    done = Signal(bool, str, str, str)  # ok, message, title, link


class SendRunnable(QRunnable):
    """把一个链接投递到指定下载主机（线程池执行）。"""

    def __init__(self, manager, url: str, title: str, host=None, source: str = ""):
        super().__init__()
        self.signals = TaskSignals()
        self._mgr = manager
        self._url = url
        self._title = title
        self._host = host
        self._source = source

    @Slot()
    def run(self) -> None:  # noqa: D102
        try:
            res = self._mgr.send(self._url, self._host)
            self.signals.done.emit(res.ok, res.message, self._title, self._url)
        except Exception as e:
            self.signals.done.emit(False, f"{type(e).__name__}: {e}",
                                   self._title, self._url)


class TestSignals(QObject):
    done = Signal(bool, str)


class TestHostRunnable(QRunnable):
    """测试某下载主机的连接。"""

    def __init__(self, manager, host):
        super().__init__()
        self.signals = TestSignals()
        self._mgr = manager
        self._host = host

    def run(self) -> None:  # noqa: D102
        try:
            res = self._mgr.test_host(self._host)
            self.signals.done.emit(res.ok, res.message)
        except Exception as e:
            self.signals.done.emit(False, f"{type(e).__name__}: {e}")


class ProbeSignals(QObject):
    done = Signal(dict)   # url -> (ok, note, len)
    log = Signal(str)


class MirrorProbeWorker(QThread):
    """逐项探测镜像可用性。"""

    done = Signal(dict)
    log = Signal(str)

    def __init__(self, db, urls: list, parent=None):
        super().__init__(parent)
        self._db = db
        self._urls = urls

    def run(self) -> None:  # noqa: D102
        from ..site import mirrors as mm

        result = {}
        try:
            for i, url in enumerate(self._urls, 1):
                self.log.emit(f"探测 {i}/{len(self._urls)}  {url}")
                try:
                    ok, note, length = mm.probe_mirrors([url])[url]
                except Exception as e:  # 单个镜像异常不中断整体
                    ok, note, length = False, f"{type(e).__name__}: {e}", 0
                result[url] = (ok, note, length)
                try:
                    self._db.mark_mirror(url, ok, note)
                except Exception:
                    pass
        except Exception as e:  # 保证 done 一定会发出，界面 busy 状态可被清除
            self.log.emit(f"探测异常：{type(e).__name__}: {e}")
        self.done.emit(result)
