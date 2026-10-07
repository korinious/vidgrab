"""Small themed building blocks for the modern UI.

Widgets style themselves through dynamic properties (``variant``, ``role``, ``tone``) that
the QSS in ``ui/theme.py`` targets, and re-tint their icons when the theme changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeyEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from vidgrab.ui.icons import icon, render
from vidgrab.ui.theme import TOUCH_TARGET, Palette, current_palette, theme_manager

TONES: dict[str, Callable[[Palette], str]] = {
    "text": lambda p: p.text,
    "muted": lambda p: p.muted,
    "accent": lambda p: p.accent,
    "on_accent": lambda p: p.on_accent,
    "success": lambda p: p.success_fg,
    "error": lambda p: p.error_fg,
    "warning": lambda p: p.warning_fg,
    "link": lambda p: p.link,
}


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    """Set a style property and re-apply the stylesheet rules that depend on it."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def bind_icon(button: QAbstractButton, name: str, tone: str = "text", size: int = 20) -> None:
    """Give a button a Lucide icon in a theme colour that follows theme changes."""

    def refresh(palette: Palette | None = None) -> None:
        palette = palette or current_palette()
        current = button.property("_icon")
        if current:
            button.setIcon(icon(current, TONES[button.property("_tone")](palette), size))

    button.setProperty("_icon", name)
    button.setProperty("_tone", tone)
    button.setIconSize(QSize(size, size))
    refresh()
    if not button.property("_icon_bound"):
        button.setProperty("_icon_bound", True)
        theme_manager().changed.connect(refresh)


class IconButton(QToolButton):
    """A 44 x 44 icon-only button with a tooltip and an accessible name."""

    def __init__(
        self, icon_name: str, label: str, tone: str = "text", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setMinimumSize(TOUCH_TARGET, TOUCH_TARGET)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_icon(self, icon_name, tone)

    def set_icon_name(self, name: str) -> None:
        bind_icon(self, name, self.property("_tone") or "text")


def text_button(
    text: str,
    variant: str | None = None,
    icon_name: str | None = None,
    tone: str = "text",
    parent: QWidget | None = None,
) -> QPushButton:
    button = QPushButton(text, parent)
    if variant:
        button.setProperty("variant", variant)
    button.setAccessibleName(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if icon_name:
        bind_icon(button, icon_name, tone, 18)
    # Qt's size hint ignores the QSS padding next to an icon; never clip the label.
    bold = QFont(button.font())
    bold.setWeight(QFont.Weight.DemiBold)
    text_width = QFontMetrics(bold).horizontalAdvance(text)
    button.setMinimumWidth(text_width + (26 if icon_name else 0) + 34)
    return button


class IconLabel(QLabel):
    """A tinted icon as a label (status icons, field decorations)."""

    def __init__(
        self, icon_name: str, tone: str = "muted", size: int = 18, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._name, self._tone, self._size = icon_name, tone, size
        self.setFixedSize(size + 4, size + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh()
        theme_manager().changed.connect(self._refresh)

    def set_icon(self, icon_name: str, tone: str | None = None) -> None:
        self._name = icon_name
        self._tone = tone or self._tone
        self._refresh()

    def _refresh(self, palette: Palette | None = None) -> None:
        palette = palette or current_palette()
        dpr = self.devicePixelRatioF() or 1.0
        self.setPixmap(render(self._name, TONES[self._tone](palette), self._size, dpr))


def label(text: str = "", role: str | None = None, tone: str | None = None) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if tone:
        widget.setProperty("tone", tone)
    return widget


def chip(text: str = "", tone: str | None = None) -> QLabel:
    widget = label(text, role="chip", tone=tone)
    widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return widget


def card(parent: QWidget | None = None) -> QFrame:
    frame = QFrame(parent)
    frame.setProperty("card", True)
    return frame


class ElidedLabel(QLabel):
    """One line, '…' when too long; the full text stays in text() and the tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(10, self.width())
        elided = QFontMetrics(self.font()).elidedText(
            self._full, Qt.TextElideMode.ElideRight, width
        )
        super().setText(elided)


class Banner(QFrame):
    """Amber notice with an icon (e.g. "Deno not found")."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "banner")
        self._label = QLabel()
        self._label.setWordWrap(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        row.addWidget(IconLabel("triangle-alert", "warning"), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._label, 1)

    def text(self) -> str:
        return self._label.text()

    def setText(self, text: str) -> None:
        self._label.setText(text)


class ErrorRow(QFrame):
    """Red inline message that always carries an icon, never colour alone."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "error-row")
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        row.addWidget(IconLabel("circle-alert", "error"), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._label, 1)
        self.hide()

    def text(self) -> str:
        return self._label.text()

    def setText(self, text: str) -> None:
        self._label.setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.setText("")
        self.setToolTip("")


class SegmentedControl(QFrame):
    """Pill-style single choice, with the QComboBox API the window code already uses.

    Every option is a focusable button; Left/Right (and Up/Down) move the selection.
    """

    currentIndexChanged = Signal(int)

    def __init__(self, accessible_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "segmented")
        self.setAccessibleName(accessible_name)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items: list[tuple[str, Any]] = []
        self._index = -1
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # QComboBox-like API ---------------------------------------------------------------
    def addItem(self, text: str, data: Any = None) -> None:
        index = len(self._items)
        self._items.append((text, data))
        button = QPushButton(text, self)
        button.setProperty("segment", True)
        button.setCheckable(True)
        button.setAccessibleName(f"{self.accessibleName()}: {text}")
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.toggled.connect(lambda checked, i=index: checked and self._on_checked(i))
        button.installEventFilter(self)
        self._group.addButton(button, index)
        self._layout.addWidget(button)
        if self._index < 0:
            self.setCurrentIndex(0)

    def clear(self) -> None:
        for button in self._group.buttons():
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.hide()  # deleteLater() only runs at the next event loop turn
            button.deleteLater()
        self._items.clear()
        self._index = -1

    def count(self) -> int:
        return len(self._items)

    def itemData(self, index: int) -> Any:
        return self._items[index][1] if 0 <= index < len(self._items) else None

    def itemText(self, index: int) -> str:
        return self._items[index][0] if 0 <= index < len(self._items) else ""

    def findData(self, data: Any) -> int:
        for i, (_, item) in enumerate(self._items):
            if item == data:
                return i
        return -1

    def currentIndex(self) -> int:
        return self._index

    def currentData(self) -> Any:
        return self.itemData(self._index)

    def currentText(self) -> str:
        return self.itemText(self._index)

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._items) or index == self._index:
            return
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)  # -> _on_checked

    def buttons(self) -> list[QAbstractButton]:
        return [self._group.button(i) for i in range(len(self._items))]

    # internals ----------------------------------------------------------------------
    def _on_checked(self, index: int) -> None:
        if index == self._index:
            return
        self._index = index
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(index)

    def eventFilter(self, obj, event) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            step = {
                Qt.Key.Key_Left: -1,
                Qt.Key.Key_Up: -1,
                Qt.Key.Key_Right: 1,
                Qt.Key.Key_Down: 1,
            }.get(event.key())
            if step and self._items:
                new = (self._index + step) % len(self._items)
                self.setCurrentIndex(new)
                self._group.button(new).setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(obj, event)


class Thumbnail(QFrame):
    """Rounded 16:9 thumbnail with an optional duration badge and an audio placeholder."""

    def __init__(self, width: int, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "thumb")
        self.setFixedSize(width, height)
        self._pixmap: QPixmap | None = None
        self._audio = False
        self._badge = label(role="badge")
        self._badge.setParent(self)
        self._badge.hide()
        theme_manager().changed.connect(lambda *_: self.update())

    def setPixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    def clear(self) -> None:
        self.setPixmap(None)
        self.set_duration(None)

    def set_audio(self, audio: bool) -> None:
        self._audio = audio
        self.update()

    def duration(self) -> str:
        return self._badge.text()

    def set_duration(self, text: str | None) -> None:
        self._badge.setText(text or "")
        self._badge.setVisible(bool(text))
        self._badge.adjustSize()
        self._place_badge()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_badge()

    def _place_badge(self) -> None:
        self._badge.move(
            self.width() - self._badge.width() - 6, self.height() - self._badge.height() - 6
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setClipPath(path)
        if self._pixmap is not None and not self._pixmap.isNull() and not self._audio:
            # cover-fit the image into the 16:9 frame
            scaled = self._pixmap.scaled(
                self.size() * self.devicePixelRatioF(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            sw = scaled.width() / scaled.devicePixelRatio()
            sh = scaled.height() / scaled.devicePixelRatio()
            painter.drawPixmap(
                QRectF((self.width() - sw) / 2, (self.height() - sh) / 2, sw, sh),
                scaled,
                QRectF(scaled.rect()),
            )
        else:
            palette = current_palette()
            size = max(16, min(self.width(), self.height()) // 2)
            name = "music" if self._audio else "download"
            pm = render(name, palette.muted, size, self.devicePixelRatioF() or 1.0)
            painter.drawPixmap(
                round((self.width() - size) / 2), round((self.height() - size) / 2), pm
            )
        painter.end()
