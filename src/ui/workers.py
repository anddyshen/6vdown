"""Qt 后台任务封装：解析线程、搜索线程、详情抓取、发送任务、镜像探测、连接测试。"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

from ..log import get_logger

log = get_logger("workers")


class ParseWorker(QThread):
    """后台解析任务（命令行滚动输出通过 log_line 信号实时发回）。"""

    log_line = Signal(str)
    done = Signal(dict)

    def __init__(self, service, enabled_blocks=None, include_unknown=True,
                 fetch_detail=True, polite_delay=0.3, sites=None,
                 concurrency=1, parent=None):
        super().__init__(parent)
        self._service = service
        self._blocks = enabled_blocks
        self._unknown = include_unknown
        self._detail = fetch_detail
        self._delay = polite_delay
        self._sites = sites
        self._concurrency = concurrency

    def run(self) -> None:  # noqa: D102
        try:
            summary = self._service.run(
                enabled_blocks=self._blocks,
                include_unknown=self._unknown,
                fetch_detail=self._detail,
                polite_delay=self._delay,
                sites=self._sites,
                concurrency=self._concurrency,
                log_cb=lambda s: self.log_line.emit(s),
                cancel=lambda: self.isInterruptionRequested(),
            )
            self.done.emit(summary)
        except Exception as e:
            log.exception("解析线程异常")
            self.done.emit({"ok": False, "error": f"{type(e).__name__}: {e}"})

    def cancel(self) -> None:
        self.requestInterruption()


class SearchWorker(QThread):
    """后台关键词搜索（跨站点并发，日志通过 log_line 实时发回）。"""

    log_line = Signal(str)
    done = Signal(dict)

    def __init__(self, service, keyword: str = "", sites=None,
                 max_pages: int = 1, polite_delay: float = 0.3,
                 concurrency: int = 2, history_limit: int = 20,
                 limit: int = 0, auto_detail: int = 0, parent=None):
        super().__init__(parent)
        self._service = service
        self._kw = keyword
        self._sites = sites
        self._pages = max_pages
        self._delay = polite_delay
        self._concurrency = concurrency
        self._history_limit = history_limit
        self._limit = limit
        self._auto_detail = auto_detail

    def run(self) -> None:  # noqa: D102
        try:
            summary = self._service.search(
                keyword=self._kw, sites=self._sites,
                max_pages=self._pages, polite_delay=self._delay,
                concurrency=self._concurrency,
                history_limit=self._history_limit,
                limit=self._limit,
                auto_detail=self._auto_detail,
                log_cb=lambda s: self.log_line.emit(s),
                cancel=lambda: self.isInterruptionRequested(),
            )
            self.done.emit(summary)
        except Exception as e:
            log.exception("搜索线程异常")
            self.done.emit({"ok": False, "keyword": self._kw,
                            "error": f"{type(e).__name__}: {e}",
                            "items": [], "sites": [], "errors": [
                                f"{type(e).__name__}: {e}"]})

    def cancel(self) -> None:
        self.requestInterruption()


class DetailFetchWorker(QThread):
    """后台按需抓取若干条目的详情页资源（磁力/网盘/附件）。

    用于搜索页：搜索结果本身不含资源，需逐条抓详情页；逐条发
    ``row_done(row)`` 供界面增量刷新，结束发 ``finished_all(ok, fail)``。
    """

    row_done = Signal(int)
    finished_all = Signal(int, int)

    def __init__(self, fetcher, jobs, polite_delay: float = 0.3, parent=None):
        super().__init__(parent)
        self._fetcher = fetcher
        self._jobs = list(jobs or [])      # [(row, module_id, ParseItem)]
        self._delay = polite_delay
        self._ok = 0
        self._fail = 0

    def run(self) -> None:  # noqa: D102
        try:
            for row, mid, it in self._jobs:
                if self.isInterruptionRequested():
                    break
                module = _module_of(mid)
                if module is not None and getattr(it, "detail_url", ""):
                    # 论坛站偶发超时：放宽到 25s，失败再重试一次
                    for attempt in range(2):
                        try:
                            html, _ = self._fetcher.get(
                                it.detail_url, timeout=25)
                            module.parse_detail(html, it)
                            it.detail_ok = True
                            it.error = ""
                            break
                        except Exception as e:
                            it.error = f"{type(e).__name__}: {e}"
                            if attempt == 0:
                                time.sleep(1.5)
                if it.magnets:
                    self._ok += 1
                else:
                    self._fail += 1
                self.row_done.emit(row)
                if self._delay > 0:
                    time.sleep(min(self._delay, 1.5))
        except Exception as e:  # 保证 finished_all 一定会发出
            log.exception("详情抓取线程异常：%s", e)
        self.finished_all.emit(self._ok, self._fail)

    def cancel(self) -> None:
        self.requestInterruption()


def _module_of(module_id: str):
    from ..site.modules import get_module

    return get_module(module_id or "")


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
