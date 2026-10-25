"""Захват региона экрана: через QScreen.grabWindow (корректный DPI) → PIL."""
from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage


def grab_screen_region(screen, rect) -> Image.Image:
    """rect — QRect в логических координатах `screen`.
    Возвращает PIL.Image в физическом разрешении (DPI-aware процесс)."""
    sgeo = screen.geometry()
    rel = rect.translated(-sgeo.topLeft())
    pix = screen.grabWindow(0, rel.x(), rel.y(), rel.width(), rel.height())
    qimg = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    buf = bytes(ptr)
    stride = qimg.bytesPerLine()
    img = Image.frombytes("RGBA", (w, h), buf, "raw", "RGBA", stride)
    return img.convert("RGB")
