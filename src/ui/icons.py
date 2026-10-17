"""运行时图标支持：优先加载真实高清 assets 资源，带回退矢量绘制。"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from ..constants import project_root

APP_ACCENT = QColor("#2563eb")
GRAY = QColor("#9aa0a6")


def _draw_fallback(pm: QPixmap, accent: QColor) -> None:
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = pm.width()

    # 背景渐变圆角矩形
    p.setPen(Qt.PenStyle.NoPen)
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, accent)
    grad.setColorAt(1.0, accent.darker(130))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(1, 1, s - 2, s - 2), s * 0.22, s * 0.22)

    # 播放高光三角
    path = QPainterPath()
    path.moveTo(QPointF(s * 0.36, s * 0.28))
    path.lineTo(QPointF(s * 0.68, s * 0.46))
    path.lineTo(QPointF(s * 0.36, s * 0.64))
    path.closeSubpath()
    p.setBrush(QBrush(QColor(255, 255, 255, 240)))
    p.drawPath(path)

    # 底部动感极速磁力下载条
    p.setPen(Qt.PenStyle.NoPen)
    bars = [
        (s * 0.26, s * 0.72, s * 0.48, max(2.0, s * 0.05), QColor(255, 255, 255, 220)),
        (s * 0.32, s * 0.80, s * 0.36, max(2.0, s * 0.05), QColor(56, 189, 248, 240)),
        (s * 0.38, s * 0.88, s * 0.24, max(2.0, s * 0.05), QColor(125, 211, 252, 255)),
    ]
    for x, y, w, h, col in bars:
        p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
    p.end()


def make_app_pixmap(size: int = 64, gray: bool = False) -> QPixmap:
    # 优先使用 assets 中生成的高质量图标
    png_path = os.path.join(project_root(), "assets", "6vdown.png")
    if os.path.isfile(png_path):
        base = QPixmap(png_path)
        if not base.isNull():
            scaled = base.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if gray:
                # 禁用时灰度化：将彩色图片转为浅灰/柔灰，让托盘图标明显褪色
                qimg = scaled.toImage().convertToFormat(QImage.Format.Format_ARGB32)
                for x in range(qimg.width()):
                    for y in range(qimg.height()):
                        c = qimg.pixelColor(x, y)
                        if c.alpha() > 0:
                            lum = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                            # 降低对比度与亮度，呈现半透弱化灰调
                            gray_val = min(180, int(lum * 0.7 + 50))
                            qimg.setPixelColor(x, y, QColor(gray_val, gray_val, gray_val, int(c.alpha() * 0.75)))
                return QPixmap.fromImage(qimg)
            return scaled

    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    _draw_fallback(pm, GRAY if gray else APP_ACCENT)
    return pm


def app_icon(gray: bool = False) -> QIcon:
    ico_path = os.path.join(project_root(), "assets", "6vdown.ico")
    if not gray and os.path.isfile(ico_path):
        icon = QIcon(ico_path)
        if not icon.isNull():
            return icon
    return QIcon(make_app_pixmap(64, gray))


def star_pixmap(size: int = 18) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#f59e0b")))
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
