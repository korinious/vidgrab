"""Design tokens, generated Qt stylesheet, and light/dark/auto theme switching.

Everything visual comes from `Palette` tokens: the QSS below, the QPalette for Fusion,
and the colour of every icon (``ui/icons.py``). Changing the theme re-applies all three
live; widgets that draw icons listen to ``ThemeManager.changed``.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

log = logging.getLogger(__name__)


class ThemeMode(StrEnum):
    AUTO = "auto"  # follow Windows (QStyleHints.colorScheme)
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    chip_bg: str
    track: str  # progress track
    segment_bg: str  # segmented control background
    segment_selected: str
    secondary_btn: str
    hover: str
    link: str  # links and the keyboard focus ring on buttons
    field_focus: str  # border of a focused text field (neutral: red reads as an error)
    warning_fg: str
    warning_bg: str
    success_fg: str
    error_fg: str
    error_bg: str
    overlay_bg: str  # duration badge on thumbnails
    accent: str = "#DC2626"
    accent_hover: str = "#B91C1C"
    accent_pressed: str = "#991B1B"
    on_accent: str = "#FFFFFF"

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    @property
    def focus(self) -> str:
        return self.link


# Neutral greys only, no blue tint.
DARK = Palette(
    name="dark",
    bg="#0B0B0C",
    surface="#161618",
    surface2="#1F1F22",
    border="#2A2A2E",
    text="#F2F2F3",
    muted="#A1A1A8",
    chip_bg="#26262A",
    track="#2A2A2E",
    segment_bg="#1F1F22",
    segment_selected="#34343A",
    secondary_btn="#1F1F22",
    hover="#26262A",
    link="#F87171",
    field_focus="#52525B",
    warning_fg="#FCD34D",
    warning_bg="rgba(245, 158, 11, 0.14)",
    success_fg="#86EFAC",
    error_fg="#FCA5A5",
    error_bg="rgba(239, 68, 68, 0.12)",
    overlay_bg="rgba(0, 0, 0, 0.72)",
    accent_hover="#EF4444",
)

LIGHT = Palette(
    name="light",
    bg="#F5F5F5",
    surface="#FFFFFF",
    surface2="#F4F4F5",
    border="#E4E4E7",
    text="#111113",
    muted="#5E5E66",
    chip_bg="#F0F0F2",
    track="#E7E7EA",
    segment_bg="#F0F0F2",
    segment_selected="#FFFFFF",
    secondary_btn="#F4F4F5",
    hover="#EBEBED",
    link="#B91C1C",
    field_focus="#A1A1AA",
    warning_fg="#92400E",
    warning_bg="#FEF3C7",
    success_fg="#15803D",
    error_fg="#B91C1C",
    error_bg="#FEE2E2",
    overlay_bg="rgba(0, 0, 0, 0.72)",
)

PALETTES = {"dark": DARK, "light": LIGHT}

# Sizes (logical px; Qt scales them for 125 %/150 % DPI).
RADIUS_CARD = 12
RADIUS_FIELD = 12
RADIUS_BUTTON = 9
RADIUS_CHIP = 6
TOUCH_TARGET = 44
CONTENT_MAX_WIDTH = 1040
URL_FIELD_HEIGHT = 52

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter", "sans-serif"]
FONT_POINT_SIZE = 10


def app_font() -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(FONT_POINT_SIZE)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def tabular(font: QFont) -> QFont:
    """Same font with tabular (fixed-width) figures, so numbers don't jitter."""
    font = QFont(font)
    font.setFeature(QFont.Tag("tnum"), 1)
    return font


def build_qss(p: Palette) -> str:
    """The application stylesheet for a palette. Selectors use dynamic properties
    (``variant``, ``role``, ``tone``) set by the widgets in ``ui/widgets.py``."""
    selected_border = p.border if not p.is_dark else p.segment_selected
    return f"""
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog, QWidget#Root {{ background: {p.bg}; }}
QToolTip {{
    background: {p.surface2}; color: {p.text}; border: 1px solid {p.border};
    border-radius: {RADIUS_CHIP}px; padding: 4px 8px;
}}

/* --- text ---------------------------------------------------------------- */
QLabel[role="brand"] {{ font-size: 17px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="title"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="job-title"] {{ font-weight: 600; }}
QLabel[tone="muted"] {{ color: {p.muted}; }}
QLabel[tone="success"] {{ color: {p.success_fg}; }}
QLabel[tone="error"] {{ color: {p.error_fg}; }}
QLabel[tone="warning"] {{ color: {p.warning_fg}; }}
QLabel[role="chip"] {{
    background: {p.chip_bg}; color: {p.muted}; border-radius: {RADIUS_CHIP}px;
    padding: 2px 8px; font-size: 12px;
}}
QLabel[role="chip"][tone="warning"] {{ background: {p.warning_bg}; color: {p.warning_fg}; }}
QLabel[role="badge"] {{
    background: {p.overlay_bg}; color: #FFFFFF; border-radius: 4px;
    padding: 1px 5px; font-size: 11px; font-weight: 600;
}}

/* --- surfaces ------------------------------------------------------------ */
QFrame[card="true"] {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_CARD}px;
}}
QFrame[role="banner"] {{
    background: {p.warning_bg}; border-radius: {RADIUS_CARD}px;
}}
QFrame[role="banner"] QLabel {{ color: {p.warning_fg}; }}
QFrame[role="error-row"] {{ background: {p.error_bg}; border-radius: 8px; }}
QFrame[role="error-row"] QLabel {{ color: {p.error_fg}; }}
QFrame[role="thumb"] {{ background: {p.surface2}; border-radius: 8px; }}
QFrame[role="empty"] QLabel {{ color: {p.muted}; }}

/* --- inputs -------------------------------------------------------------- */
QFrame#UrlField {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_FIELD}px;
}}
QFrame#UrlField[focused="true"] {{ border: 2px solid {p.field_focus}; }}
QFrame#UrlField[invalid="true"] {{ border: 2px solid {p.error_fg}; }}
QLineEdit#UrlEdit {{
    background: transparent; border: none; font-size: 14px; padding: 0;
    selection-background-color: {p.accent}; selection-color: {p.on_accent};
}}
QLineEdit, QComboBox, QSpinBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px;
    padding: 6px 10px; min-height: 24px;
    selection-background-color: {p.accent}; selection-color: {p.on_accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {p.field_focus}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
    selection-background-color: {p.surface2}; selection-color: {p.text}; outline: none;
}}

/* --- buttons ------------------------------------------------------------- */
QPushButton {{
    background: {p.secondary_btn}; color: {p.text}; border: 1px solid {p.border};
    border-radius: {RADIUS_BUTTON}px; padding: 0 14px; min-height: 36px;
}}
QPushButton:hover {{ background: {p.hover}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:focus {{ border: 2px solid {p.focus}; }}
QPushButton:disabled {{ color: {p.muted}; }}
QPushButton[variant="primary"] {{
    background: {p.accent}; color: {p.on_accent}; border: none; font-weight: 600;
    border-radius: 10px; padding: 0 22px; min-height: {URL_FIELD_HEIGHT}px;
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {p.focus}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.track}; color: {p.muted}; }}
QPushButton[variant="warning"] {{
    background: {p.warning_bg}; color: {p.warning_fg}; border: 1px solid transparent;
    font-weight: 600;
}}
QPushButton[variant="warning"]:hover {{ border: 1px solid {p.warning_fg}; }}
QPushButton[variant="warning"]:focus {{ border: 2px solid {p.focus}; }}
QPushButton[variant="inline"] {{
    background: {p.chip_bg}; border: none; border-radius: 8px; min-height: 32px;
    padding: 0 12px; font-weight: 600;
}}
QPushButton[variant="inline"]:hover {{ background: {p.hover}; }}
QPushButton[variant="inline"]:focus {{ border: 2px solid {p.focus}; }}
QPushButton[variant="link"] {{
    background: transparent; border: none; color: {p.link}; padding: 0 4px;
    min-height: 28px; text-align: left;
}}
QPushButton[variant="link"]:hover {{ text-decoration: underline; }}
QPushButton[variant="link"]:focus {{ border: 2px solid {p.focus}; border-radius: 6px; }}
QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 10px;
    min-width: {TOUCH_TARGET}px; min-height: {TOUCH_TARGET}px;
}}
QToolButton:hover {{ background: {p.hover}; }}
QToolButton:pressed {{ background: {p.border}; }}
QToolButton:focus {{ border: 2px solid {p.focus}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* --- segmented control ------------------------------------------------------ */
QFrame[role="segmented"] {{ background: {p.segment_bg}; border-radius: 10px; }}
QPushButton[segment="true"] {{
    background: transparent; color: {p.muted}; border: 1px solid transparent;
    border-radius: 8px; min-height: 30px; padding: 0 12px;
}}
QPushButton[segment="true"]:hover {{ color: {p.text}; }}
QPushButton[segment="true"]:checked {{
    background: {p.segment_selected}; color: {p.text}; border: 1px solid {selected_border};
    font-weight: 600;
}}
QPushButton[segment="true"]:focus {{ border: 2px solid {p.focus}; }}

/* --- progress, lists, scroll bars, menus ------------------------------------------ */
QProgressBar {{
    background: {p.track}; border: none; border-radius: 2px;
    min-height: 4px; max-height: 4px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 2px; }}
QListWidget#Queue {{ background: transparent; border: none; outline: none; }}
QListWidget#Queue::item {{ background: transparent; border: none; padding: 0; margin: 0; }}
QListWidget#Queue::item:selected, QListWidget#Queue::item:hover {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 4px;
}}
QMenu::item {{ padding: 8px 16px 8px 28px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.surface2}; }}
QCheckBox:focus {{ color: {p.link}; }}
"""


def qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.bg,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface,
        QPalette.ColorRole.AlternateBase: p.surface2,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.PlaceholderText: p.muted,
        QPalette.ColorRole.Button: p.secondary_btn,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.on_accent,
        QPalette.ColorRole.ToolTipBase: p.surface2,
        QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.Link: p.link,
        QPalette.ColorRole.Mid: p.border,
        QPalette.ColorRole.Dark: p.border,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(p.muted))
    return pal


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def resolve(mode: ThemeMode) -> Palette:
    mode = ThemeMode(mode)
    if mode is ThemeMode.AUTO:
        return DARK if system_prefers_dark() else LIGHT
    return DARK if mode is ThemeMode.DARK else LIGHT


def set_dark_title_bar(widget: QWidget, dark: bool) -> bool:
    """Windows 10 20H1+/11: dark caption bar via DWMWA_USE_IMMERSIVE_DARK_MODE.

    Returns True if the call succeeded. No-op elsewhere.
    """
    if os.name != "nt" or not widget.isWindow():
        return False
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.WinDLL("dwmapi")
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE; 19 on Windows 10 builds before 20H1.
        for attribute in (20, 19):
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if hr == 0:
                return True
    except Exception:
        log.debug("DwmSetWindowAttribute failed", exc_info=True)
    return False


class ThemeManager(QObject):
    """Applies a theme to the whole application and tells widgets when it changes."""

    changed = Signal(object)  # Palette

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self.mode = ThemeMode.AUTO
        self.palette = resolve(ThemeMode.AUTO)
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setFont(app_font())
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        app.installEventFilter(self)  # dark title bar for every window that is shown
        self._applied = False

    def apply(self, mode: ThemeMode | str) -> Palette:
        self.mode = ThemeMode(mode)
        palette = resolve(self.mode)
        if self._applied and palette == self.palette and self._app.styleSheet():
            return palette
        self.palette = palette
        self._app.setPalette(qpalette(palette))
        self._app.setStyleSheet(build_qss(palette))
        self._applied = True
        for widget in self._app.topLevelWidgets():
            if widget.isWindow() and widget.isVisible():
                set_dark_title_bar(widget, palette.is_dark)
        log.info("Theme: %s (%s)", palette.name, self.mode)
        self.changed.emit(palette)
        return palette

    def _on_system_scheme(self, *_: object) -> None:
        if self.mode is ThemeMode.AUTO:
            self.apply(ThemeMode.AUTO)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(obj, QWidget)
            and obj.isWindow()
            and sys.platform == "win32"
        ):
            set_dark_title_bar(obj, self.palette.is_dark)
        return False


_MANAGER: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    """The application's ThemeManager (created on first use)."""
    global _MANAGER
    app = QApplication.instance()
    assert isinstance(app, QApplication), "create the QApplication first"
    if _MANAGER is None or _MANAGER.parent() is not app:
        _MANAGER = ThemeManager(app)
    return _MANAGER


def current_palette() -> Palette:
    return theme_manager().palette
