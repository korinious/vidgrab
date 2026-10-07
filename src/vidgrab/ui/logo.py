"""The VidGrab mark: a white download arrow on a red rounded square.

One drawing function serves the header logo and every size of the .ico
(``scripts/make_icon.py``), so they always match.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

ACCENT = "#DC2626"


def paint_logo(painter: QPainter, rect: QRectF) -> None:
    s = min(rect.width(), rect.height())
    x0 = rect.x() + (rect.width() - s) / 2
    y0 = rect.y() + (rect.height() - s) / 2

    def pt(fx: float, fy: float) -> QPointF:
        return QPointF(x0 + fx * s, y0 + fy * s)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawRoundedRect(QRectF(x0, y0, s, s), s * 0.23, s * 0.23)

    # Thicker strokes at tiny sizes so the arrow survives 16x16.
    width = s * (0.12 if s <= 24 else 0.095)
    pen = QPen(QColor("#FFFFFF"), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arrow = QPainterPath(pt(0.5, 0.22))
    arrow.lineTo(pt(0.5, 0.60))
    painter.drawPath(arrow)
    head = QPainterPath(pt(0.31, 0.43))
    head.lineTo(pt(0.5, 0.62))
    head.lineTo(pt(0.69, 0.43))
    painter.drawPath(head)
    base = QPainterPath(pt(0.28, 0.78))
    base.lineTo(pt(0.72, 0.78))
    painter.drawPath(base)
    painter.restore()


def logo_image(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_logo(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def logo_pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    pixmap = QPixmap.fromImage(logo_image(round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class LogoWidget(QWidget):
    """The mark at a fixed logical size, drawn vectorially (sharp at any DPI)."""

    def __init__(self, size: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("VidGrab")

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_logo(painter, QRectF(self.rect()))
        painter.end()
