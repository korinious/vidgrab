import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadCancelled

from vidgrab.core.audiofix import (
    CommandResult,
    ensure_mp4_audio,
    needs_aac,
    probe_audio_codecs,
    run_command,
)
from vidgrab.core.binaries import Binaries


class FakeRunner:
    """Scripted stand-in for ffprobe/ffmpeg. Records every command."""

    def __init__(self, codecs="opus\n", probe_rc=0, ffmpeg_rc=0):
        self.codecs = codecs
        self.probe_rc = probe_rc
        self.ffmpeg_rc = ffmpeg_rc
        self.calls: list[list[str]] = []

    def __call__(self, args, cancel_event):
        args = list(args)
        self.calls.append(args)
        if "ffprobe" in Path(args[0]).name:
            return CommandResult(self.probe_rc, self.codecs, "probe err")
        if self.ffmpeg_rc == 0:
            Path(args[-1]).write_bytes(b"converted")  # ffmpeg writes the output file
        return CommandResult(self.ffmpeg_rc, "", "ffmpeg err")

    @property
    def ffmpeg_calls(self):
        return [c for c in self.calls if "ffmpeg" in Path(c[0]).name]


@pytest.fixture
def real_bins(tmp_path) -> Binaries:
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (d / name).write_bytes(b"")
    return Binaries(ffmpeg=d / "ffmpeg", ffprobe=d / "ffprobe")


@pytest.fixture
def mp4(tmp_path) -> Path:
    f = tmp_path / "video.mp4"
    f.write_bytes(b"original")
    return f


@pytest.mark.parametrize(
    ("codecs", "expected"),
    [
        (["aac"], False),
        (["mp3"], False),
        (["ac3", "eac3"], False),
        ([], False),  # no audio track
        (["opus"], True),
        (["vorbis"], True),
        (["flac"], True),
        (["aac", "opus"], True),
    ],
)
def test_needs_aac(codecs, expected):
    assert needs_aac(codecs) is expected


def test_probe_parses_codecs(real_bins, mp4):
    runner = FakeRunner(codecs="opus\n\nAAC\n")
    assert probe_audio_codecs(mp4, real_bins.ffprobe, runner, threading.Event()) == ["opus", "aac"]
    (call,) = runner.calls
    assert call[0] == str(real_bins.ffprobe)
    assert call[-1] == str(mp4)
    assert call[call.index("-select_streams") : call.index("-select_streams") + 2] == [
        "-select_streams",
        "a",
    ]


def test_opus_is_converted_audio_only(real_bins, mp4):
    runner = FakeRunner(codecs="opus\n")
    assert ensure_mp4_audio(mp4, real_bins, threading.Event(), runner) is True
    (cmd,) = runner.ffmpeg_calls
    # video is copied, only audio is encoded
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "libx264" not in cmd and "-vcodec" not in cmd
    assert mp4.read_bytes() == b"converted"  # replaced in place, same name
    assert not list(mp4.parent.glob("*.tmp.mp4"))


@pytest.mark.parametrize("codecs", ["aac\n", "", "mp3\n"])
def test_compatible_audio_is_left_alone(real_bins, mp4, codecs):
    runner = FakeRunner(codecs=codecs)
    assert ensure_mp4_audio(mp4, real_bins, threading.Event(), runner) is False
    assert runner.ffmpeg_calls == []
    assert mp4.read_bytes() == b"original"


def test_non_mp4_is_skipped(real_bins, tmp_path):
    mkv = tmp_path / "v.mkv"
    mkv.write_bytes(b"x")
    runner = FakeRunner()
    assert ensure_mp4_audio(mkv, real_bins, threading.Event(), runner) is False
    assert runner.calls == []


def test_missing_tools_skip_with_warning(mp4, caplog):
    runner = FakeRunner()
    assert ensure_mp4_audio(mp4, Binaries(), threading.Event(), runner) is False
    assert runner.calls == []
    assert "cannot check MP4 audio" in caplog.text


def test_ffmpeg_failure_keeps_original_and_cleans_tmp(real_bins, mp4):
    runner = FakeRunner(codecs="opus\n", ffmpeg_rc=1)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        ensure_mp4_audio(mp4, real_bins, threading.Event(), runner)
    assert mp4.read_bytes() == b"original"
    assert not list(mp4.parent.glob("*.tmp.mp4"))


def test_ffprobe_failure_raises(real_bins, mp4):
    with pytest.raises(RuntimeError, match="ffprobe failed"):
        ensure_mp4_audio(mp4, real_bins, threading.Event(), FakeRunner(probe_rc=1))


def test_run_command_returns_output():
    result = run_command([sys.executable, "-c", "print('hi')"], threading.Event())
    assert result.returncode == 0
    assert result.stdout.strip() == "hi"


def test_run_command_kills_on_cancel():
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    with pytest.raises(DownloadCancelled):
        run_command([sys.executable, "-c", "import time; time.sleep(30)"], cancel)
    timer.cancel()


# --- integration with a real ffmpeg (skipped when ffmpeg/ffprobe are not installed) -----

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe not on PATH")


def _ffmpeg(*args):
    subprocess.run([_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _video_packets_md5(path):
    out = subprocess.run(
        [_FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.strip()


@needs_ffmpeg
def test_real_ffmpeg_converts_opus_and_copies_video(tmp_path):
    src = tmp_path / "clip.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "libopus", str(src),
    )  # fmt: skip
    bins = Binaries(ffmpeg=Path(_FFMPEG), ffprobe=Path(_FFPROBE))
    cancel = threading.Event()
    assert probe_audio_codecs(src, bins.ffprobe, run_command, cancel) == ["opus"]
    video_before = _video_packets_md5(src)

    assert ensure_mp4_audio(src, bins, cancel) is True

    assert probe_audio_codecs(src, bins.ffprobe, run_command, cancel) == ["aac"]
    assert _video_packets_md5(src) == video_before  # video stream untouched
    assert ensure_mp4_audio(src, bins, cancel) is False  # second pass: nothing to do
