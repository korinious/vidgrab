"""Where the main window opens and how big it is.

- First start: 1100 x min(900, screen height - 40), never wider than the screen, centred
  on the screen the window opens on (the one under the mouse).
- Later starts: the size and position saved at the last close (``ui.json``), but only
  if the window's title bar would still be on one of the current screens (a monitor
  may have been unplugged); the size is clamped to that screen.

All sizes are logical pixels, so at 150 % scaling a 1920x1080 screen counts as 1280x720.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect

DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 900
SCREEN_MARGIN = 40  # keep this much of the screen free around a new window
MIN_WIDTH = 640
MIN_HEIGHT = 520
TITLE_BAR_PROBE = 12  # px below the top edge: a point of the title bar must be on screen


@dataclass(frozen=True)
class SavedGeometry:
    """The window's normal (not maximised) geometry at the last close."""

    x: int
    y: int
    width: int
    height: int
    maximized: bool = False

    def rect(self) -> QRect:
        return QRect(self.x, self.y, self.width, self.height)

    @classmethod
    def from_rect(cls, rect: QRect, maximized: bool) -> SavedGeometry:
        return cls(rect.x(), rect.y(), rect.width(), rect.height(), maximized)

    def to_json(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "maximized": self.maximized,
        }

    @classmethod
    def from_json(cls, data: object) -> SavedGeometry | None:
        if not isinstance(data, dict):
            return None
        values = [data.get(k) for k in ("x", "y", "width", "height")]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            return None
        x, y, width, height = values
        if width <= 0 or height <= 0:
            return None
        return cls(x, y, width, height, data.get("maximized") is True)


def minimum_size(available: QRect) -> tuple[int, int]:
    """Never ask for more than the screen has (small laptops at 150 %)."""
    return (
        min(MIN_WIDTH, available.width() - SCREEN_MARGIN),
        min(MIN_HEIGHT, available.height() - SCREEN_MARGIN),
    )


def default_rect(available: QRect) -> QRect:
    width = min(DEFAULT_WIDTH, available.width() - SCREEN_MARGIN)
    height = min(DEFAULT_HEIGHT, available.height() - SCREEN_MARGIN)
    rect = QRect(0, 0, width, height)
    rect.moveCenter(available.center())
    return rect


def screen_showing(rect: QRect, screens: list[QRect]) -> QRect | None:
    """The available area of the screen that shows the window's title bar, if any."""
    probe = QPoint(rect.center().x(), rect.top() + TITLE_BAR_PROBE)
    for available in screens:
        if available.contains(probe):
            return available
    return None


def restored_rect(saved: SavedGeometry, screens: list[QRect]) -> QRect | None:
    """The saved geometry, clamped to its screen; None if it is on no screen any more."""
    rect = saved.rect()
    available = screen_showing(rect, screens)
    if available is None:
        return None
    rect.setWidth(min(rect.width(), available.width()))
    rect.setHeight(min(rect.height(), available.height()))
    # Pull it fully onto that screen (e.g. after a resolution change).
    rect.moveLeft(max(available.left(), min(rect.left(), available.right() - rect.width() + 1)))
    rect.moveTop(max(available.top(), min(rect.top(), available.bottom() - rect.height() + 1)))
    return rect


def initial_geometry(
    saved: SavedGeometry | None, screens: list[QRect], opening: QRect
) -> tuple[QRect, bool]:
    """(geometry, maximised) for the window: the saved one if still visible, else default.

    ``screens`` are the available areas of all screens, ``opening`` the one the window
    opens on when there is nothing (valid) to restore.
    """
    if saved is not None:
        rect = restored_rect(saved, screens)
        if rect is not None:
            return rect, saved.maximized
    return default_rect(opening), False
