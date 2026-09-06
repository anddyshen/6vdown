"""运行时绘制图标：应用图标（彩色/灰阶）、星标等。无需外部图片资源。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

APP_ACCENT = QColor("#2563eb")
GRAY = QColor("#9aa0a6")


def _draw_app(pm: QPixmap, accent: QColor) -> None:
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = pm.width()
    # 背景圆角方块
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(accent))
    p.drawRoundedRect(QRectF(1, 1, s - 2, s - 2), s * 0.22, s * 0.22)
    # 白色播放三角
    path = QPainterPath()
    path.moveTo(QPointF(s * 0.36, s * 0.30))
    path.lineTo(QPointF(s * 0.66, s * 0.46))
    path.lineTo(QPointF(s * 0.36, s * 0.62))
    path.closeSubpath()
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawPath(path)
    # 底部“接收/磁力”三横条
    p.setPen(QPen(QColor("#ffffff"), max(2.0, s * 0.06), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    for i, w in enumerate((0.34, 0.5, 0.66)):
        y = s * 0.76 + i * s * 0.06
        p.drawLine(QPointF(s * 0.24, y), QPointF(s * 0.24 + s * w * 0.9, y))
    p.end()


def make_app_pixmap(size: int = 64, gray: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    _draw_app(pm, GRAY if gray else APP_ACCENT)
    return pm


def app_icon(gray: bool = False) -> QIcon:
    return QIcon(make_app_pixmap(64, gray))


def star_pixmap(size: int = 18) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#f5a623")))
    path = QPainterPath()
    cx, cy = size / 2, size * 0.52
    R, r = size * 0.46, size * 0.20
    for i in range(10):
        ang = -3.14159 / 2 + i * 3.14159 / 5
        rad = R if i % 2 == 0 else r
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        path.lineTo(QPointF(x, y)) if i else path.moveTo(QPointF(x, y))
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return pm
