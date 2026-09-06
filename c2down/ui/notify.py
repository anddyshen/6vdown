"""右下角提醒弹窗：渐变淡入 / 驻留 / 淡出；支持按钮确认条。"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_FADE_IN = 220
_FADE_OUT = 420
_MARGIN = 14
_BAR_GAP = 10


def _geometry() -> "QRect":
    from PySide6.QtCore import QRect

    scr = QApplication.primaryScreen()
    rect = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
    return rect


class NotifyBar(QWidget):
    """无边框毛玻璃风格提醒条。"""

    def __init__(self, title: str, message: str, seconds: int = 6,
                 accent: str = "#3b82f6", buttons: list | None = None,
                 on_action=None):
        super().__init__(None)
        self._buttons = buttons or []
        self._on_action = on_action
        self._accent = accent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(360)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._build(title, message)
        # 自动关闭计时
        self._timer = None
        if seconds and seconds > 0:
            from PySide6.QtCore import QTimer

            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.close_fade)
            self._timer.start(int(seconds * 1000))

    def _build(self, title: str, message: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget(self)
        card.setObjectName("toastCard")
        card.setStyleSheet(
            f"#toastCard {{ background: rgba(30,31,36,235); border-radius: 10px;"
            f" border: 1px solid rgba(255,255,255,28); }}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 8, 10)
        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {self._accent}; font-size: 14px;")
        t = QLabel(title or "")
        t.setStyleSheet("color: white; font-weight: 600; font-size: 13px;")
        t.setWordWrap(True)
        top.addWidget(dot)
        top.addWidget(t, 1)
        close = QPushButton("×")
        close.setFixedSize(22, 22)
        close.setStyleSheet(
            "background: transparent; color: #aab; border: none; font-size: 16px;"
        )
        close.clicked.connect(self.close_fade)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        cv.addLayout(top)
        msg = QLabel(message or "")
        msg.setStyleSheet("color: #d8dce2; font-size: 12px;")
        msg.setWordWrap(True)
        cv.addWidget(msg)
        if self._buttons:
            row = QHBoxLayout()
            row.addStretch(1)
            for text, _cb in self._buttons:
                btn = QPushButton(text)
                btn.setStyleSheet(
                    "background: rgba(255,255,255,24); color: white; border: none;"
                    "border-radius: 4px; padding: 4px 12px; font-size: 12px;"
                )
                btn.clicked.connect(lambda _=False, cb=_cb: self._fire(cb))
                row.addWidget(btn)
            cv.addLayout(row)
        root.addWidget(card)
        self.setStyleSheet("background: transparent;")

    def _fire(self, cb) -> None:
        try:
            if cb:
                cb()
        finally:
            self.close_fade()

    def fade_in(self) -> None:
        self.adjustSize()
        self.show()
        self.raise_()
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(_FADE_IN)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def close_fade(self) -> None:
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(_FADE_OUT)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(0.0)
        anim.finished.connect(self._really_close)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        if self._timer:
            self._timer.stop()

    def _really_close(self) -> None:
        self.close()
        self.deleteLater()


class NotifyManager:
    """多提醒管理：右下角向上堆叠，最多同时 4 条。"""

    def __init__(self):
        self._bars: list = []

    def show(self, title: str, message: str, seconds: int = 6,
             accent: str = "#3b82f6", buttons: list | None = None) -> None:
        bar = NotifyBar(title, message, seconds, accent, buttons)
        self._bars.append(bar)
        if len(self._bars) > 4:
            old = self._bars.pop(0)
            try:
                old.close()
                old.deleteLater()
            except Exception:
                pass
        bar.destroyed.connect(lambda _=None: self._drop(bar))
        self._layout()
        bar.fade_in()

    def _drop(self, bar) -> None:
        if bar in self._bars:
            self._bars.remove(bar)
        self._layout()

    def _layout(self) -> None:
        rect = _geometry()
        y = rect.bottom() - _MARGIN
        for bar in list(self._bars):
            bar.adjustSize()
            bar.move(rect.right() - bar.width() - _MARGIN,
                     y - bar.height())
            y -= bar.height() + _BAR_GAP

    def clear(self) -> None:
        for bar in list(self._bars):
            bar.close_fade()
