"""Lucide SVG icons tinted with theme colours, rendered sharp at any DPI."""

from __future__ import annotations

from functools import cache, lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
APP_ICON = ASSETS_DIR / "vidgrab.ico"

# Device pixel ratios rendered into each QIcon: 100 %, 125 %, 150 %, 200 %.
_DPRS = (1.0, 1.25, 1.5, 2.0)


@cache
def _svg(name: str) -> str:
    return (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")


def available_icons() -> list[str]:
    return sorted(p.stem for p in ICONS_DIR.glob("*.svg"))


def render(name: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    """One tinted pixmap of ``size`` logical pixels at device pixel ratio ``dpr``."""
    svg = _svg(name).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = max(1, round(size * dpr))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


@lru_cache(maxsize=512)
def icon(name: str, color: str, size: int = 20) -> QIcon:
    """A QIcon with pixmaps for common DPI scales, so 125 %/150 % stay crisp."""
    result = QIcon()
    for dpr in _DPRS:
        result.addPixmap(render(name, color, size, dpr))
    return result
