# -*- mode: python ; coding: utf-8 -*-
"""6vdown PyInstaller 精简打包规范文件。
实现轻量化绿色免安装版单文件 EXE，剔除未使用的 Qt 大型模块及冗余组件。
"""
from __future__ import annotations

import os
import sys

block_cipher = None

# 1. 明确排除未使用的 Python 标准库与 Qt 重型子模块
excluded_modules = [
    # 标准库冗余
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "lib2to3",
    "test",
    "email.test",
    "xmlrpc",
    "turtle",
    # Qt 未使用的重型模块（避免将 WebEngine、Quick、3D 等上百兆文件打入）
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtCharts",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtAsyncio",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("src/site/modules/rules", "src/site/modules/rules"),
    ],
    hiddenimports=[
        "pypinyin",
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        "sqlite3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)

# 2. 二进制精准过滤：仅剔除 Qt 冗余组件，严禁触碰 Python 自身的 _sqlite3 等标准库
def is_unwanted_binary(dest_path: str) -> bool:
    low = os.path.basename(dest_path).lower()
    full_low = dest_path.lower().replace("/", "\\")

    # 过滤 Qt 插件：仅保留 platforms, styles, imageformats
    if "pyside6\\plugins\\" in full_low:
        allowed_plugins = ["plugins\\platforms", "plugins\\styles", "plugins\\imageformats"]
        if not any(p in full_low for p in allowed_plugins):
            return True
        return False

    # 过滤 Qt6 动态库：仅保留 core, gui, widgets, network
    if low.startswith("qt6") and low.endswith(".dll"):
        allowed_qt6 = {
            "qt6core.dll",
            "qt6gui.dll",
            "qt6widgets.dll",
            "qt6network.dll",
        }
        return low not in allowed_qt6

    # 过滤 PySide6 各模块 .pyd
    if "pyside6" in full_low and low.endswith(".pyd"):
        allowed_pyd = {
            "qtcore.pyd",
            "qtgui.pyd",
            "qtwidgets.pyd",
            "qtnetwork.pyd",
            "__init__.pyd",
        }
        return not any(low.endswith(ap) for ap in allowed_pyd)

    return False


filtered_binaries = []
for item in a.binaries:
    dest_name = item[0]
    if not is_unwanted_binary(dest_name):
        filtered_binaries.append(item)

# 3. 数据过滤：剔除 Qt 大量语言翻译 .qm 文件等
filtered_datas = []
for item in a.datas:
    dest_name = item[0].lower()
    if "translations" in dest_name or "qml" in dest_name:
        continue
    filtered_datas.append(item)

pyz = PYZ(a.pure, optimize=1)

exe = EXE(
    pyz,
    a.scripts,
    filtered_binaries,
    filtered_datas,
    [],
    name="6vdown",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/6vdown.ico"],
)
