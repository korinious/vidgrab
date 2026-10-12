"""Update banner, "Τι νέο" dialog, old-engine banner and the settings (offscreen Qt).

All HTTP goes to the ``fake_http`` fixture; nothing reaches GitHub.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from PySide6.QtGui import QFont, QTextCharFormat  # noqa: E402

from vidgrab import strings  # noqa: E402
from vidgrab.core.errors import ErrorKind  # noqa: E402
from vidgrab.core.settings import Settings, load_settings  # noqa: E402
from vidgrab.core.updates import (  # noqa: E402
    LATEST_RELEASE_API,
    CheckResult,
    CheckStatus,
    format_check_time,
)
from vidgrab.ui.theme import ThemeMode, theme_manager  # noqa: E402
from vidgrab.ui.update_banner import BannerState  # noqa: E402

BASE = "https://github.com/korinious/vidgrab/releases/download"
ZIP = b"PK\x03\x04 fake zip " * 4000
NOTES = """VidGrab 9.0.1

## Τι νέο υπάρχει

- **Ενημερώσεις:** έλεγχος μέσα από την εφαρμογή.
- Δεύτερο σημείο με [σύνδεσμο](https://example.com/x).

![εικόνα](https://example.com/tracker.png)
"""
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def restore_theme(qapp):
    yield
    theme_manager().apply(ThemeMode.AUTO)


def wait_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    app.processEvents()
    assert condition(), "condition not met in time"


def iter_blocks(doc):
    block = doc.begin()
    while block.isValid():
        yield block
        block = block.next()


def heading_point_size(block):
    it = block.begin()
    fragment = it.fragment()
    return fragment.charFormat().font().pointSizeF()


def serve(fake_http, version="9.0.1", sums=True, zip_body=ZIP):
    tag = f"v{version}"
    name = f"VidGrab-{version}-win64.zip"
    assets = [{"name": name, "browser_download_url": f"{BASE}/{tag}/{name}", "size": len(ZIP)}]
    if sums:
        assets.append(
            {"name": "SHA256SUMS.txt", "browser_download_url": f"{BASE}/{tag}/SHA256SUMS.txt"}
        )
        digest = hashlib.sha256(ZIP).hexdigest()
        fake_http.routes[f"{BASE}/{tag}/SHA256SUMS.txt"] = f"{digest}  {name}\n".encode()
    fake_http.routes[f"{BASE}/{tag}/{name}"] = zip_body
    fake_http.routes[LATEST_RELEASE_API] = json.dumps(
        {
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "html_url": f"https://github.com/korinious/vidgrab/releases/tag/{tag}",
            "body": NOTES,
            "assets": assets,
        }
    ).encode()


@pytest.fixture
def make_window(qapp, tmp_path, fake_ydl, binaries):
    from vidgrab.ui.main_window import MainWindow

    made = []

    def make(**settings):
        win = MainWindow(
            Settings(output_dir=str(tmp_path / "out"), **settings),
            binaries,
            settings_path=tmp_path / "settings.json",
            ydl_factory=fake_ydl,
            load_thumbnails=False,
        )
        win.update_download_dir = tmp_path / "Downloads"
        win.show()
        qapp.processEvents()
        made.append(win)
        return win

    yield make
    for win in made:
        win.controller.shutdown()
        win.close()
        win.deleteLater()
    qapp.processEvents()


def checked(qapp, win, now=NOW):
    assert win.auto_check_for_updates(now)
    wait_until(qapp, lambda: win._update_check_worker is None)
    return win


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_banner_shows_a_new_version(qapp, make_window, fake_http, tmp_path, mode):
    theme_manager().apply(mode)
    serve(fake_http)
    win = checked(qapp, make_window())
    banner = win.update_banner
    assert banner.isVisible() and banner.state is BannerState.AVAILABLE
    assert banner.title.text() == "Διαθέσιμη η VidGrab 9.0.1"
    for button in (banner.btn_download, banner.btn_notes, banner.btn_skip, banner.btn_close):
        assert button.isVisible()
    assert [b.text() for b in (banner.btn_download, banner.btn_notes, banner.btn_skip)] == [
        "Λήψη",
        "Τι νέο",
        "Παράλειψη αυτής της έκδοσης",
    ]
    assert banner.btn_close.accessibleName() and banner.btn_close.toolTip()
    assert not banner.progress.isVisible()
    # it sits right under the header, above the URL field
    banner_y = banner.mapTo(win, banner.rect().topLeft()).y()
    assert banner_y < win.url_field.mapTo(win, win.url_field.rect().topLeft()).y()
    # the time of the check is saved, so the next start does not check again
    saved = load_settings(tmp_path / "settings.json")
    assert saved.last_update_check == format_check_time(NOW)


def test_check_at_most_once_per_day_and_never_when_off(qapp, make_window, fake_http):
    serve(fake_http)
    recent = format_check_time(NOW - timedelta(hours=3))
    win = make_window(last_update_check=recent)
    assert not win.auto_check_for_updates(NOW)
    off = make_window(auto_update_check=False)
    assert not off.auto_check_for_updates(NOW)
    assert fake_http.requests == []
    assert not win.update_banner.isVisible() and not off.update_banner.isVisible()


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), b"{not json"])
def test_failed_check_is_silent(qapp, make_window, fake_http, failure):
    fake_http.routes[LATEST_RELEASE_API] = failure
    win = checked(qapp, make_window())
    assert not win.update_banner.isVisible()
    assert [w for w in qapp.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox)] == []


def test_skip_this_version(qapp, make_window, fake_http, tmp_path):
    serve(fake_http)
    win = checked(qapp, make_window())
    win.update_banner.btn_skip.click()
    assert not win.update_banner.isVisible()
    assert load_settings(tmp_path / "settings.json").skipped_update_version == "9.0.1"
    # a day later, the same version stays hidden ...
    checked(qapp, win, NOW + timedelta(days=1))
    assert not win.update_banner.isVisible()
    # ... but the next one shows again
    serve(fake_http, "9.0.2")
    checked(qapp, win, NOW + timedelta(days=2))
    assert win.update_banner.isVisible()
    assert win.update_banner.title.text() == "Διαθέσιμη η VidGrab 9.0.2"


def test_close_hides_until_next_start(qapp, make_window, fake_http, tmp_path):
    serve(fake_http)
    win = checked(qapp, make_window())
    win.update_banner.btn_close.click()
    assert not win.update_banner.isVisible()
    assert load_settings(tmp_path / "settings.json").skipped_update_version is None


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_whats_new_renders_markdown(qapp, make_window, fake_http, mode):
    theme_manager().apply(mode)
    serve(fake_http)
    win = checked(qapp, make_window())
    requests_before = len(fake_http.requests)
    win.update_banner.btn_notes.click()
    dialog = win.notes_dialog
    wait_until(qapp, dialog.isVisible)
    doc = dialog.browser.document()
    text = doc.toPlainText()
    assert "Τι νέο υπάρχει" in text and "**" not in text and "## " not in text
    # list items are a real list, "Ενημερώσεις:" is bold
    block = doc.begin()
    lists, bold = 0, False
    while block.isValid():
        if block.textList() is not None:
            lists += 1
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            fmt: QTextCharFormat = fragment.charFormat()
            if "Ενημερώσεις" in fragment.text() and fmt.fontWeight() >= QFont.Weight.Bold:
                bold = True
            it += 1
        block = block.next()
    assert lists == 2 and bold
    # headings follow the app's type scale, not Qt's (much larger) defaults
    base = dialog.browser.font().pointSizeF()
    heading = next(b for b in iter_blocks(doc) if b.blockFormat().headingLevel() == 2)
    sizes = {heading_point_size(heading)}
    assert max(sizes) <= base * 1.35 + 0.1
    assert dialog.windowTitle() == "Τι νέο στη VidGrab 9.0.1"
    # the dialog follows the theme: text and background from the tokens
    palette = theme_manager().palette
    assert (
        dialog.browser.palette().color(dialog.browser.foregroundRole()).name().upper()
        == palette.text.upper()
    )
    # the image in the notes is never fetched
    assert len(fake_http.requests) == requests_before
    dialog.btn_close.click()
    wait_until(qapp, lambda: not dialog.isVisible())


def test_whats_new_without_notes(qapp, make_window, fake_http):
    serve(fake_http)
    raw = json.loads(fake_http.routes[LATEST_RELEASE_API])
    raw["body"] = ""
    fake_http.routes[LATEST_RELEASE_API] = json.dumps(raw).encode()
    win = checked(qapp, make_window())
    dialog = win.show_release_notes()
    assert dialog.browser.toPlainText() == strings.NOTES_EMPTY
    dialog.close()


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_download_progress_and_done(qapp, make_window, fake_http, tmp_path, mode):
    theme_manager().apply(mode)
    gate = threading.Event()
    serve(fake_http)
    zip_url = f"{BASE}/v9.0.1/VidGrab-9.0.1-win64.zip"
    fake_http.routes[zip_url] = lambda: (gate.wait(5), ZIP)[1]
    win = checked(qapp, make_window())
    banner = win.update_banner
    banner.btn_download.click()
    wait_until(qapp, lambda: banner.state is BannerState.DOWNLOADING)
    assert banner.progress.isVisible() and banner.btn_cancel.isVisible()
    assert not banner.btn_download.isVisible() and not banner.btn_close.isVisible()
    assert banner.title.text() == "Λήψη της VidGrab 9.0.1…"
    banner.set_progress(len(ZIP) // 2, len(ZIP))
    assert banner.progress.value() == 500
    assert " από " in banner.hint.text()
    gate.set()
    wait_until(qapp, lambda: banner.state is BannerState.DONE)
    path = tmp_path / "Downloads" / "VidGrab-9.0.1-win64.zip"
    assert path.read_bytes() == ZIP and banner.downloaded == path
    assert banner.title.text() == "Η νέα έκδοση κατέβηκε"
    assert "αποσυμπίεσε" in banner.hint.text() and path.name in banner.hint.text()
    assert banner.btn_open_folder.isVisible() and banner.btn_open_folder.text() == "Άνοιγμα φακέλου"
    assert not banner.progress.isVisible()


def test_cancel_download(qapp, make_window, fake_http, tmp_path):
    gate = threading.Event()
    serve(fake_http)
    fake_http.routes[f"{BASE}/v9.0.1/VidGrab-9.0.1-win64.zip"] = lambda: (gate.wait(5), ZIP)[1]
    win = checked(qapp, make_window())
    banner = win.update_banner
    banner.btn_download.click()
    wait_until(qapp, lambda: banner.state is BannerState.DOWNLOADING)
    banner.btn_cancel.click()
    gate.set()
    wait_until(qapp, lambda: banner.state is BannerState.AVAILABLE)
    wait_until(qapp, lambda: win._update_download_worker is None)
    assert not any((tmp_path / "Downloads").iterdir())


def test_bad_checksum_is_an_error_and_nothing_is_kept(qapp, make_window, fake_http, tmp_path):
    serve(fake_http, zip_body=ZIP + b"tampered")
    win = checked(qapp, make_window())
    banner = win.update_banner
    banner.btn_download.click()
    wait_until(qapp, lambda: banner.state is BannerState.FAILED)
    assert banner.error.isVisible()
    assert banner.error.text() == strings.ERR_UPDATE_CHECKSUM_MISMATCH
    assert banner.btn_retry.isVisible()
    assert not any((tmp_path / "Downloads").iterdir())


def test_missing_checksums_is_an_error(qapp, make_window, fake_http, tmp_path):
    serve(fake_http, sums=False)
    win = checked(qapp, make_window())
    win.update_banner.btn_download.click()
    wait_until(qapp, lambda: win.update_banner.state is BannerState.FAILED)
    assert win.update_banner.error.text() == strings.ERR_UPDATE_CHECKSUM_MISSING
    assert not (tmp_path / "Downloads").exists() or not any((tmp_path / "Downloads").iterdir())


# --- old download engine -------------------------------------------------------------------


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_stale_engine_banner(qapp, make_window, mode):
    theme_manager().apply(mode)
    win = make_window()
    assert not win.set_stale_engine("2026.08.19", date(2026, 10, 1))  # 43 days
    assert not win.stale_banner.isVisible()
    assert win.set_stale_engine("2026.08.19", date(2026, 10, 30))  # 72 days
    assert win.stale_banner.isVisible()
    assert win.stale_banner.text() == (
        "Η μηχανή λήψης είναι παλιά. Αν οι λήψεις αποτυγχάνουν, ενημέρωσε το VidGrab."
    )
    assert "72" in win.stale_banner.toolTip()
    win.stale_banner.btn_close.click()
    assert not win.stale_banner.isVisible()


def test_stale_engine_banner_gives_way_to_the_update_banner(qapp, make_window, fake_http):
    serve(fake_http)
    win = make_window()
    win.set_stale_engine("2026.01.01", date(2026, 10, 12))
    assert win.stale_banner.isVisible()
    checked(qapp, win)
    assert win.update_banner.isVisible() and not win.stale_banner.isVisible()
    win.update_banner.btn_close.click()
    assert win.stale_banner.isVisible()  # no update banner any more


# --- settings ------------------------------------------------------------------------------


def test_settings_toggle_check_now_and_versions(qapp, make_window, fake_http):
    from vidgrab.ui.dialogs import SettingsDialog

    win = make_window()
    win.set_versions({"yt-dlp": "2026.08.19", "ffmpeg": "8.0", "deno": "2.9.6"})
    dialog = SettingsDialog(win.settings, win, versions=win._versions)
    win._settings_dialog = dialog
    dialog.check_requested.connect(win.check_for_updates_now)
    assert dialog.auto_update_check.isChecked()
    assert dialog.auto_update_check.text() == "Αυτόματος έλεγχος για ενημερώσεις"
    assert dialog.versions_label.text().startswith("VidGrab ")
    assert "yt-dlp 2026.08.19 · FFmpeg 8.0 · Deno 2.9.6" in dialog.versions_label.text()

    fake_http.routes[LATEST_RELEASE_API] = TimeoutError("timed out")
    dialog.btn_check_now.click()
    wait_until(qapp, lambda: dialog.check_result.text() == strings.CHECK_FAILED)

    serve(fake_http, "0.0.1")
    dialog.btn_check_now.click()
    wait_until(qapp, lambda: dialog.check_result.text() == "Έχεις την τελευταία έκδοση")
    assert dialog.btn_check_now.isEnabled()

    serve(fake_http, "9.0.1")
    dialog.btn_check_now.click()
    wait_until(qapp, lambda: dialog.check_result.text() == "Διαθέσιμη η 9.0.1")
    assert win.update_banner.isVisible()

    dialog.auto_update_check.click()
    assert dialog.result_settings().auto_update_check is False
    win._settings_dialog = None
    dialog.close()


def test_manual_check_ignores_skip(qapp, make_window, fake_http):
    serve(fake_http)
    win = make_window(skipped_update_version="9.0.1")
    win.check_for_updates_now()
    wait_until(qapp, lambda: win._update_check_worker is None)
    assert win.update_banner.isVisible()


def test_dialog_result_keeps_update_bookkeeping(qapp, make_window):
    win = make_window()
    win.settings = Settings(
        output_dir=win.settings.output_dir,
        last_update_check=format_check_time(NOW),
        skipped_update_version="9.0.1",
    )
    win.apply_settings(Settings(output_dir=win.settings.output_dir, auto_update_check=False))
    assert win.settings.auto_update_check is False
    assert win.settings.last_update_check == format_check_time(NOW)
    assert win.settings.skipped_update_version == "9.0.1"


def test_check_result_texts(qapp):
    from vidgrab.ui.dialogs import SettingsDialog

    dialog = SettingsDialog(Settings())
    dialog.show_check_running()
    assert dialog.check_result.text() == "Έλεγχος…" and not dialog.btn_check_now.isEnabled()
    dialog.show_check_result(CheckResult(CheckStatus.UP_TO_DATE))
    assert dialog.check_result.property("tone") == "success"
    dialog.close()


def test_update_errors_have_messages():
    from vidgrab.core.errors import UserError

    assert (
        UserError(ErrorKind.UPDATE_CHECKSUM_MISSING).message == strings.ERR_UPDATE_CHECKSUM_MISSING
    )
