"""Offscreen UI tests for lists: selection screen, grouped queue, download history."""

from __future__ import annotations

import threading
import time

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from yt_dlp.utils import DownloadError  # noqa: E402

from conftest import (  # noqa: E402
    FakeScenario,
    PerUrlYdlFactory,
    instagram_carousel,
    yt_flat_entry,
    yt_playlist,
)
from vidgrab import strings  # noqa: E402
from vidgrab.core import archive  # noqa: E402
from vidgrab.core.models import JobStatus, Quality  # noqa: E402
from vidgrab.core.settings import Settings, load_settings  # noqa: E402

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLtest"
FORBIDDEN = DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    app.processEvents()
    assert condition(), "condition not met in time"


@pytest.fixture
def make_window(qapp, tmp_path, binaries):
    from vidgrab.ui.main_window import MainWindow

    windows = []

    def make(factory, **settings):
        win = MainWindow(
            Settings(output_dir=str(tmp_path / "out"), **settings),
            binaries,
            settings_path=tmp_path / "settings.json",
            ydl_factory=factory,
            load_thumbnails=False,
        )
        win.resize(1100, 900)
        win.show()
        win.activateWindow()  # keyboard focus and shortcuts need an active window
        QTest.qWaitForWindowActive(win, 2000)
        windows.append(win)
        return win

    yield make
    for win in windows:
        win.controller.shutdown()
        win.hide()
        win.deleteLater()
    qapp.processEvents()


@pytest.fixture
def window(make_window, fake_ydl):
    return make_window(fake_ydl)


def open_link(qapp, win, url=PLAYLIST_URL):
    win.url_edit.setText(url)
    win.fetch_metadata()
    wait_until(qapp, lambda: win.btn_fetch.isEnabled())
    qapp.processEvents()


def open_playlist(qapp, win, fake, n=10, extra=None):
    fake.scenario.info = yt_playlist(n, extra)
    open_link(qapp, win)
    assert win.selection_view.isVisible()
    return win.selection_view


# --- detection and the selection screen --------------------------------------------------


def test_list_link_opens_selection_screen(qapp, window, fake_ydl):
    view = open_playlist(
        qapp,
        window,
        fake_ydl,
        10,
        [yt_flat_entry(11, title="[Private video]"), yt_flat_entry(12, title="[Deleted video]")],
    )
    assert window.preview_card.isHidden()
    assert not window.btn_download.isEnabled()  # the list has its own primary button
    assert view.list_title.text() == "Λίστα δοκιμής"
    assert view.platform_chip.text() == "YouTube"
    assert view.count_chip.text() == "10 videos"
    assert view.duration_chip.text() == "10:55"  # 61 + ... + 70 seconds
    assert view.selected_label.text() == "10 από 10 επιλεγμένα"
    assert view.btn_download.text() == "Λήψη 10 videos"
    private, deleted = view.cards[10], view.cards[11]
    assert not private.isEnabled() and private.state_chip.text() == strings.CHIP_PRIVATE
    assert not deleted.isEnabled() and deleted.state_chip.text() == strings.CHIP_UNAVAILABLE
    assert 10 not in view.selected_indexes and 11 not in view.selected_indexes
    # private items never block the others
    view.toggle(10)
    assert 10 not in view.selected_indexes


def test_click_space_none_and_all(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 4)
    card = view.cards[0]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert 0 not in view.selected_indexes
    assert card.property("selected") is False and not card.check.isChecked()
    QTest.keyClick(card, Qt.Key.Key_Space)
    assert 0 in view.selected_indexes and card.property("selected") is True
    view.btn_none.click()
    assert view.selected_indexes == []
    assert view.selected_label.text() == "0 από 4 επιλεγμένα"
    assert not view.btn_download.isEnabled()
    view.btn_all.click()
    assert view.selected_indexes == [0, 1, 2, 3]
    assert view.btn_download.text() == "Λήψη 4 videos"
    view.toggle(1)
    view.toggle(2)
    view.toggle(3)
    assert view.btn_download.text() == "Λήψη 1 video"


def test_ctrl_a_selects_all(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 5)
    view.select_none()
    window.activateWindow()
    view.cards[2].setFocus()
    qapp.processEvents()
    QTest.keyClick(view.cards[2], Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert view.selected_indexes == [0, 1, 2, 3, 4]


def test_arrow_keys_move_through_the_grid(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 9)
    cols = view._columns
    assert cols in (2, 3)
    view.cards[0].setFocus()
    QTest.keyClick(view.cards[0], Qt.Key.Key_Right)
    assert view.cards[1].hasFocus()
    QTest.keyClick(view.cards[1], Qt.Key.Key_Down)
    assert view.cards[1 + cols].hasFocus()
    QTest.keyClick(view.cards[1 + cols], Qt.Key.Key_Left)
    assert view.cards[cols].hasFocus()


def test_arrows_skip_disabled_cards(qapp, window, fake_ydl):
    view = open_playlist(
        qapp, window, fake_ydl, 1, [yt_flat_entry(2, title="[Private video]"), yt_flat_entry(3)]
    )
    view.cards[0].setFocus()
    QTest.keyClick(view.cards[0], Qt.Key.Key_Right)
    assert view.cards[2].hasFocus()


def test_columns_follow_window_width(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 6)
    window.resize(1100, 900)
    qapp.processEvents()
    assert view._columns == 3
    window.resize(680, 900)
    qapp.processEvents()
    assert view._columns == 2


def test_rename_inline_is_windows_safe(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 3)
    card = view.cards[1]
    card.setFocus()
    QTest.keyClick(card, Qt.Key.Key_F2)
    assert card.editing
    card.editor.setText("Νέος: τίτλος? <final>")
    QTest.keyClick(card.editor, Qt.Key.Key_Return)
    assert not card.editing
    assert card.title.text() == "Νέος - τίτλος final"
    names = {item.entry.position: item.filename for item in view.selected_items()}
    assert names[2] == "02 - Νέος - τίτλος final"

    card.start_rename()
    card.editor.setText("ignored")
    QTest.keyClick(card.editor, Qt.Key.Key_Escape)
    assert card.title.text() == "Νέος - τίτλος final"
    assert view.isVisible()  # Esc in the editor does not leave the screen


def test_escape_goes_back(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 3)
    window.activateWindow()
    view.cards[0].setFocus()
    QTest.keyClick(view.cards[0], Qt.Key.Key_Escape)
    qapp.processEvents()
    assert view.isHidden() and window.preview_card.isVisible()


def test_many_selected_shows_amber_warning(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 30)
    assert view.warning.isVisible()
    assert view.warning.text().startswith("30 λήψεις μπορεί να προκαλέσουν προσωρινό")
    assert "από το YouTube" in view.warning.text()
    view.toggle(0)
    view.toggle(1)
    view.toggle(2)
    view.toggle(3)
    view.toggle(4)
    view.toggle(5)
    assert len(view.selected_indexes) == 24
    assert not view.warning.isVisible()


def test_long_list_builds_cards_in_batches(qapp, window, fake_ydl):
    from vidgrab.ui.selection import BATCH_SIZE

    view = open_playlist(qapp, window, fake_ydl, 150)
    assert len(view.cards) == BATCH_SIZE
    assert len(view.selected_indexes) == 150  # selection covers cards not built yet
    assert view.btn_download.text() == "Λήψη 150 videos"
    bar = view.scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    qapp.processEvents()
    assert len(view.cards) == 2 * BATCH_SIZE
    assert view.ensure_card(149) is view.cards[149]


def test_short_list_builds_all_cards(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 100)
    assert len(view.cards) == 100


def test_list_with_single_video_skips_selection(qapp, window, fake_ydl):
    post = instagram_carousel()
    post["entries"] = post["entries"][:2]  # one video and a photo
    fake_ydl.scenario.info = post
    fake_ydl.scenario.final_name = "v.mp4"
    open_link(qapp, window, "https://www.instagram.com/p/CARO1/")
    assert window.selection_view.isHidden()
    assert window.preview_title.text() == "Video by user 1"
    job = window.enqueue_current()
    assert job.request.playlist_item == 1
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert fake_ydl.last_params["playlist_items"] == "1"


def test_carousel_opens_selection(qapp, window, fake_ydl):
    fake_ydl.scenario.info = instagram_carousel()
    open_link(qapp, window, "https://www.instagram.com/p/CARO1/")
    view = window.selection_view
    assert view.isVisible()
    assert [c.entry.playlist_item for c in view.cards] == [1, 3]
    assert view.platform_chip.text() == "Instagram"


def test_video_inside_list_offers_scope(qapp, window, fake_ydl):
    fake_ydl.scenario.single_info = dict(fake_ydl.scenario.info)
    fake_ydl.scenario.info = yt_playlist(4)
    open_link(qapp, window, "https://www.youtube.com/watch?v=abc123&list=PLtest")
    assert window.preview_card.isVisible()
    assert window.preview_title.text() == "Test video"
    assert not window.scope_combo.isHidden()
    assert window.scope_combo.currentText() == strings.SCOPE_THIS_VIDEO
    assert window.btn_download.isEnabled()

    window.scope_combo.setCurrentIndex(1)  # "Όλη η λίστα"
    wait_until(qapp, lambda: window.selection_view.isVisible())
    assert len(window.selection_view.cards) == 4

    window.selection_view.btn_back.click()
    assert window.preview_card.isVisible()
    assert window.scope_combo.currentIndex() == 0
    assert window.btn_download.isEnabled()
    job = window.enqueue_current()
    assert job.request.url == "https://www.youtube.com/watch?v=abc123"


def test_plain_video_has_no_scope_choice(qapp, window, fake_ydl):
    open_link(qapp, window, "https://youtu.be/abc123")
    assert window.scope_combo.isHidden()


# --- downloading a list -------------------------------------------------------------------


def test_download_selected_as_a_group(qapp, window, fake_ydl, tmp_path):
    fake_ydl.scenario.name_from_outtmpl = True
    view = open_playlist(qapp, window, fake_ydl, 5)
    view.select_none()
    for i in (0, 2, 4):
        view.toggle(i)
    view.rename(2, "Δικό μου όνομα")
    view.btn_download.click()
    assert view.isHidden() and window.preview_card.isVisible()
    (group,) = window.controller.queue.groups
    jobs = window.controller.queue.group_jobs(group.id)
    assert [j.request.filename for j in jobs] == [
        "01 - Βίντεο 1",
        "03 - Δικό μου όνομα",
        "05 - Βίντεο 5",
    ]
    folder = tmp_path / "out" / "Λίστα δοκιμής"
    assert {j.request.output_dir for j in jobs} == {folder}
    assert jobs[0].request.url == "https://www.youtube.com/watch?v=vid001"
    wait_until(qapp, lambda: all(j.status is JobStatus.COMPLETED for j in jobs))
    assert sorted(p.name for p in folder.iterdir()) == [
        "01 - Βίντεο 1.mp4",
        "03 - Δικό μου όνομα.mp4",
        "05 - Βίντεο 5.mp4",
    ]
    header = window.group_header(group.id)
    assert header.count.text() == "3/3"
    assert header.progress.value() == 1000
    assert header.btn_cancel_all.isHidden()
    # history now has them
    assert {"youtube vid001", "youtube vid003", "youtube vid005"} <= archive.load_keys()


def test_subfolder_and_numbering_can_be_turned_off(qapp, window, fake_ydl, tmp_path):
    view = open_playlist(qapp, window, fake_ydl, 2)
    view.chk_subfolder.click()
    view.chk_numbering.click()
    saved = load_settings(tmp_path / "settings.json")
    assert (saved.list_subfolder, saved.list_numbering) == (False, False)
    view.btn_download.click()
    jobs = window.controller.queue.jobs
    assert [j.request.filename for j in jobs] == ["Βίντεο 1", "Βίντεο 2"]
    assert {j.request.output_dir for j in jobs} == {tmp_path / "out"}


def test_format_choice_in_selection_applies_to_list_and_preview(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 2)
    view.options.quality_combo.setCurrentIndex(view.options.quality_combo.findData(Quality.P720))
    assert window.settings.quality is Quality.P720
    assert Quality(window.quality_combo.currentData()) is Quality.P720  # preview in sync
    view.btn_download.click()
    assert {j.request.quality for j in window.controller.queue.jobs} == {Quality.P720}


# --- download history ---------------------------------------------------------------------


def test_downloaded_items_start_unselected_but_can_be_chosen(qapp, window, fake_ydl):
    archive.record("youtube vid002")
    fake_ydl.scenario.final_name = None
    fake_ydl.scenario.name_from_outtmpl = True
    view = open_playlist(qapp, window, fake_ydl, 3)
    card = view.cards[1]
    assert not card.downloaded_chip.isHidden()
    assert card.downloaded_chip.text() == strings.CHIP_ALREADY_DOWNLOADED
    assert view.selected_indexes == [0, 2]
    assert view.skipped_count() == 1
    view.toggle(1)  # chosen by hand: downloads normally
    assert view.skipped_count() == 0
    view.btn_download.click()
    jobs = window.controller.queue.jobs
    assert len(jobs) == 3
    wait_until(qapp, lambda: all(j.status is JobStatus.COMPLETED for j in jobs))


def test_skipped_count_on_group_header(qapp, window, fake_ydl):
    archive.record("youtube vid001")
    view = open_playlist(qapp, window, fake_ydl, 3)
    view.btn_download.click()
    (group,) = window.controller.queue.groups
    assert group.skipped == 1
    header = window.group_header(group.id)
    assert not header.skipped.isHidden()
    assert header.skipped.text() == "1 υπάρχουν ήδη"


def test_skip_option_off_selects_downloaded_items(qapp, window, fake_ydl, tmp_path):
    archive.record("youtube vid002")
    view = open_playlist(qapp, window, fake_ydl, 3)
    view.chk_skip.click()
    assert view.selected_indexes == [0, 1, 2]
    assert load_settings(tmp_path / "settings.json").skip_downloaded is False
    view.chk_skip.click()
    assert view.selected_indexes == [0, 2]


def test_single_url_downloads_even_if_in_history(qapp, window, fake_ydl):
    archive.record("youtube abc123")
    fake_ydl.scenario.final_name = "v.mp4"
    open_link(qapp, window, "https://youtu.be/abc123")
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert job.output_path.is_file()


def test_retry_downloads_even_if_in_history(qapp, make_window):
    factory = PerUrlYdlFactory()
    factory.scenario.final_name = "v.mp4"
    win = make_window(factory)
    open_link(qapp, win, "https://youtu.be/abc123")
    factory.scenario.attempt_errors = [FORBIDDEN, FORBIDDEN, FORBIDDEN]
    job = win.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.FAILED)
    archive.record("youtube abc123")  # e.g. downloaded meanwhile from a list
    win.controller.retry(job.id)
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)


def test_settings_dialog_clears_history_after_confirmation(qapp, download_archive):
    from vidgrab.ui.dialogs import SettingsDialog

    for key in ("youtube a", "youtube b", "instagram c"):
        archive.record(key)
    dialog = SettingsDialog(Settings())
    assert dialog.history_count.text() == "3 εγγραφές"
    assert dialog.btn_clear_history.isEnabled()
    asked = []
    dialog._confirm_clear_history = lambda n: asked.append(n) or False
    dialog.btn_clear_history.click()
    assert asked == [3] and archive.count() == 3
    dialog._confirm_clear_history = lambda n: True
    dialog.btn_clear_history.click()
    assert archive.count() == 0 and not download_archive.exists()
    assert dialog.history_count.text() == "0 εγγραφές"
    assert not dialog.btn_clear_history.isEnabled()
    dialog.deleteLater()


def test_history_text_for_one_entry():
    from vidgrab.ui.dialogs import history_count_text

    assert history_count_text(1) == "1 εγγραφή"


# --- grouped queue ------------------------------------------------------------------------


def test_group_over_five_starts_collapsed(qapp, window, fake_ydl):
    gate = threading.Event()
    fake_ydl.scenario.progress_events = [{"status": "downloading", "create": "x.part"}]
    fake_ydl.scenario.between_events = lambda i: gate.wait(5)
    view = open_playlist(qapp, window, fake_ydl, 6)
    view.btn_download.click()
    (group,) = window.controller.queue.groups
    header = window.group_header(group.id)
    assert not header.expanded
    children = [window._job_items[j.id][0] for j in window.controller.queue.group_jobs(group.id)]
    assert len(children) == 6 and all(item.isHidden() for item in children)
    header.btn_toggle.click()
    assert header.expanded and not any(item.isHidden() for item in children)
    assert header.btn_toggle.accessibleName() == strings.BTN_COLLAPSE
    # rows sit right under the header, indented
    header_row = window.queue_list.row(window._group_items[group.id][0])
    assert [window.queue_list.row(i) for i in children] == list(
        range(header_row + 1, header_row + 7)
    )
    gate.set()


def test_group_of_five_starts_expanded(qapp, window, fake_ydl):
    view = open_playlist(qapp, window, fake_ydl, 5)
    view.btn_download.click()
    (group,) = window.controller.queue.groups
    assert window.group_header(group.id).expanded


def test_cancel_all_and_retry_failed(qapp, make_window):
    factory = PerUrlYdlFactory()
    factory.scenario.info = yt_playlist(3)
    gate = threading.Event()
    hold = FakeScenario(
        info={"id": "vid002", "title": "Βίντεο 2", "extractor_key": "Youtube"},
        progress_events=[
            {"status": "downloading", "create": "v.part", "downloaded_bytes": 1, "total_bytes": 9}
        ]
        * 2,
        between_events=lambda i: gate.wait(5) if i == 1 else None,
    )
    failing = FakeScenario(
        info={"id": "vid001", "title": "Βίντεο 1", "extractor_key": "Youtube"},
        attempt_errors=[FORBIDDEN, FORBIDDEN, FORBIDDEN],
        final_name="one.mp4",
    )
    factory.scenarios = {
        "https://www.youtube.com/watch?v=vid001": failing,
        "https://www.youtube.com/watch?v=vid002": hold,
    }
    win = make_window(factory, max_concurrent=1)
    open_link(qapp, win)
    win.selection_view.btn_download.click()
    (group,) = win.controller.queue.groups
    one, two, three = win.controller.queue.group_jobs(group.id)
    header = win.group_header(group.id)
    wait_until(qapp, lambda: one.status is JobStatus.FAILED and two.progress is not None)
    assert three.status is JobStatus.QUEUED
    assert not header.failed.isHidden() and header.failed.text() == "1 απέτυχαν"
    assert not header.btn_retry_failed.isHidden()

    header.btn_cancel_all.click()
    gate.set()
    wait_until(qapp, lambda: two.status is JobStatus.CANCELLED)
    assert three.status is JobStatus.CANCELLED
    assert one.status is JobStatus.FAILED  # failures stay for "Επανάληψη αποτυχημένων"
    assert header.btn_cancel_all.isHidden()

    header.btn_retry_failed.click()
    wait_until(qapp, lambda: one.status is JobStatus.COMPLETED)
    assert header.btn_retry_failed.isHidden()
    assert header.count.text() == "1/3"


def test_clearing_finished_removes_empty_group(qapp, window, fake_ydl):
    fake_ydl.scenario.final_name = "v.mp4"
    view = open_playlist(qapp, window, fake_ydl, 2)
    view.btn_download.click()
    (group,) = window.controller.queue.groups
    jobs = window.controller.queue.group_jobs(group.id)
    wait_until(qapp, lambda: all(j.status is JobStatus.COMPLETED for j in jobs))
    window.btn_clear.click()
    assert window.controller.queue.groups == []
    assert group.id not in window._group_items
    assert window.queue_list.count() == 0
    assert window.queue_stack.currentWidget() is window.empty_state


def test_group_jobs_keep_single_job_features(qapp, make_window):
    """Downgrade chip and 403 errors work inside a group as for single jobs."""
    factory = PerUrlYdlFactory()
    factory.scenario.info = yt_playlist(1, [yt_flat_entry(2)])
    audio = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}
    uhd = {"format_id": "401", "height": 2160, "vcodec": "av01", "ext": "mp4"}
    fhd = {"format_id": "137", "height": 1080, "vcodec": "avc1", "ext": "mp4"}
    factory.scenarios = {
        "https://www.youtube.com/watch?v=vid001": FakeScenario(
            info={
                "id": "vid001",
                "title": "a",
                "extractor_key": "Youtube",
                "formats": [uhd, fhd, audio],
                "requested_formats": [fhd, audio],
            },
            final_name="a.mp4",
        ),
        "https://www.youtube.com/watch?v=vid002": FakeScenario(
            attempt_errors=[FORBIDDEN, FORBIDDEN, FORBIDDEN]
        ),
    }
    win = make_window(factory)
    open_link(qapp, win)
    win.selection_view.btn_download.click()
    a, b = win.controller.queue.jobs
    wait_until(qapp, lambda: a.status.is_finished and b.status.is_finished)
    card_a = win._job_items[a.id][1]
    assert not card_a.resolution_chip.isHidden()
    assert card_a.resolution_chip.text() == "1080p αντί 2160p"
    assert not card_a.btn_upgrade.isHidden()
    assert b.error.kind.value == "forbidden"
    assert not win._job_items[b.id][1].btn_retry.isHidden()


# --- accessibility and themes -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_selection_screen_in_both_themes(qapp, window, fake_ydl, mode):
    from vidgrab.ui.theme import DARK, LIGHT, ThemeMode, build_qss

    window.set_theme(ThemeMode(mode))
    palette = DARK if mode == "dark" else LIGHT
    qss = build_qss(palette)
    assert f'QFrame[role="entry"][selected="true"] {{ border: 2px solid {palette.accent}; }}' in qss
    view = open_playlist(qapp, window, fake_ydl, 3, [yt_flat_entry(4, title="[Private video]")])
    for card in view.cards[:3]:
        assert card.accessibleName().startswith(f"{card.entry.position}. ")
        assert card.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert card.btn_rename.toolTip() and card.btn_rename.width() >= 44
    assert not view.cards[3].focusPolicy() & Qt.FocusPolicy.TabFocus
    for button in (view.btn_back, view.btn_all, view.btn_none, view.btn_download):
        assert button.accessibleName() or button.text()
    window.set_theme(ThemeMode.AUTO)


def test_no_stray_top_level_windows(qapp, window, fake_ydl):
    """Chips shown before they had a parent once opened as tiny separate windows."""
    archive.record("youtube vid001")
    view = open_playlist(qapp, window, fake_ydl, 3, [yt_flat_entry(4, title="[Private video]")])
    view.toggle(0)
    view.btn_download.click()
    qapp.processEvents()
    visible = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    assert visible == [window]
    assert window.isActiveWindow()
