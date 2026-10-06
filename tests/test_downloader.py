import logging
import os
import shutil
import subprocess
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
    ).path

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
        {"status": "finished", "create": "song.mp3"},
    ]
    path = download(
        make_request(tmp_path, Quality.AUDIO),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
    ).path
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
    # yt-dlp works inside the job's private staging folder, never in the destination
    assert params["outtmpl"]["default"].startswith(str(tmp_path / "staging"))
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


def test_cancel_mid_download_removes_staging(tmp_path, fake_ydl, binaries, staging_root):
    cancel = threading.Event()
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "other.mp4"
    existing.write_bytes(b"keep me")
    seen_stage = []

    def between(index):
        stage = Path(fake_ydl.last_params["outtmpl"]["default"]).parent
        if index == 1:
            # yt-dlp's .part file for the stream being written
            (stage / "v.f137.mp4.part").write_bytes(b"partial")
            seen_stage.append(stage)
        if index == 2:
            cancel.set()

    sc = fake_ydl.scenario
    sc.progress_events = two_stream_events()
    sc.between_events = between

    with pytest.raises(UserError) as ei:
        download(make_request(tmp_path), binaries, lambda p: None, cancel, ydl_factory=fake_ydl)

    assert ei.value.kind is ErrorKind.CANCELLED
    assert seen_stage and not seen_stage[0].exists()  # whole staging folder removed
    assert list(staging_root.iterdir()) == []
    assert sorted(p.name for p in out.iterdir()) == ["other.mp4"]  # destination untouched


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


def test_failure_is_classified_and_cleans_staging(tmp_path, fake_ydl, binaries, staging_root):
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
    assert list(staging_root.iterdir()) == []
    assert list((tmp_path / "out").iterdir()) == []  # no partial data in the destination


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
    ).path
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


# --- HTTP 403: fresh extract_info retries and fallback ---------------------------------

from vidgrab import strings  # noqa: E402
from vidgrab.core import staging as staging_mod  # noqa: E402
from vidgrab.core.downloader import YOUTUBE_FALLBACK_CLIENTS, RetryPolicy  # noqa: E402

FAST = RetryPolicy(forbidden_delays=(0, 0), move_backoff=(0, 0, 0), sleep=lambda s: None)


def http403():
    return DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")


def stream_event(format_id="401"):
    return {
        "status": "downloading",
        "create": f"v.f{format_id}.mp4",
        "downloaded_bytes": 1,
        "total_bytes": 10,
        "info_dict": {"format_id": format_id},
    }


def test_403_passes_on_second_retry(tmp_path, fake_ydl, binaries, caplog):
    caplog.set_level(logging.INFO, logger="vidgrab")
    sc = fake_ydl.scenario
    sc.attempt_errors = [http403(), http403(), None]
    sc.progress_events = [stream_event("401")]
    sc.final_name = "v.mp4"

    path = download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    ).path

    assert path == tmp_path / "out" / "v.mp4"
    # three separate YoutubeDL instances = three full, fresh extract_info calls
    assert len(fake_ydl.instances) == 3
    assert all(
        i.extract_calls == [("https://www.youtube.com/watch?v=abc123", True)]
        for i in fake_ydl.instances
    )
    first, second, last = (i.params for i in fake_ydl.instances)
    assert "extractor_args" not in first and "extractor_args" not in second
    assert first["format"] == second["format"]
    # last retry: other YouTube clients, and the refused format is excluded
    assert last["extractor_args"]["youtube"]["player_client"] == YOUTUBE_FALLBACK_CLIENTS
    assert "[format_id!='401']" in last["format"]
    assert caplog.text.count("HTTP 403 on attempt") == 2
    assert "Download attempt 3/3" in caplog.text
    assert "403 fallback" in caplog.text


def test_403_once_then_ok_needs_no_fallback(tmp_path, fake_ydl, binaries):
    fake_ydl.scenario.attempt_errors = [http403(), None]
    download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    )
    assert len(fake_ydl.instances) == 2
    assert "extractor_args" not in fake_ydl.last_params


def test_403_that_never_passes_is_forbidden(tmp_path, fake_ydl, binaries, staging_root):
    fake_ydl.scenario.attempt_errors = [http403(), http403(), http403(), None]
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
            policy=FAST,
        )
    assert ei.value.kind is ErrorKind.FORBIDDEN
    assert ei.value.message == strings.ERR_FORBIDDEN
    assert "403" in ei.value.message
    assert len(fake_ydl.instances) == 3  # 1 try + 2 retries, then give up
    assert list(staging_root.iterdir()) == []


def test_403_on_other_site_uses_generic_message_and_no_youtube_args(tmp_path, fake_ydl, binaries):
    fake_ydl.scenario.attempt_errors = [http403(), http403(), http403()]
    fake_ydl.scenario.progress_events = [stream_event("hd-720")]
    req = DownloadRequest("https://x.com/a/status/1", Quality.BEST, tmp_path / "out")
    with pytest.raises(UserError) as ei:
        download(
            req, binaries, lambda p: None, threading.Event(), ydl_factory=fake_ydl, policy=FAST
        )
    assert ei.value.kind is ErrorKind.FORBIDDEN
    assert ei.value.message == strings.ERR_FORBIDDEN_OTHER_SITE
    last = fake_ydl.last_params
    assert "extractor_args" not in last
    assert "[format_id!='hd-720']" in last["format"]


def test_other_errors_are_not_retried(tmp_path, fake_ydl, binaries):
    fake_ydl.scenario.attempt_errors = [
        DownloadError("ERROR: [youtube] abc123: Video unavailable"),
        None,
    ]
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
            policy=FAST,
        )
    assert ei.value.kind is ErrorKind.UNAVAILABLE
    assert len(fake_ydl.instances) == 1


def test_cancel_while_waiting_to_retry_403(tmp_path, fake_ydl, binaries):
    cancel = threading.Event()
    fake_ydl.scenario.attempt_errors = [http403(), None]
    threading.Timer(0.2, cancel.set).start()
    slow = RetryPolicy(forbidden_delays=(30, 30))
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            cancel,
            ydl_factory=fake_ydl,
            policy=slow,
        )
    assert ei.value.kind is ErrorKind.CANCELLED
    assert len(fake_ydl.instances) == 1  # did not start another attempt


# --- WinError 32 when moving the finished file ------------------------------------------


def _winerror32():
    exc = PermissionError(
        13, "The process cannot access the file because it is being used by another process"
    )
    exc.winerror = 32
    return exc


def test_winerror32_on_rename_passes_after_two_attempts(
    tmp_path, fake_ydl, binaries, monkeypatch, staging_root
):
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) <= 2:
            raise _winerror32()
        os.replace(src, dst)

    monkeypatch.setattr(staging_mod, "_default_replace", flaky)
    fake_ydl.scenario.final_name = "v.mp4"
    path = download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    ).path
    assert path == tmp_path / "out" / "v.mp4" and path.read_bytes() == b"done"
    assert len(calls) == 3
    assert list(staging_root.iterdir()) == []


def test_winerror32_on_rename_that_never_clears_is_file_locked(
    tmp_path, fake_ydl, binaries, monkeypatch, staging_root
):
    def locked(src, dst):
        raise _winerror32()

    monkeypatch.setattr(staging_mod, "_default_replace", locked)
    fake_ydl.scenario.final_name = "v.mp4"
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
            policy=FAST,
        )
    assert ei.value.kind is ErrorKind.FILE_LOCKED
    assert ei.value.message == strings.ERR_FILE_LOCKED
    assert list((tmp_path / "out").iterdir()) == []
    assert list(staging_root.iterdir()) == []


def test_ytdlp_rename_failure_message_is_file_locked(tmp_path, fake_ydl, binaries):
    # The exact error from the Windows report, raised inside yt-dlp itself.
    fake_ydl.scenario.error = DownloadError(
        "ERROR: Unable to rename file: [WinError 32] The process cannot access the file "
        "because it is being used by another process: 'C:\\\\x\\\\v.f401.mp4.part' -> "
        "'C:\\\\x\\\\v.f401.mp4'. Giving up after 3 retries"
    )
    with pytest.raises(UserError) as ei:
        download(
            make_request(tmp_path),
            binaries,
            lambda p: None,
            threading.Event(),
            ydl_factory=fake_ydl,
            policy=FAST,
        )
    assert ei.value.kind is ErrorKind.FILE_LOCKED


def test_ytdlp_gets_more_file_access_retries(tmp_path, fake_ydl, binaries):
    download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    )
    assert fake_ydl.last_params["file_access_retries"] == 10


# --- two jobs with the same video id at the same time -----------------------------------


def test_two_concurrent_jobs_same_video_id(tmp_path, fake_ydl, binaries, staging_root):
    both_downloading = threading.Barrier(2, timeout=5)
    stages = set()

    def between(index):
        stages.add(Path(fake_ydl.instances[-1].params["outtmpl"]["default"]).parent)
        both_downloading.wait()  # make the two downloads overlap

    sc = fake_ydl.scenario
    sc.progress_events = [stream_event("137")]
    sc.between_events = between
    sc.final_name = "Test video [abc123].mp4"
    results, errors = [], []

    def run():
        try:
            results.append(
                download(
                    make_request(tmp_path),
                    binaries,
                    lambda p: None,
                    threading.Event(),
                    ydl_factory=fake_ydl,
                    policy=FAST,
                ).path
            )
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert errors == []
    assert len({p.parent for p in stages}) == 1 and len(stages) == 2  # separate folders
    assert sorted(p.name for p in results) == [
        "Test video [abc123] (2).mp4",
        "Test video [abc123].mp4",
    ]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(p.name for p in results)
    assert list(staging_root.iterdir()) == []


# --- end to end with the real yt-dlp and ffmpeg (local file:// source, no network) ------


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not on PATH"
)
def test_real_ytdlp_end_to_end_mp4(tmp_path, staging_root):
    from yt_dlp import YoutubeDL

    from vidgrab.core.binaries import Binaries

    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    src = tmp_path / "src" / "clip.webm"
    src.parent.mkdir()
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=1",
         "-f", "lavfi", "-i", "sine=duration=1",
         "-c:v", "libvpx-vp9", "-c:a", "libopus", str(src)],
        check=True,
    )  # fmt: skip
    bins = Binaries(ffmpeg=Path(ffmpeg), ffprobe=Path(ffprobe))

    def factory(params):
        return YoutubeDL({**params, "enable_file_urls": True})

    from vidgrab.core.models import VideoContainer

    req = DownloadRequest(
        src.as_uri(), Quality.BEST, tmp_path / "out", container=VideoContainer.MP4
    )
    first = download(req, bins, lambda p: None, threading.Event(), ydl_factory=factory).path
    second = download(req, bins, lambda p: None, threading.Event(), ydl_factory=factory).path

    def codecs(path):
        return subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.split()  # fmt: skip

    assert first.name == "clip [clip].mp4" and second.name == "clip [clip] (2).mp4"
    assert codecs(first) == ["vp9", "aac"]  # video copied, only audio converted
    assert list(staging_root.iterdir()) == []


# --- lower resolution than requested -----------------------------------------------------


def _vf(fid, height):
    return {"format_id": fid, "height": height, "vcodec": "vp9", "ext": "webm"}


AUDIO_140 = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}


def test_403_fallback_to_lower_resolution_is_reported(tmp_path, fake_ydl, binaries, caplog):
    sc = fake_ydl.scenario
    # attempts 1 and 2 start the 4K stream and get 403; the fallback excludes it
    sc.attempt_errors = [http403(), http403(), None]
    sc.progress_events = [{**stream_event("401"), "info_dict": _vf("401", 2160)}]
    sc.info.update(
        formats=[_vf("401", 2160), _vf("400", 1440), _vf("137", 1080), AUDIO_140],
        requested_formats=[_vf("400", 1440), AUDIO_140],
    )
    sc.final_name = "v.mp4"
    result = download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    )
    assert (result.requested_height, result.actual_height) == (2160, 1440)
    assert result.downgraded
    assert "Lower resolution than requested" in caplog.text


def test_4k_dropped_from_formats_after_client_switch_is_still_reported(
    tmp_path, fake_ydl, binaries
):
    # The fallback clients may not list the 4K format at all; the attempted height counts.
    sc = fake_ydl.scenario
    sc.attempt_errors = [http403(), http403(), None]
    sc.progress_events = [{**stream_event("401"), "info_dict": _vf("401", 2160)}]
    sc.info.update(
        formats=[_vf("137", 1080), AUDIO_140], requested_formats=[_vf("137", 1080), AUDIO_140]
    )
    result = download(
        make_request(tmp_path),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    )
    assert (result.requested_height, result.actual_height) == (2160, 1080)


@pytest.mark.parametrize(
    ("quality", "available", "got", "downgraded"),
    [
        (Quality.P1080, [2160, 1080, 720], 720, True),  # any reason, not only 403
        (Quality.P1080, [2160, 1080, 720], 1080, False),
        (Quality.P1080, [720, 480], 720, False),  # the video has no 1080p: not a downgrade
        (Quality.BEST, [2160, 1440], 2160, False),
        (Quality.BEST, [2160, 1440], 1440, True),
    ],
)
def test_resolution_check_for_any_reason(
    tmp_path, fake_ydl, binaries, quality, available, got, downgraded
):
    sc = fake_ydl.scenario
    sc.info.update(
        formats=[_vf(str(h), h) for h in available] + [AUDIO_140],
        requested_formats=[_vf(str(got), got), AUDIO_140],
    )
    sc.final_name = "v.mp4"
    req = DownloadRequest("https://youtu.be/abc123", quality, tmp_path / "out")
    result = download(
        req, binaries, lambda p: None, threading.Event(), ydl_factory=fake_ydl, policy=FAST
    )
    assert result.actual_height == got
    assert result.downgraded is downgraded


def test_audio_only_has_no_resolution_check(tmp_path, fake_ydl, binaries):
    fake_ydl.scenario.info.update(
        formats=[_vf("401", 2160), AUDIO_140], requested_formats=[AUDIO_140]
    )
    fake_ydl.scenario.final_name = "song.mp3"
    result = download(
        make_request(tmp_path, Quality.AUDIO),
        binaries,
        lambda p: None,
        threading.Event(),
        ydl_factory=fake_ydl,
        policy=FAST,
    )
    assert result.requested_height is None and not result.downgraded
