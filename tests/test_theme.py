"""Theme, icons and accessibility of the modern UI (offscreen Qt)."""

from __future__ import annotations

import json

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFocusEvent, QGuiApplication, QImageReader, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from vidgrab import strings  # noqa: E402
from vidgrab.core.settings import Settings  # noqa: E402
from vidgrab.ui import theme as theme_mod  # noqa: E402
from vidgrab.ui.icons import APP_ICON, available_icons, render  # noqa: E402
from vidgrab.ui.theme import DARK, LIGHT, ThemeMode, build_qss, theme_manager  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def restore_theme(qapp):
    yield
    theme_manager().apply(ThemeMode.AUTO)


@pytest.fixture
def window(qapp, tmp_path, fake_ydl, binaries):
    from vidgrab.ui.main_window import MainWindow

    win = MainWindow(
        Settings(output_dir=str(tmp_path / "out")),
        binaries,
        settings_path=tmp_path / "settings.json",
        ydl_factory=fake_ydl,
        load_thumbnails=False,
    )
    yield win
    win.controller.shutdown()
    win.close()
    win.deleteLater()
    qapp.processEvents()


# --- tokens and QSS -----------------------------------------------------------------------


def test_dark_and_light_tokens():
    assert (DARK.bg, DARK.surface, DARK.surface2, DARK.border) == (
        "#0B0B0C",
        "#161618",
        "#1F1F22",
        "#2A2A2E",
    )
    assert (DARK.text, DARK.muted, DARK.chip_bg, DARK.track) == (
        "#F2F2F3",
        "#A1A1A8",
        "#26262A",
        "#2A2A2E",
    )
    assert (LIGHT.bg, LIGHT.surface, LIGHT.border, LIGHT.text, LIGHT.muted) == (
        "#F5F5F5",
        "#FFFFFF",
        "#E4E4E7",
        "#111113",
        "#5E5E66",
    )
    assert DARK.accent == LIGHT.accent == "#DC2626"
    assert (DARK.link, LIGHT.link) == ("#F87171", "#B91C1C")
    assert DARK.is_dark and not LIGHT.is_dark


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_qss_is_built_from_tokens(palette):
    qss = build_qss(palette)
    for token in (palette.bg, palette.surface, palette.border, palette.accent, palette.focus):
        assert token in qss
    assert qss.count("{") == qss.count("}")
    other = LIGHT if palette is DARK else DARK
    assert other.bg not in qss  # no leftovers from the other theme


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_both_themes_load(qapp, mode):
    manager = theme_manager()
    manager.apply(ThemeMode.LIGHT if mode is ThemeMode.DARK else ThemeMode.DARK)
    seen = []
    manager.changed.connect(seen.append)
    try:
        palette = manager.apply(mode)
    finally:
        manager.changed.disconnect(seen.append)
    expected = DARK if mode is ThemeMode.DARK else LIGHT
    assert palette == expected
    assert qapp.styleSheet() == build_qss(expected)
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(expected.bg)
    assert seen == [expected]


def test_auto_follows_system_scheme(qapp, monkeypatch):
    monkeypatch.setattr(theme_mod, "system_prefers_dark", lambda: True)
    assert theme_manager().apply(ThemeMode.AUTO) is DARK
    monkeypatch.setattr(theme_mod, "system_prefers_dark", lambda: False)
    theme_manager()._on_system_scheme()  # what colorSchemeChanged triggers
    assert theme_manager().palette is LIGHT


def test_app_font_has_tabular_figures_helper(qapp):
    font = theme_mod.app_font()
    assert font.families()[0].startswith("Segoe UI Variable")
    assert "Segoe UI" in font.families()
    assert theme_mod.tabular(font).featureValue(theme_mod.QFont.Tag("tnum")) == 1


# --- icons ------------------------------------------------------------------------------


def test_icons_render_in_theme_colours(qapp):
    names = available_icons()
    assert len(names) >= 20
    for name in names:
        for colour in (DARK.text, LIGHT.text):
            pixmap = render(name, colour, 20, 1.5)
            assert not pixmap.isNull() and pixmap.width() == 30


def test_every_icon_used_in_code_exists():
    from vidgrab.ui.main_window import THEME_ICONS
    from vidgrab.ui.queue_widget import _STATUS_STYLE

    used = set(THEME_ICONS.values()) | {name for name, _ in _STATUS_STYLE.values()}
    used |= {"link", "search", "clipboard-paste", "settings", "download", "folder"}
    used |= {"folder-open", "external-link", "x", "rotate-ccw", "trash-2", "info", "music"}
    used |= {"refresh-cw", "inbox", "file-text", "circle-alert", "triangle-alert"}
    assert used <= set(available_icons())


def test_app_icon_has_all_sizes(qapp):
    reader = QImageReader(str(APP_ICON))
    sizes = set()
    for i in range(reader.imageCount()):
        reader.jumpToImage(i)
        sizes.add(reader.read().width())
    assert {16, 24, 32, 48, 256} <= sizes


# --- window -----------------------------------------------------------------------------


def test_icon_buttons_are_accessible_touch_targets(qapp, window):
    window.show()
    qapp.processEvents()
    buttons = window.findChildren(QtWidgets.QToolButton)
    assert len(buttons) >= 3
    for button in buttons:
        if not button.isVisibleTo(window):
            continue
        assert button.accessibleName(), button
        assert button.toolTip(), button
        size = button.size()
        assert size.width() >= 40 and size.height() >= 40, (button.toolTip(), size)
    for button in (window.btn_theme, window.btn_settings, window.btn_open_dest):
        assert button.width() >= 44 and button.height() >= 44
    for widget in window.findChildren(QtWidgets.QAbstractButton):
        if widget.isVisibleTo(window):
            assert widget.focusPolicy() & Qt.FocusPolicy.TabFocus, widget


def test_url_field_is_52px_with_inline_buttons(qapp, window):
    window.show()
    qapp.processEvents()
    assert window.url_field.height() == 52
    assert window.btn_paste.parent() is window.url_field
    assert window.btn_download.property("variant") == "primary"


def test_segmented_control_keyboard(qapp, window):
    from vidgrab.core.models import Quality

    window.show()
    qapp.processEvents()
    seen = []
    window.quality_combo.currentIndexChanged.connect(seen.append)
    first = window.quality_combo.buttons()[0]
    window.quality_combo.setCurrentIndex(0)
    first.setFocus()
    QTest.keyClick(first, Qt.Key.Key_Right)
    assert window.quality_combo.currentIndex() == 1
    assert Quality(window.quality_combo.currentData()) == window.settings.quality
    QTest.keyClick(window.quality_combo.buttons()[1], Qt.Key.Key_Left)
    assert window.quality_combo.currentIndex() == 0
    assert seen[-2:] == [1, 0]


def test_clipboard_suggestion(qapp, window):
    from vidgrab.ui.main_window import clipboard_url

    assert clipboard_url("https://youtu.be/abc") == "https://youtu.be/abc"
    assert clipboard_url("  http://example.com/v?id=1 ") == "http://example.com/v?id=1"
    for bad in ("", "hello", "ftp://x.com/a", "https://", "https://a b.com", "file:///C:/x"):
        assert clipboard_url(bad) is None, bad

    clipboard = QGuiApplication.clipboard()
    clipboard.setText("not a link")
    QtWidgets.QApplication.sendEvent(window.url_edit, QFocusEvent(QEvent.Type.FocusIn))
    assert window.clipboard_hint.isHidden()

    clipboard.setText("https://youtu.be/abc123")
    QtWidgets.QApplication.sendEvent(window.url_edit, QFocusEvent(QEvent.Type.FocusIn))
    assert not window.clipboard_hint.isHidden()
    assert "https://youtu.be/abc123" in window.clipboard_hint.text()
    assert window.url_field.property("focused") is True

    window.clipboard_hint.click()
    assert window.url_edit.text() == "https://youtu.be/abc123"
    assert window.clipboard_hint.isHidden()  # field is no longer empty


def test_empty_state_and_counter(qapp, window):
    from vidgrab.core.models import JobStatus

    assert window.queue_stack.currentWidget() is window.empty_state
    assert window.queue_counter.text() == ""
    window.url_edit.setText("https://youtu.be/abc123")
    window.fetch_metadata()
    _wait(qapp, lambda: window.btn_fetch.isEnabled())
    job = window.enqueue_current()
    assert window.queue_stack.currentWidget() is window.queue_list
    _wait(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert window.queue_counter.text() == strings.QUEUE_IDLE
    window.btn_clear.click()
    assert window.queue_stack.currentWidget() is window.empty_state


def test_theme_choice_is_saved_and_restored(qapp, window, tmp_path, fake_ydl, binaries):
    from vidgrab.ui.main_window import MainWindow

    window.set_theme(ThemeMode.DARK)
    assert theme_manager().palette is DARK
    assert json.loads((tmp_path / "ui.json").read_text(encoding="utf-8")) == {"theme": "dark"}

    theme_manager().apply(ThemeMode.LIGHT)
    reopened = MainWindow(
        Settings(output_dir=str(tmp_path / "out")),
        binaries,
        settings_path=tmp_path / "settings.json",
        ydl_factory=fake_ydl,
        load_thumbnails=False,
    )
    try:
        assert theme_manager().mode is ThemeMode.DARK
        assert reopened._theme_actions[ThemeMode.DARK].isChecked()
    finally:
        reopened.deleteLater()


def test_theme_switch_recolours_without_restart(qapp, window):
    window.set_theme(ThemeMode.LIGHT)
    light_icon = window.btn_settings.icon().pixmap(20, 20).toImage()
    window.set_theme(ThemeMode.DARK)
    dark_icon = window.btn_settings.icon().pixmap(20, 20).toImage()
    assert light_icon != dark_icon
    assert qapp.styleSheet() == build_qss(DARK)


def test_settings_dialog_theme(qapp):
    from vidgrab.ui.dialogs import SettingsDialog

    dialog = SettingsDialog(Settings(), theme=ThemeMode.LIGHT)
    assert dialog.result_theme() is ThemeMode.LIGHT
    dialog.theme_combo.setCurrentIndex(2)
    assert dialog.result_theme() is ThemeMode.DARK
    dialog.deleteLater()


def test_versions_footer(qapp, window):
    window.set_versions({"yt-dlp": "2026.09.30", "ffmpeg": "8.0", "deno": None})
    assert window.versions_label.text() == "yt-dlp 2026.09.30 · FFmpeg 8.0 · Deno —"


def _wait(app, condition, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    assert condition()
