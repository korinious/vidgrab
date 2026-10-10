"""Window size and position per screen, and the layout on small screens (offscreen Qt)."""

from __future__ import annotations

import json
import time

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from PySide6.QtCore import QRect  # noqa: E402

from conftest import yt_playlist  # noqa: E402
from vidgrab.core.models import JobStatus, Quality  # noqa: E402
from vidgrab.core.settings import Settings  # noqa: E402
from vidgrab.ui.prefs import UiPrefs, load_prefs, save_prefs  # noqa: E402
from vidgrab.ui.window_geometry import (  # noqa: E402
    SavedGeometry,
    default_rect,
    initial_geometry,
    minimum_size,
    restored_rect,
)

# Available areas (screen minus taskbar), in logical pixels.
LAPTOP_1366 = QRect(0, 0, 1366, 728)  # 1366x768 at 100 %, 40 px taskbar
FULLHD_150 = QRect(0, 0, 1280, 688)  # 1920x1080 at 150 %: 1280x720 logical, 32 px taskbar
BIG_1440 = QRect(0, 0, 2560, 1400)
SECOND_SCREEN = QRect(1366, 0, 1920, 1040)


# --- pure geometry ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "size"),
    [(LAPTOP_1366, (1100, 688)), (FULLHD_150, (1100, 648)), (BIG_1440, (1100, 900))],
)
def test_default_size_is_min_900_and_screen_minus_40_centred(available, size):
    rect = default_rect(available)
    assert (rect.width(), rect.height()) == size
    assert (
        rect.center() == available.center() or abs(rect.center().y() - available.center().y()) <= 1
    )
    assert available.contains(rect)


def test_default_on_a_second_screen_is_centred_there():
    rect = default_rect(SECOND_SCREEN)
    assert SECOND_SCREEN.contains(rect)
    assert rect.height() == 900


def test_minimum_size_never_exceeds_the_screen():
    assert minimum_size(LAPTOP_1366) == (640, 520)
    tiny = QRect(0, 0, 800, 520)
    assert minimum_size(tiny) == (640, 480)


def test_saved_geometry_is_restored_when_on_a_screen():
    saved = SavedGeometry(200, 80, 1000, 600)
    rect, maximized = initial_geometry(saved, [LAPTOP_1366], LAPTOP_1366)
    assert rect == QRect(200, 80, 1000, 600) and not maximized


def test_saved_geometry_on_an_unplugged_screen_falls_back_to_default():
    saved = SavedGeometry(2000, 100, 1100, 800, maximized=True)  # was on SECOND_SCREEN
    assert restored_rect(saved, [LAPTOP_1366]) is None
    rect, maximized = initial_geometry(saved, [LAPTOP_1366], LAPTOP_1366)
    assert rect == default_rect(LAPTOP_1366) and not maximized
    # with the second screen back, it is restored there, maximised as it was
    rect, maximized = initial_geometry(saved, [LAPTOP_1366, SECOND_SCREEN], LAPTOP_1366)
    assert rect == QRect(2000, 100, 1100, 800) and maximized


def test_saved_geometry_is_clamped_and_pulled_onto_its_screen():
    # saved on a big monitor, now the laptop's resolution is smaller
    saved = SavedGeometry(300, 50, 1400, 1000)
    rect = restored_rect(saved, [LAPTOP_1366])
    assert rect.width() == 1366 and rect.height() == 728
    assert LAPTOP_1366.contains(rect)


def test_window_whose_title_bar_is_off_screen_is_not_restored():
    saved = SavedGeometry(100, -400, 800, 600)  # title bar above the top edge
    assert restored_rect(saved, [LAPTOP_1366]) is None


@pytest.mark.parametrize(
    "data",
    [None, "x", {}, {"x": 1, "y": 2, "width": 0, "height": 5}, {"x": "1", "y": 2, "width": 3}],
)
def test_bad_saved_geometry_is_ignored(data):
    assert SavedGeometry.from_json(data) is None


def test_prefs_round_trip_window(tmp_path):
    path = tmp_path / "ui.json"
    save_prefs(UiPrefs(window=SavedGeometry(10, 20, 900, 700, True)), path)
    assert json.loads(path.read_text(encoding="utf-8"))["window"] == {
        "x": 10,
        "y": 20,
        "width": 900,
        "height": 700,
        "maximized": True,
    }
    assert load_prefs(path).window == SavedGeometry(10, 20, 900, 700, True)
    path.write_text('{"theme": "dark", "window": {"x": 1}}', encoding="utf-8")
    assert load_prefs(path).window is None  # a bad entry is ignored, not fatal


# --- the real window ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(app, condition=lambda: True, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        app.processEvents()
    assert condition()


@pytest.fixture
def new_window(qapp, tmp_path, fake_ydl, binaries):
    from vidgrab.ui.main_window import MainWindow

    made = []

    def make(available: QRect, **settings):
        win = MainWindow(
            Settings(output_dir=str(tmp_path / "out"), **settings),
            binaries,
            settings_path=tmp_path / "settings.json",
            ydl_factory=fake_ydl,
            load_thumbnails=False,
        )
        win.place_on_screen([available], available)
        win.show()
        pump(qapp)
        made.append(win)
        return win

    yield make
    for win in made:
        win.controller.shutdown()
        win.hide()
        win.deleteLater()
    qapp.processEvents()


def test_close_remembers_size_and_position(qapp, new_window, tmp_path):
    win = new_window(LAPTOP_1366)
    win.setGeometry(QRect(150, 60, 1000, 640))
    pump(qapp)
    win.close()
    saved = load_prefs(tmp_path / "ui.json").window
    assert saved == SavedGeometry(150, 60, 1000, 640, False)
    again = new_window(LAPTOP_1366)
    assert again.geometry() == QRect(150, 60, 1000, 640)


def test_window_saved_on_another_screen_opens_centred(qapp, new_window, tmp_path):
    save_prefs(UiPrefs(window=SavedGeometry(2400, 100, 1000, 700)), tmp_path / "ui.json")
    win = new_window(LAPTOP_1366)
    assert win.geometry() == default_rect(LAPTOP_1366)


@pytest.mark.parametrize("available", [LAPTOP_1366, FULLHD_150], ids=["1366x768", "1080p@150"])
def test_everything_fits_without_squashing(qapp, new_window, fake_ydl, available):
    # Worst case for the preview: audio + MP3 shows the bitrate row; jobs in the queue.
    win = new_window(available, quality=Quality.AUDIO)
    assert win.height() == min(900, available.height() - 40)
    assert available.contains(win.geometry())
    fake_ydl.scenario.final_name = "v.mp4"
    win.url_edit.setText("https://youtu.be/abc123")
    win.fetch_metadata()
    pump(qapp, win.btn_fetch.isEnabled)
    jobs = [win.enqueue_current() for _ in range(3)]
    pump(qapp, lambda: all(j.status is JobStatus.COMPLETED for j in jobs))
    assert not win.bitrate_combo.isHidden()
    assert win.page.minimumSizeHint().height() <= win.page_scroll.viewport().height()
    assert win.page_scroll.verticalScrollBar().maximum() == 0  # nothing squashed or hidden


@pytest.mark.parametrize("available", [LAPTOP_1366, FULLHD_150], ids=["1366x768", "1080p@150"])
def test_selection_scrolls_and_download_bar_stays_visible(qapp, new_window, fake_ydl, available):
    win = new_window(available)
    fake_ydl.scenario.info = yt_playlist(40)  # 40 selected: the amber warning is shown too
    win.url_edit.setText("https://www.youtube.com/playlist?list=PLtest")
    win.fetch_metadata()
    pump(qapp, lambda: win.selection_view.isVisible())
    view = win.selection_view
    assert view.warning.isVisible()
    assert win.page_scroll.verticalScrollBar().maximum() == 0  # the window does not scroll

    def bar_inside_window():
        top_left = view.btn_download.mapTo(win, view.btn_download.rect().topLeft())
        return win.rect().contains(QRect(top_left, view.btn_download.size()))

    assert view.btn_download.isVisible() and bar_inside_window()
    assert view.warning.mapTo(win, view.warning.rect().bottomLeft()).y() < win.height()
    bar = view.scroll.verticalScrollBar()
    assert bar.maximum() > 0  # header, options and cards scroll inside the card
    assert view.scroll.viewport().height() >= 150  # at least part of a card row on screen
    before = view.btn_download.mapTo(win, view.btn_download.rect().topLeft())
    bar.setValue(bar.maximum())
    pump(qapp)
    assert view.btn_download.mapTo(win, view.btn_download.rect().topLeft()) == before  # sticky
    assert bar_inside_window()
