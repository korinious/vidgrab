import threading
from pathlib import Path

import pytest
from yt_dlp.cookies import CookieLoadError
from yt_dlp.utils import DownloadError

from vidgrab.core.downloader import download
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.models import CookieConfig, CookieSource, DownloadRequest, Phase, Quality


def make_request(tmp_path: Path, quality=Quality.BEST, cookies=None) -> DownloadRequest:
    return DownloadRequest(
        url="https://www.youtube.com/watch?v=abc123",
        quality=quality,
        output_dir=tmp_path / "out",
        cookies=cookies or CookieConfig(),
    )


def two_stream_events():
    info = {"id": "abc123", "requested_formats": [{"format_id": "137"}, {"format_id": "140"}]}
    return [
        {
            "status": "downloading",
            "create": "v.f137.mp4",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 10.0,
            "eta": 5,
            "info_dict": info,
        },
        {
            "status": "downloading",
            "create": "v.f137.mp4",
            "downloaded_bytes": 100,
            "total_bytes": 100,
            "info_dict": info,
        },
        {"status": "finished", "create": "v.f137.mp4", "info_dict": info},
        {
            "status": "downloading",
            "create": "v.f140.m4a",
            "downloaded_bytes": 10,
            "total_bytes_estimate": 40,
            "info_dict": info,
        },
    ]


def test_progress_and_final_path(tmp_path, fake_ydl, binaries):
    sc = fake_ydl.scenario
    sc.progress_events = two_stream_events()
    sc.postprocessor_events = [{"status": "started", "postprocessor": "Merger"}]
    sc.final_name = "v.mp4"
    updates = []

    path = download(
        make_request(tmp_path), binaries, updates.append, threading.Event(), ydl_factory=fake_ydl
    )

    assert path == tmp_path / "out" / "v.mp4"
    downloading = [u for u in updates if u.phase is Phase.DOWNLOADING]
    assert [(u.stream_index, u.stream_count) for u in downloading] == [(1, 2), (1, 2), (2, 2)]
    assert downloading[0].overall_fraction == 0.25
    assert downloading[0].speed == 10.0 and downloading[0].eta == 5
    assert downloading[2].total_bytes == 40  # falls back to the estimate
    assert updates[-1].phase is Phase.POSTPROCESSING


def test_postprocessor_filepath_wins(tmp_path, fake_ydl, binaries):
    final = str(tmp_path / "out" / "song.mp3")
    fake_ydl.scenario.postprocessor_events = [
        {"status": "started"},
        {"status": "finished", "info_dict": {"filepath": final}},
    ]
    path = download(
        make_request(tmp_path, Quality.AUDIO_MP3),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
    )
    assert path == Path(final)


def test_options_passed_to_ytdlp(tmp_path, fake_ydl, binaries):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    download(
        make_request(tmp_path, Quality.P720, CookieConfig(CookieSource.FILE, str(cookie_file))),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
    )
    params = fake_ydl.last_params
    assert "[height<=720]" in params["format"]
    assert params["outtmpl"]["default"].startswith(str(tmp_path / "out"))
    assert params["outtmpl"]["default"].endswith("[%(id)s].%(ext)s")
    assert params["cookiefile"] == str(cookie_file)
    assert params["noplaylist"] is True
    assert params["windowsfilenames"] is True
    assert params["js_runtimes"] == {"deno": {"path": str(binaries.deno)}}
    assert (tmp_path / "out").is_dir()


def test_audio_options(tmp_path, fake_ydl, binaries):
    download(
        make_request(tmp_path, Quality.AUDIO_MP3),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
    )
    assert fake_ydl.last_params["postprocessors"][0]["preferredcodec"] == "mp3"


def test_cancel_mid_download_cleans_partials(tmp_path, fake_ydl, binaries):
    cancel = threading.Event()
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "other.mp4"
    existing.write_bytes(b"keep me")

    def between(index):
        if index == 1:
            # yt-dlp's .part file for the stream being written
            (out / "v.f137.mp4.part").write_bytes(b"partial")
        if index == 2:
            cancel.set()

    sc = fake_ydl.scenario
    sc.progress_events = two_stream_events()
    sc.between_events = between

    with pytest.raises(UserError) as ei:
        download(make_request(tmp_path), binaries, lambda p: None, cancel, ydl_factory=fake_ydl)

    assert ei.value.kind is ErrorKind.CANCELLED
    assert not (out / "v.f137.mp4").exists()
    assert not (out / "v.f137.mp4.part").exists()
    assert existing.exists()


def test_cancel_before_start_never_calls_ytdlp(tmp_path, fake_ydl, binaries):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(UserError) as ei:
        download(make_request(tmp_path), binaries, lambda p: None, cancel, ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.CANCELLED
    assert fake_ydl.instances == []


def test_cancel_during_postprocessing(tmp_path, fake_ydl, binaries):
    cancel = threading.Event()
    sc = fake_ydl.scenario
    sc.progress_events = two_stream_events()[:1]
    sc.postprocessor_events = [{"status": "started"}]
    sc.between_events = lambda i: None

    def on_progress(p):
        if p.phase is Phase.DOWNLOADING:
            cancel.set()

    # The hook that delivers the first progress update is followed by the cancel check in
    # the next hook call (postprocessor started).
    with pytest.raises(UserError) as ei:
        download(make_request(tmp_path), binaries, on_progress, cancel, ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.CANCELLED
    assert not (tmp_path / "out" / "v.f137.mp4").exists()


def test_failure_is_classified_and_keeps_completed_files(tmp_path, fake_ydl, binaries):
    sc = fake_ydl.scenario
    sc.progress_events = two_stream_events()[:1]
    sc.error = DownloadError("ERROR: [youtube] abc123: Sign in to confirm you're not a bot")
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
        )
    assert ei.value.kind is ErrorKind.LOGIN_REQUIRED
    # Non-cancel failures keep partial data so yt-dlp can resume on retry.
    assert (tmp_path / "out" / "v.f137.mp4").exists()


def test_cookie_load_error(tmp_path, fake_ydl, binaries):
    fake_ydl.scenario.error = CookieLoadError("failed to load cookies")
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path, cookies=CookieConfig(CookieSource.CHROME)),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
        )
    assert ei.value.kind is ErrorKind.COOKIES_FAILED


def test_unwritable_output_dir(tmp_path, fake_ydl, binaries):
    blocker = tmp_path / "out"
    blocker.write_text("I am a file, not a directory")
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
        )
    assert ei.value.kind is ErrorKind.DISK
