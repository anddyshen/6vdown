"""Qt 应用入口：主题、单实例、主窗口装配。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__
from .constants import app_data_dir, legacy_data_dir
from .ui.theme import apply_theme


def _migrate_legacy_data() -> None:
    """Green mode: migrate legacy APPDATA 6vdown data into data next to the exe."""
    import os
    import shutil

    from . import constants

    if not constants.is_frozen():
        return
    new_dir = app_data_dir()
    old_dir = legacy_data_dir()
    if os.path.normcase(os.path.normpath(new_dir)) == \
            os.path.normcase(os.path.normpath(old_dir)):
        return
    new_db = os.path.join(new_dir, "6vdown.db")
    old_db = os.path.join(old_dir, "c2down.db")
    if os.path.exists(new_db) or not os.path.exists(old_db):
        return
    try:
        os.makedirs(new_dir, exist_ok=True)
        cfg_old = os.path.join(old_dir, "config.json")
        if os.path.exists(cfg_old):
            shutil.copy2(cfg_old, os.path.join(new_dir, "config.json"))
        shutil.copy2(old_db, new_db)
        cache_old = os.path.join(old_dir, "cache")
        if os.path.isdir(cache_old):
            shutil.copytree(cache_old, os.path.join(new_dir, "cache"),
                            dirs_exist_ok=True)
    except Exception:
        pass


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

    # 便携数据目录 + 旧数据迁移（必须在 Database() 之前执行）
    _migrate_legacy_data()
    _migrate_db_name()

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
