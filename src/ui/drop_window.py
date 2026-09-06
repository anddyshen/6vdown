"""可拖拽小窗：接收网页链接 / 磁力文本，直接添加任务。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_RIGHT_MARGIN = 36
_BOTTOM_MARGIN = 56


class DropWindow(QWidget):
    dropped = Signal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._drag_offset = None
        self.setWindowTitle("拖拽到此处添加下载")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(260, 130)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        self._title = QLabel("⇩ 拖拽到这里")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            "background:transparent; color:#ffffff;"
            "font-size:18px; font-weight:700;")
        self._hint = QLabel("把网页链接或磁力拖进来\n即可发送到下载器")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            "background:transparent; color:#e6ecf5;"
            "font-size:12px; font-weight:600;")
        # 让点击/拖动事件穿透文字标签，落到窗口本身以实现整窗拖动
        for w in (self._title, self._hint):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addStretch(1)
        lay.addWidget(self._title)
        lay.addWidget(self._hint)
        lay.addStretch(1)
        self._restore_pos()

    # ------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: D102
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(22, 24, 30, 252))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 14, 14)
        p.setPen(QPen(QColor(110, 168, 254), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 14, 14)
        p.end()

    # ------------------------------------------------------------- 拖拽
    def dragEnterEvent(self, event) -> None:  # noqa: D102
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D102
        mime = event.mimeData()
        parts = []
        if mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    continue
                parts.append(u.toString())
        if mime.hasText():
            parts.append(mime.text())
        text = "\n".join(p for p in parts if p)
        if text.strip():
            self.dropped.emit(text)
        event.acceptProposedAction()

    # ------------------------------------------------------------- 拖动
    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._drag_offset is not None and (
                event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102
        if self._drag_offset is not None:
            # 用户完成了一次拖动，记住位置（后续启动还原此处）
            try:
                self.cfg["drop_geometry"] = [self.x(), self.y()]
                self.cfg["drop_geometry_saved"] = True
                self.cfg.save()
            except Exception:
                pass
        self._drag_offset = None
        event.accept()

    # ------------------------------------------------------------- 位置
    def _restore_pos(self) -> None:
        use_saved = False
        try:
            use_saved = bool(self.cfg["drop_geometry_saved"])
        except Exception:
            pass
        if use_saved:
            try:
                g = self.cfg["drop_geometry"]
                if isinstance(g, list) and len(g) == 2:
                    self.move(int(g[0]), int(g[1]))
                    return
            except Exception:
                pass
        # 默认放在主屏右下角（可用区域，避开任务栏）
        try:
            scr = QGuiApplication.primaryScreen()
            rect = scr.availableGeometry() if scr else None
            if rect:
                x = rect.right() - self.width() - _RIGHT_MARGIN
                y = rect.bottom() - self.height() - _BOTTOM_MARGIN
                self.move(QPoint(x, y))
        except Exception:
            pass

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
