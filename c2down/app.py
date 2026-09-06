"""Qt 应用入口：主题、单实例、主窗口装配。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__
from .constants import app_data_dir, legacy_data_dir
from .ui.theme import apply_theme


def _migrate_legacy_data() -> None:
    """绿色模式：首次启动把旧 %APPDATA%\\C2Down 的数据复制到 exe 同级 data\\。"""
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
    db_file = os.path.join(new_dir, "c2down.db")
    if os.path.exists(db_file):
        return  # 已在便携目录建立过
    old_db = os.path.join(old_dir, "c2down.db")
    if not os.path.exists(old_db):
        return
    try:
        os.makedirs(new_dir, exist_ok=True)
        for name in ("c2down.db", "config.json"):
            src = os.path.join(old_dir, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(new_dir, name))
        cache_old = os.path.join(old_dir, "cache")
        if os.path.isdir(cache_old):
            shutil.copytree(cache_old, os.path.join(new_dir, "cache"),
                            dirs_exist_ok=True)
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

    # 单实例锁
    lock = QLockFile(__import__("os").path.join(app_data_dir(), "c2down.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "C2Down 已在运行中（可查看系统托盘）。")
        return 0

    from .controller import Controller

    ctl = Controller(app)
    if ctl.cfg.get("start_behavior", "window") == "tray":
        ctl.window.hide()
        ctl.notify_tip("C2Down \u5df2\u5728\u540e\u53f0\u8fd0\u884c",
                       "\u5df2\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8\uff0c\u5355\u51fb\u56fe\u6807\u53ef\u6253\u5f00\u4e3b\u7a97\u53e3\u3002")
    else:
        ctl.window.show()
    try:
        lock_path = lock.fileName()
    except Exception:
        lock_path = ""
    app.aboutToQuit.connect(lambda: (ctl.cfg.save(), lock.unlock()))
    return app.exec()
