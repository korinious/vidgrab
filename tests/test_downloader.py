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
        make_request(tmp_path, Quality.AUDIO),
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
        make_request(tmp_path, Quality.AUDIO),
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


def test_relative_output_dir_is_rejected(tmp_path, fake_ydl, binaries, monkeypatch):
    monkeypatch.chdir(tmp_path)
    request = DownloadRequest("https://youtu.be/abc123", Quality.BEST, Path("rel/out"))
    with pytest.raises(UserError) as ei:
        download(request, binaries, lambda p: None, threading.Event(), ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.DISK
    assert fake_ydl.instances == []
    assert list(tmp_path.iterdir()) == []  # nothing created relative to the CWD


# --- formats and MP4 audio check -----------------------------------------------------


def test_request_format_choices_reach_ytdlp(tmp_path, fake_ydl, binaries):
    from vidgrab.core.models import AudioFormat, VideoContainer

    req = DownloadRequest(
        "https://youtu.be/abc123",
        Quality.P1080,
        tmp_path / "out",
        container=VideoContainer.MKV,
    )
    download(req, binaries, lambda p: None, threading.Event(), ydl_factory=fake_ydl)
    assert fake_ydl.last_params["merge_output_format"] == "mkv"

    req = DownloadRequest(
        "https://youtu.be/abc123",
        Quality.AUDIO,
        tmp_path / "out",
        audio_format=AudioFormat.MP3,
        mp3_bitrate=320,
    )
    download(req, binaries, lambda p: None, threading.Event(), ydl_factory=fake_ydl)
    assert fake_ydl.last_params["postprocessors"][0]["preferredquality"] == "320"


def _bins_that_exist(tmp_path):
    from vidgrab.core.binaries import Binaries

    d = tmp_path / "realbin"
    d.mkdir(exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (d / name).write_bytes(b"")
    return Binaries(ffmpeg=d / "ffmpeg", ffprobe=d / "ffprobe")


def _recording_runner(codec):
    from vidgrab.core.audiofix import CommandResult

    calls = []

    def runner(args, cancel_event):
        calls.append(list(args))
        if Path(args[0]).name == "ffprobe":
            return CommandResult(0, codec + "\n")
        Path(args[-1]).write_bytes(b"aac")
        return CommandResult(0)

    runner.calls = calls
    return runner


def test_mp4_with_opus_audio_gets_aac(tmp_path, fake_ydl):
    fake_ydl.scenario.final_name = "v.mp4"
    runner = _recording_runner("opus")
    updates = []
    path = download(
        make_request(tmp_path),  # BEST + MP4 (default)
        _bins_that_exist(tmp_path),
        updates.append,
        threading.Event(),
        ydl_factory=fake_ydl,
        runner=runner,
    )
    assert path.read_bytes() == b"aac"
    assert [Path(c[0]).name for c in runner.calls] == ["ffprobe", "ffmpeg"]
    assert updates[-1].phase is Phase.POSTPROCESSING


@pytest.mark.parametrize(
    ("quality", "container"),
    [(Quality.BEST, "mkv"), (Quality.AUDIO, "mp4")],
)
def test_no_audio_check_for_mkv_or_audio_only(tmp_path, fake_ydl, quality, container):
    from vidgrab.core.models import VideoContainer

    fake_ydl.scenario.final_name = "v.mkv" if container == "mkv" else "song.mp3"
    runner = _recording_runner("opus")
    req = DownloadRequest(
        "https://youtu.be/abc123", quality, tmp_path / "out", container=VideoContainer(container)
    )
    download(
        req,
        _bins_that_exist(tmp_path),
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        runner=runner,
    )
    assert runner.calls == []


def test_cancel_before_audio_check(tmp_path, fake_ydl):
    cancel = threading.Event()
    fake_ydl.scenario.final_name = "v.mp4"
    fake_ydl.scenario.progress_events = [{"status": "downloading", "create": "v.mp4"}]
    fake_ydl.scenario.between_events = lambda i: cancel.set()
    runner = _recording_runner("opus")
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            _bins_that_exist(tmp_path),
            lambda p: None,
            cancel,
            ydl_factory=fake_ydl,
            runner=runner,
        )
    assert ei.value.kind is ErrorKind.CANCELLED
    assert runner.calls == []
