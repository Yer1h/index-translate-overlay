"""Карточка-оверлей с переводом: без рамки, поверх всех, стриминг текста,
перетаскивание за полоску-ручку сверху."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

MAX_HEIGHT_FRACTION = 0.42  # от высоты экрана, дальше — скролл


class _DragStrip(QWidget):
    """Полоска-ручка: тащи карточку, двойной клик — закрепить."""

    def __init__(self, owner: "ResultPopup"):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("grip")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFixedHeight(20)
        lbl = QLabel("⠿")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.addWidget(lbl)
        self._off = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._off = (e.globalPosition().toPoint()
                         - self.owner.frameGeometry().topLeft())

    def mouseMoveEvent(self, e) -> None:
        if self._off is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move_clamped(e.globalPosition().toPoint() - self._off)

    def mouseReleaseEvent(self, e) -> None:
        self._off = None

    def mouseDoubleClickEvent(self, e) -> None:
        self.owner._toggle_pin()


class ResultPopup(QWidget):
    closed_sig = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.pinned = False
        self._full = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # не крадём фокус: печатаешь в мессенджере — горячая клавиша — попап
        # появился, но ввод продолжает идти в мессенджер
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("card")

        ui = self.cfg.data["ui"]
        self._opacity = float(ui.get("opacity", 0.95))
        max_w = int(ui.get("max_width_px", 560))
        alpha = int(self._opacity * 255)

        self._grip = _DragStrip(self)

        self._body = QPlainTextEdit()
        self._body.setReadOnly(True)
        self._body.setFrameStyle(0)
        self._body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._body.viewport().setAutoFillBackground(False)
        f = self._body.font()
        f.setPointSize(int(ui.get("font_size", 14)))
        self._body.setFont(f)

        self._status = QLabel("⏳ перевод…")
        self._status.setObjectName("status")

        self._copy_btn = QPushButton("Копировать")
        self._copy_btn.clicked.connect(self._copy)
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setToolTip("Закрепить (не закрывать кликом мимо)")
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._close_btn = QPushButton("✕")
        self._close_btn.clicked.connect(self.close)

        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        footer.addWidget(self._copy_btn)
        footer.addWidget(self._pin_btn)
        footer.addWidget(self._close_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 10)
        lay.setSpacing(4)
        lay.addWidget(self._grip)
        lay.addWidget(self._body, 1)
        lay.addLayout(footer)

        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setMaximumWidth(max_w)
        self.setMaximumHeight(int(screen.height() * MAX_HEIGHT_FRACTION))
        self.setMinimumWidth(260)

        self.setStyleSheet(f"""
            #card {{ background: rgba(24, 26, 32, {alpha});
                     border-radius: 10px; }}
            #grip, #grip QLabel {{ background: transparent; color: #6b7280; }}
            QPlainTextEdit {{ background: transparent; color: #e6e9f0;
                              border: none;
                              selection-background-color: #3b82f6; }}
            QLabel#status {{ color: #8b93a7; }}
            QPushButton {{ background: rgba(255,255,255,24); color: #d7dbe6;
                           border: none; border-radius: 6px; padding: 4px 10px; }}
            QPushButton:hover {{ background: rgba(255,255,255,44); }}
        """)

    # ------------------------------------------------------------ внешние
    def move_clamped(self, top_left) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(top_left.x(),
                                   screen.right() - self.width()))
        y = max(screen.top(), min(top_left.y(),
                                  screen.bottom() - self.height()))
        self.move(x, y)

    def show_at_cursor(self) -> None:
        pos = self._cursor_pos()
        self.resize(self.maximumWidth(), 120)
        self.move_clamped(pos + QPoint(12, 16))
        self.show()
        self._scroll_bottom()

    def show_at_rect(self, rect) -> None:
        """Под прямоугольником выделенной области экрана (логич. координаты)."""
        w = max(320, min(int(rect.width()), self.maximumWidth()))
        self.resize(w, 120)
        x = rect.center().x() - w // 2
        y = rect.bottom() + 10
        self.move_clamped(QPoint(x, y))
        self.show()
        self._scroll_bottom()

    def set_source_hint(self, text: str) -> None:
        if text:
            snippet = text.strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:120] + "…"
            self._status.setText(f"⏳ {snippet}")

    def append_stream(self, full_text: str) -> None:
        self._full = full_text
        cur = self._body.toPlainText()
        if cur == full_text:
            return
        self._body.setPlainText(full_text)
        self._fit_height()
        self._scroll_bottom()

    def finish(self, translation: str, meta: str) -> None:
        self._body.setPlainText(translation)
        self._fit_height()
        self._status.setText(meta)
        self._scroll_bottom()

    def fail(self, message: str) -> None:
        self._body.setPlainText("⚠ " + message)
        self._fit_height()
        self._status.setText("ошибка")

    # ------------------------------------------------------------ internals
    def _cursor_pos(self):
        from PySide6.QtGui import QCursor
        return QCursor.pos()

    def _fit_height(self) -> None:
        """Растёт под текст (до максимума), не выезжая за низ экрана."""
        doc_h = self._body.document().size().toSize().height()
        wanted = int(min(max(doc_h, 80) + 70, self.maximumHeight()))
        screen = QGuiApplication.primaryScreen().availableGeometry()
        max_h = screen.bottom() - self.y() - 8
        wanted = int(min(wanted, max(250, max_h)))
        if abs(wanted - self.height()) > 4:
            self.resize(self.width(), wanted)

    def _scroll_bottom(self) -> None:
        sb = self._body.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._body.toPlainText())
        self._status.setText("скопировано ✓")

    def _toggle_pin(self) -> None:
        self.pinned = not self.pinned
        self._pin_btn.setText("📍" if self.pinned else "📌")

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        self.closed_sig.emit()
        super().closeEvent(e)
