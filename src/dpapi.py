"""Windows DPAPI 密码加密（ctypes，无第三方依赖）。非 Windows 时降级 base64。"""
from __future__ import annotations

import base64
import ctypes
import os
import sys

_IS_WIN = sys.platform == "win32"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_local_machine = False


def _win_protect(data: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _win_unprotect(data: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def encrypt_text(plain: str) -> str:
    """加密为 base64 字符串；空串原样返回。"""
    if not plain:
        return ""
    data = plain.encode("utf-8")
    try:
        if _IS_WIN:
            return base64.b64encode(_win_protect(data)).decode("ascii")
    except Exception:
        pass
    return "base64:" + base64.b64encode(data).decode("ascii")


def decrypt_text(token: str) -> str:
    """解密；失败返回空串。"""
    if not token:
        return ""
    try:
        if token.startswith("base64:"):
            return base64.b64decode(token[7:]).decode("utf-8")
        if _IS_WIN:
            return _win_unprotect(base64.b64decode(token)).decode("utf-8")
    except Exception:
        return ""
    return ""
