"""应用日志：滚动写入 data/6vdown.log。"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from .constants import app_data_dir

_LOGGER: logging.Logger | None = None


def get_logger(name: str = "6vdown") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER.getChild(name)
    logger = logging.getLogger("6vdown")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            path = os.path.join(app_data_dir(), "6vdown.log")
            handler = RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            logger.addHandler(handler)
        except Exception:
            pass
    _LOGGER = logger
    return logger
