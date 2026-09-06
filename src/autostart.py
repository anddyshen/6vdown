"""开机自启（Windows 注册表 Run 键）。"""
from __future__ import annotations

import os
import sys

from . import constants

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "6vdown"


def is_frozen_app() -> bool:
    return constants.is_frozen()


def exe_path() -> str:
    """自启目标：打包后为 exe 自身；开发期为当前 python + main.py。"""
    if is_frozen_app():
        return f'"{sys.executable}"'
    main_py = os.path.join(constants.project_root(), "main.py")
    return f'"{sys.executable}" "{main_py}"'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def set_enabled(flag: bool) -> bool:
    """设置/取消自启。返回是否成功。"""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if flag:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, exe_path())
            else:
                try:
                    winreg.DeleteValue(k, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
