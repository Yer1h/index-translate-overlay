"""Полноэкранная рамка выбора региона для скриншота."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel, QRubberBand, QWidget


class RegionSelector(QWidget):
    # picked: QRect в логических координатах выбранного экрана
    picked = Signal(QRect, object)  # (rect, screen)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        screen = QGuiApplication.primaryScreen()
        for scr in QGuiApplication.screens():
            if scr.geometry().contains(QCursor.pos()):
                screen = scr
                break
        self.screen = screen

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())

        self._origin: QPoint | None = None
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self)

        self._hint = QLabel("Выделите область с текстом · Esc — отмена", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("""
            color: white; background: rgba(0,0,0,170);
            border-radius: 8px; padding: 8px 14px; font-size: 14px;
        """)
        self._hint.adjustSize()
        self._hint.move(screen.geometry().width() // 2
                        - self._hint.width() // 2, 24)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.position().toPoint()
            self._band.setGeometry(QRect(self._origin, self._origin))
            self._band.show()

    def mouseMoveEvent(self, e) -> None:
        if self._origin is not None:
            self._band.setGeometry(
                QRect(self._origin, e.position().toPoint()).normalized())

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        rect = QRect(self._origin, e.position().toPoint()).normalized()
        self._origin = None
        self._band.hide()
        self.hide()
        if rect.width() < 8 or rect.height() < 8:
            self.cancelled.emit()
            return
        self.picked.emit(rect, self.screen)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e) -> None:
        from PySide6.QtGui import QColor, QPainter, QPen
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))
        sel = self._band.geometry()
        if not sel.isNull() and sel.width() > 0:
            p.setPen(QPen(QColor(90, 160, 255), 2))
            p.drawRect(sel)
