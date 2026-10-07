"""Headless (offscreen) tests for the PySide6 layer, driven by FakeYoutubeDL."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt not loadable here")

from vidgrab import strings  # noqa: E402
from vidgrab.core.binaries import Binaries  # noqa: E402
from vidgrab.core.models import (  # noqa: E402
    MP3_BITRATES,
    AudioFormat,
    CookieSource,
    JobStatus,
    Quality,
    VideoContainer,
)
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
    assert window.preview_thumb.duration() == "1:01"  # badge on the thumbnail
    assert "YouTube" in window.preview_meta.text()
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
    window.quality_combo.setCurrentIndex(window.quality_combo.findData(Quality.AUDIO))
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


# --- format switch ---------------------------------------------------------------------


def select(combo, value):
    index = combo.findData(value)
    assert index >= 0, f"{value!r} not in combo"
    combo.setCurrentIndex(index)


def combo_values(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def bitrate_shown(win):
    return not win.bitrate_combo.isHidden() and not win.bitrate_label.isHidden()


def test_format_choices_follow_quality(window):
    # video qualities: MP4 (default, first) / MKV, no bitrate
    assert [VideoContainer(v) for v in combo_values(window.format_combo)] == [
        VideoContainer.MP4,
        VideoContainer.MKV,
    ]
    assert VideoContainer(window.format_combo.currentData()) is VideoContainer.MP4
    assert not bitrate_shown(window)
    # audio only: MP3 (default) / Original, bitrate shown for MP3 only
    select(window.quality_combo, Quality.AUDIO)
    assert [AudioFormat(v) for v in combo_values(window.format_combo)] == [
        AudioFormat.MP3,
        AudioFormat.ORIGINAL,
    ]
    assert bitrate_shown(window)
    assert int(window.bitrate_combo.currentData()) == 192
    select(window.format_combo, AudioFormat.ORIGINAL)
    assert not bitrate_shown(window)
    select(window.format_combo, AudioFormat.MP3)
    assert bitrate_shown(window)
    select(window.quality_combo, Quality.P720)
    assert not bitrate_shown(window)


def test_bitrate_choices_and_tooltip(window):
    assert [int(v) for v in combo_values(window.bitrate_combo)] == list(MP3_BITRATES)
    assert window.bitrate_combo.toolTip() == strings.TOOLTIP_BITRATE
    assert "128–160" in strings.TOOLTIP_BITRATE and "320" in strings.TOOLTIP_BITRATE


def test_video_and_audio_choices_are_remembered_separately(window):
    select(window.format_combo, VideoContainer.MKV)
    select(window.quality_combo, Quality.AUDIO)
    select(window.format_combo, AudioFormat.ORIGINAL)
    select(window.quality_combo, Quality.BEST)
    assert VideoContainer(window.format_combo.currentData()) is VideoContainer.MKV
    select(window.quality_combo, Quality.AUDIO)
    assert AudioFormat(window.format_combo.currentData()) is AudioFormat.ORIGINAL


VIDEO_COMBOS = [(q, c) for q in (Quality.BEST, Quality.P1080, Quality.P720) for c in VideoContainer]


@pytest.mark.parametrize(("quality", "container"), VIDEO_COMBOS)
def test_video_combination_reaches_ytdlp(qapp, window, fake_ydl, quality, container):
    fetch(qapp, window)
    select(window.quality_combo, quality)
    select(window.format_combo, container)
    job = window.enqueue_current()
    assert job.request.quality is quality
    assert job.request.container is container
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    params = fake_ydl.last_params
    assert params["merge_output_format"] == container.value
    assert ("format_sort" in params) is (container is VideoContainer.MP4)
    assert ("1080" in params["format"]) is (quality is Quality.P1080)


@pytest.mark.parametrize("bitrate", MP3_BITRATES)
def test_mp3_bitrate_reaches_ytdlp(qapp, window, fake_ydl, bitrate):
    fetch(qapp, window)
    select(window.quality_combo, Quality.AUDIO)
    select(window.format_combo, AudioFormat.MP3)
    select(window.bitrate_combo, bitrate)
    job = window.enqueue_current()
    assert (job.request.audio_format, job.request.mp3_bitrate) == (AudioFormat.MP3, bitrate)
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    (pp,) = fake_ydl.last_params["postprocessors"]
    assert (pp["preferredcodec"], pp["preferredquality"]) == ("mp3", str(bitrate))


def test_audio_original_reaches_ytdlp(qapp, window, fake_ydl):
    fetch(qapp, window)
    select(window.quality_combo, Quality.AUDIO)
    select(window.format_combo, AudioFormat.ORIGINAL)
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    (pp,) = fake_ydl.last_params["postprocessors"]
    assert pp["preferredcodec"] == "best"
    assert window._job_items[job.id][1].quality.text() == "Μόνο ήχος · Αρχικό (m4a/opus)"


def test_switch_does_not_affect_running_or_waiting_jobs(qapp, window, fake_ydl):
    window.apply_settings(replace(window.settings, max_concurrent=1))
    fetch(qapp, window)
    gate = threading.Event()
    fake_ydl.scenario.progress_events = [{"status": "downloading", "create": "v.mp4"}] * 2
    fake_ydl.scenario.between_events = lambda i: gate.wait(5) if i == 1 else None

    select(window.quality_combo, Quality.P1080)
    select(window.format_combo, VideoContainer.MP4)
    running = window.enqueue_current()
    wait_until(qapp, lambda: running.status is JobStatus.DOWNLOADING)
    select(window.quality_combo, Quality.AUDIO)
    select(window.format_combo, AudioFormat.MP3)
    select(window.bitrate_combo, 128)
    waiting = window.enqueue_current()
    assert waiting.status is JobStatus.QUEUED

    # change everything again while both are in the queue
    select(window.format_combo, AudioFormat.ORIGINAL)
    select(window.quality_combo, Quality.BEST)
    select(window.format_combo, VideoContainer.MKV)

    assert (running.request.quality, running.request.container) == (
        Quality.P1080,
        VideoContainer.MP4,
    )
    assert (waiting.request.quality, waiting.request.audio_format, waiting.request.mp3_bitrate) == (
        Quality.AUDIO,
        AudioFormat.MP3,
        128,
    )
    gate.set()
    wait_until(qapp, lambda: waiting.status is JobStatus.COMPLETED)
    first, second = fake_ydl.instances[-2:]
    assert first.params["merge_output_format"] == "mp4"
    assert second.params["postprocessors"][0]["preferredquality"] == "128"
    assert window._job_items[running.id][1].quality.text() == "1080p · MP4"
    assert window._job_items[waiting.id][1].quality.text() == "Μόνο ήχος · MP3 128 kbps"


def test_choices_are_saved_and_restored(qapp, window, tmp_path, fake_ydl):
    from vidgrab.ui.main_window import MainWindow

    select(window.format_combo, VideoContainer.MKV)
    select(window.quality_combo, Quality.AUDIO)
    select(window.format_combo, AudioFormat.MP3)
    select(window.bitrate_combo, 256)

    saved = load_settings(tmp_path / "settings.json")
    assert (saved.quality, saved.video_container, saved.audio_format, saved.mp3_bitrate) == (
        Quality.AUDIO,
        VideoContainer.MKV,
        AudioFormat.MP3,
        256,
    )
    reopened = MainWindow(saved, window.binaries, ydl_factory=fake_ydl, load_thumbnails=False)
    try:
        assert Quality(reopened.quality_combo.currentData()) is Quality.AUDIO
        assert AudioFormat(reopened.format_combo.currentData()) is AudioFormat.MP3
        assert int(reopened.bitrate_combo.currentData()) == 256
        assert bitrate_shown(reopened)
        select(reopened.quality_combo, Quality.BEST)
        assert VideoContainer(reopened.format_combo.currentData()) is VideoContainer.MKV
    finally:
        reopened.deleteLater()


# --- 403 from the UI: shown as FORBIDDEN, and "retry" does a full new extract_info ------


def test_forbidden_is_shown_and_ui_retry_extracts_again(qapp, window, fake_ydl):
    from yt_dlp.utils import DownloadError

    fetch(qapp, window)
    forbidden = DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    fake_ydl.scenario.attempt_errors = [forbidden] * 3  # every automatic attempt fails
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.FAILED)
    assert job.error.kind.value == "forbidden"
    widget = window._job_items[job.id][1]
    assert strings.ERR_FORBIDDEN in widget.status.text()
    assert not widget.btn_retry.isHidden()
    before = len(fake_ydl.instances)

    fake_ydl.scenario.attempt_errors = []  # YouTube lets us through now
    window.controller.retry(job.id)
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    new = fake_ydl.instances[before:]
    assert len(new) == 1
    assert new[0].extract_calls == [(job.request.url, True)]  # fresh extract_info + download


# --- lower resolution chip ---------------------------------------------------------------


def _vfmt(fid, height):
    return {"format_id": fid, "height": height, "vcodec": "vp9", "ext": "webm"}


def test_lower_resolution_chip_on_card(qapp, window, fake_ydl):
    fetch(qapp, window)
    audio = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}
    fake_ydl.scenario.info.update(
        formats=[_vfmt("401", 2160), _vfmt("137", 1080), audio],
        requested_formats=[_vfmt("137", 1080), audio],
    )
    fake_ydl.scenario.final_name = "v.mp4"
    select(window.quality_combo, Quality.BEST)
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    chip = window._job_items[job.id][1].resolution_chip
    assert not chip.isHidden()
    assert chip.text() == "1080p αντί 2160p"
    assert chip.toolTip() == strings.TOOLTIP_LOWER_RESOLUTION
    assert chip.property("tone") == "warning"  # amber, from the theme's QSS


def test_no_chip_when_resolution_is_as_requested(qapp, window, fake_ydl):
    fetch(qapp, window)
    fake_ydl.scenario.info.update(
        formats=[_vfmt("401", 2160), _vfmt("137", 1080)],
        requested_formats=[_vfmt("401", 2160)],
    )
    fake_ydl.scenario.final_name = "v.mp4"
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert window._job_items[job.id][1].resolution_chip.isHidden()


# --- "Ξανά σε πλήρη ποιότητα" button --------------------------------------------------


def _downgraded_job(qapp, window, fake_ydl):
    fetch(qapp, window)
    audio = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}
    fake_ydl.scenario.info.update(
        formats=[_vfmt("401", 2160), _vfmt("137", 1080), audio],
        requested_formats=[_vfmt("137", 1080), audio],
    )
    fake_ydl.scenario.final_name = "v.mp4"
    select(window.quality_combo, Quality.BEST)
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    return job, window._job_items[job.id][1], audio


def test_upgrade_button_replaces_with_higher_resolution(qapp, window, fake_ydl, recycle_bin):
    job, widget, audio = _downgraded_job(qapp, window, fake_ydl)
    assert not widget.btn_upgrade.isHidden()
    assert widget.btn_upgrade.toolTip() == "Ξανά σε πλήρη ποιότητα"
    old_path = job.output_path
    old_bytes = old_path.read_bytes()
    before = len(fake_ydl.instances)

    fake_ydl.scenario.info["requested_formats"] = [_vfmt("401", 2160), audio]
    widget.btn_upgrade.click()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED and job.result.upgrade)

    assert len(fake_ydl.instances) == before + 1  # one full new extract_info + download
    assert job.output_path == old_path  # same name
    assert [p for p, _ in recycle_bin] == [old_path]
    assert recycle_bin[0][1] == old_bytes
    assert widget.resolution_chip.isHidden() and widget.btn_upgrade.isHidden()
    assert strings.STATUS_UPGRADED.format(height=2160) in widget.status.text()
    assert [p.name for p in old_path.parent.iterdir()] == [old_path.name]


def test_upgrade_button_without_improvement_keeps_old(qapp, window, fake_ydl, recycle_bin):
    job, widget, _ = _downgraded_job(qapp, window, fake_ydl)
    old_bytes = job.output_path.read_bytes()

    widget.btn_upgrade.click()  # the site still offers only 1080p
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED and job.result.upgrade)

    assert strings.STATUS_NO_BETTER_QUALITY in widget.status.text()
    assert "Δεν βρέθηκε καλύτερη ποιότητα αυτή τη στιγμή" in widget.status.text()
    assert job.output_path.read_bytes() == old_bytes
    assert recycle_bin == []
    assert not widget.resolution_chip.isHidden()  # still below what was wanted
    assert not widget.btn_upgrade.isHidden()  # can try again later
    assert [p.name for p in job.output_path.parent.iterdir()] == [job.output_path.name]


def test_no_upgrade_button_at_full_quality(qapp, window, fake_ydl):
    fetch(qapp, window)
    fake_ydl.scenario.final_name = "v.mp4"
    job = window.enqueue_current()
    wait_until(qapp, lambda: job.status is JobStatus.COMPLETED)
    assert window._job_items[job.id][1].btn_upgrade.isHidden()
