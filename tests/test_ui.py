"""Headless (offscreen) tests for the PySide6 layer, driven by FakeYoutubeDL."""

from __future__ import annotations

import threading
import time

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from vidgrab import strings  # noqa: E402
from vidgrab.core.binaries import Binaries  # noqa: E402
from vidgrab.core.models import CookieSource, JobStatus, Quality  # noqa: E402
from vidgrab.core.settings import Settings, load_settings  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


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
def window(qapp, tmp_path, fake_ydl, binaries):
    from vidgrab.ui.main_window import MainWindow

    win = MainWindow(
        Settings(output_dir=str(tmp_path / "out")),
        binaries,
        settings_path=tmp_path / "settings.json",
        log_file=tmp_path / "logs" / "vidgrab.log",
        ydl_factory=fake_ydl,
        load_thumbnails=False,
    )
    yield win
    win.controller.shutdown()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def fetch(qapp, win, url="https://youtu.be/abc123"):
    win.url_edit.setText(url)
    win.fetch_metadata()
    wait_until(qapp, lambda: win.btn_fetch.isEnabled())


def test_no_warning_banner_when_all_tools_present(window):
    assert window.warning_banner.isHidden()


def test_warning_banner_when_deno_missing(qapp, tmp_path, fake_ydl):
    from vidgrab.ui.main_window import MainWindow

    win = MainWindow(
        Settings(output_dir=str(tmp_path)),
        Binaries(ffmpeg=tmp_path / "f", ffprobe=tmp_path / "p"),
        ydl_factory=fake_ydl,
        load_thumbnails=False,
    )
    assert not win.warning_banner.isHidden()
    assert win.warning_banner.text() == strings.WARN_DENO_MISSING
    win.deleteLater()


def test_fetch_metadata_shows_preview(qapp, window):
    fetch(qapp, window)
    assert window.preview_title.text() == "Test video"
    assert "1:01" in window.preview_meta.text()
    assert window.btn_download.isEnabled()
    assert window.preview_error.text() == ""


def test_fetch_error_is_shown(qapp, window, fake_ydl):
    from yt_dlp.utils import DownloadError

    fake_ydl.scenario.error = DownloadError("ERROR: [youtube] abc123: Video unavailable")
    fetch(qapp, window)
    assert window.preview_error.text() == strings.ERR_UNAVAILABLE
    assert not window.btn_download.isEnabled()


def test_invalid_url(qapp, window, fake_ydl):
    fetch(qapp, window, "hello there")
    assert window.preview_error.text() == strings.ERR_INVALID_URL
    assert fake_ydl.instances == []


def test_download_completes(qapp, window, fake_ydl, tmp_path):
    fetch(qapp, window)
    fake_ydl.scenario.progress_events = [
        {"status": "downloading", "create": "v.mp4", "downloaded_bytes": 5, "total_bytes": 10},
    ]
    fake_ydl.scenario.final_name = "Test video [abc123].mp4"
    window.quality_combo.setCurrentIndex(window.quality_combo.findData(Quality.P720))
    job = window.enqueue_current()
    assert job.request.quality is Quality.P720

    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert job.output_path == tmp_path / "out" / "Test video [abc123].mp4"
    assert "[height<=720]" in fake_ydl.last_params["format"]
    widget = window._job_items[job.id][1]
    assert widget.progress.value() == 100
    assert not widget.btn_open.isHidden()
    assert widget.btn_cancel.isHidden()
    # quality choice is persisted
    assert load_settings(tmp_path / "settings.json").quality is Quality.P720


def test_cancel_running_download_then_retry(qapp, window, fake_ydl):
    fetch(qapp, window)
    gate = threading.Event()
    sc = fake_ydl.scenario
    sc.progress_events = [
        {"status": "downloading", "create": "v.mp4", "downloaded_bytes": 1, "total_bytes": 10},
        {"status": "downloading", "create": "v.mp4", "downloaded_bytes": 2, "total_bytes": 10},
    ]
    sc.between_events = lambda i: gate.wait(5) if i == 1 else None
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.progress is not None)

    window.controller.cancel(job.id)
    assert job.status is JobStatus.CANCELLING
    gate.set()
    wait_until(qapp, lambda: job.status is JobStatus.CANCELLED)
    wait_until(qapp, lambda: not window.controller.has_active)
    widget = window._job_items[job.id][1]
    assert not widget.btn_retry.isHidden()

    sc.between_events = None
    window.controller.retry(job.id)
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert job.attempts == 2


def test_audio_quality_reaches_core_as_enum(qapp, window, fake_ydl):
    fetch(qapp, window)
    window.quality_combo.setCurrentIndex(window.quality_combo.findData(Quality.AUDIO_MP3))
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert fake_ydl.last_params["postprocessors"][0]["preferredcodec"] == "mp3"


def test_failed_download_shows_message(qapp, window, fake_ydl):
    from yt_dlp.utils import DownloadError

    fetch(qapp, window)
    fake_ydl.scenario.error = DownloadError("ERROR: [youtube] abc123: Private video")
    fake_ydl.scenario.progress_events = [{"status": "downloading", "create": "v.mp4"}]
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.FAILED)
    widget = window._job_items[job.id][1]
    assert strings.ERR_PRIVATE in widget.status.text()
    assert not widget.btn_details.isHidden()


def test_concurrency_limit(qapp, window, fake_ydl):
    fetch(qapp, window)
    gate = threading.Event()
    fake_ydl.scenario.progress_events = [{"status": "downloading", "create": "v.mp4"}] * 2
    fake_ydl.scenario.between_events = lambda i: gate.wait(5)
    jobs = [window.enqueue_current() for _ in range(3)]
    wait_until(qapp, lambda: window.controller.queue.active_count == 2)
    assert jobs[2].status is JobStatus.QUEUED
    gate.set()
    wait_until(qapp, lambda: all(j.status is JobStatus.COMPLETED for j in jobs))


def test_clear_finished_removes_rows(qapp, window, fake_ydl):
    fetch(qapp, window)
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert window.queue_list.count() == 1
    window.controller.clear_finished()
    assert window.queue_list.count() == 0


def test_output_dir_persisted(qapp, window, tmp_path):
    window.set_output_dir(str(tmp_path / "elsewhere"))
    assert window.dest_label.text() == str(tmp_path / "elsewhere")
    assert load_settings(tmp_path / "settings.json").output_dir == str(tmp_path / "elsewhere")


def test_settings_dialog(qapp, tmp_path):
    from vidgrab.ui.dialogs import SettingsDialog

    dlg = SettingsDialog(Settings(output_dir=str(tmp_path)))
    assert CookieSource(dlg.cookie_source.itemData(1)) is CookieSource.FIREFOX
    assert not dlg.cookie_file_row.isEnabled()
    dlg.cookie_source.setCurrentIndex(dlg.cookie_source.findData(CookieSource.FILE))
    assert dlg.cookie_file_row.isEnabled()
    dlg.cookie_file.setText(" C:/cookies.txt ")
    dlg.max_concurrent.setValue(3)
    result = dlg.result_settings()
    assert result.cookie_source is CookieSource.FILE
    assert result.cookie_file == "C:/cookies.txt"
    assert result.max_concurrent == 3
    assert result.output_dir == str(tmp_path)
    dlg.deleteLater()


def test_apply_settings_updates_concurrency(qapp, window, tmp_path):
    from dataclasses import replace

    window.apply_settings(
        replace(window.settings, max_concurrent=4, cookie_source=CookieSource.FIREFOX)
    )
    assert window.controller.queue.max_concurrent == 4
    saved = load_settings(tmp_path / "settings.json")
    assert saved.cookie_source is CookieSource.FIREFOX


def test_main_self_check_exit_code(tmp_path, monkeypatch):
    from vidgrab import __main__ as entry
    from vidgrab.core import binaries as binmod

    for name in ("ffmpeg", "ffprobe", "deno"):
        (tmp_path / binmod.exe_name(name)).write_bytes(b"")
    monkeypatch.setattr(binmod, "default_search_dirs", lambda: [tmp_path])
    monkeypatch.setattr(binmod.shutil, "which", lambda name: None)
    report = tmp_path / "report.txt"
    assert entry.main(["--self-check", "--report", str(report)]) == 0
    assert report.read_text(encoding="utf-8").strip().endswith("PASS")

    (tmp_path / binmod.exe_name("deno")).unlink()
    assert entry.main(["--self-check", "--report", str(report)]) == 1
    assert "MISSING  deno" in report.read_text(encoding="utf-8")
