"""Qt 应用入口：主题、单实例、主窗口装配。"""
from __future__ import annotations

if __package__ in (None, ""):
    # 被当作脚本直接运行时（`python src/app.py`、编辑器 ▶ 运行当前文件、F5），
    # 本模块没有父包，相对导入会失败；此处先补好项目根路径，再以 src.app 包内
    # 模块的身份（run_name="__main__"）重新执行一遍，等价于 python -m src.app。
    import os as _os
    import runpy as _runpy
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    _runpy.run_module("src.app", run_name="__main__", alter_sys=True)
    raise SystemExit(0)

import sys

from PySide6.QtCore import QEvent, QLockFile, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox

from . import APP_NAME, __version__
from .constants import app_data_dir, legacy_data_dirs
from .ui.theme import apply_theme


class _NoWheelSpinFilter(QObject):
    """全局拦截数字输入框的鼠标滚轮：只能用上下箭头或键盘改值。

    Qt 默认在鼠标悬停时滚动滚轮就会改数字（设置页、搜索页上限等），
    很容易误改配置，故统一吞掉 QAbstractSpinBox 的 Wheel 事件。
    """

    def eventFilter(self, obj, event):  # noqa: N802
        if (event.type() == QEvent.Type.Wheel
                and isinstance(obj, QAbstractSpinBox)):
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def _migrate_legacy_data() -> None:
    """首次启动把旧版留在 %APPDATA% 的数据搬到程序目录（之后只读写程序目录）。"""
    import os
    import shutil

    from . import constants

    if not constants.is_frozen():
        return
    new_dir = app_data_dir()
    # 程序目录里已有数据（任一文件名）时优先保留，避免旧快照覆盖新数据
    for name in ("6vdown.db", "c2down.db"):
        if os.path.exists(os.path.join(new_dir, name)):
            return
    for old_dir in legacy_data_dirs():
        if os.path.normcase(os.path.normpath(old_dir)) == \
                os.path.normcase(os.path.normpath(new_dir)):
            continue
        old_db = ""
        for name in ("6vdown.db", "c2down.db"):
            p = os.path.join(old_dir, name)
            if os.path.exists(p):
                old_db = p
                break
        if not old_db:
            continue
        try:
            os.makedirs(new_dir, exist_ok=True)
            cfg_old = os.path.join(old_dir, "config.json")
            if os.path.exists(cfg_old):
                shutil.copy2(cfg_old, os.path.join(new_dir, "config.json"))
            shutil.copy2(old_db, os.path.join(new_dir, "6vdown.db"))
            cache_old = os.path.join(old_dir, "cache")
            if os.path.isdir(cache_old):
                shutil.copytree(cache_old, os.path.join(new_dir, "cache"),
                                dirs_exist_ok=True)
        except Exception:
            pass
        return


def _migrate_db_name() -> None:
    """Rename legacy 6vdown.db into new 6vdown.db in the current data dir."""
    import os
    import shutil

    d = app_data_dir()
    old = os.path.join(d, "c2down.db")
    new = os.path.join(d, "6vdown.db")
    if os.path.exists(old) and not os.path.exists(new):
        try:
            shutil.copy2(old, new)
        except Exception:
            pass

def run(argv: list | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} v{__version__}")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "system")

    # 全局禁用“鼠标滚轮改数字框”（避免误改设置），保留上下箭头/键盘
    app._no_wheel_guard = _NoWheelSpinFilter(app)
    app.installEventFilter(app._no_wheel_guard)

    # 便携数据目录 + 旧数据迁移（必须在 Database() 之前执行）
    # 顺序很重要：先把“程序目录里的 c2down.db”升级为 6vdown.db，
    # 再考虑从 %APPDATA% 旧目录搬迁（否则会用更旧的 APPDATA 快照覆盖较新数据）。
    _migrate_db_name()
    _migrate_legacy_data()

    # 单实例锁
    lock = QLockFile(__import__("os").path.join(app_data_dir(), "6vdown.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "6vdown 已在运行中（可查看系统托盘）。")
        return 0

    from .controller import Controller

    ctl = Controller(app)
    if ctl.cfg.get("start_behavior", "window") == "tray":
        ctl.window.hide()
        ctl.notify_tip("6vdown \u5df2\u5728\u540e\u53f0\u8fd0\u884c",
                       "\u5df2\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8\uff0c\u5355\u51fb\u56fe\u6807\u53ef\u6253\u5f00\u4e3b\u7a97\u53e3\u3002")
    else:
        ctl.window.show()
    try:
        lock_path = lock.fileName()
    except Exception:
        lock_path = ""
    app.aboutToQuit.connect(lambda: (ctl.cfg.save(), lock.unlock()))
    return app.exec()


if __name__ == "__main__":  # python -m src.app / python src/app.py
    sys.exit(run())
