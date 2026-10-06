"""Make sure an MP4's audio plays everywhere, converting only the audio when needed.

yt-dlp can put Opus/Vorbis audio into an MP4 container, which many Windows players cannot
play. After an MP4 download we probe the audio codec(s); if any is not MP4-friendly, ffmpeg
rewrites the file with the video stream *copied* and only the audio re-encoded to AAC.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from yt_dlp.utils import DownloadCancelled

from vidgrab.core.binaries import Binaries

log = logging.getLogger(__name__)

# Audio codecs (ffprobe codec_name) that play from MP4 in common Windows players.
MP4_FRIENDLY_AUDIO = frozenset({"aac", "mp3", "alac", "ac3", "eac3"})
AAC_BITRATE = "192k"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


# (args, cancel_event) -> CommandResult. Injected in tests; real one runs a subprocess.
CommandRunner = Callable[[Sequence[str], threading.Event], CommandResult]


def run_command(args: Sequence[str], cancel_event: threading.Event) -> CommandResult:
    """Run a command, killing it if ``cancel_event`` is set. Raises DownloadCancelled then."""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # no console flash in GUI app
    with subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    ) as proc:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                return CommandResult(proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if cancel_event.is_set():
                    proc.kill()
                    proc.communicate()
                    raise DownloadCancelled() from None


def probe_audio_codecs(
    path: Path, ffprobe: Path, runner: CommandRunner, cancel_event: threading.Event
) -> list[str]:
    result = runner(
        [
            str(ffprobe),
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_name",
            "-of", "csv=p=0",
            str(path),
        ],
        cancel_event,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed ({result.returncode}): {result.stderr.strip()}")
    return [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]


def needs_aac(codecs: Sequence[str]) -> bool:
    return any(codec not in MP4_FRIENDLY_AUDIO for codec in codecs)


def ensure_mp4_audio(
    path: Path,
    binaries: Binaries,
    cancel_event: threading.Event,
    runner: CommandRunner = run_command,
) -> bool:
    """Convert ``path``'s audio to AAC if it is not MP4-friendly. Returns True if converted.

    Skips (with a warning) when ffmpeg/ffprobe are missing; the app already warns about that.
    """
    if path.suffix.lower() != ".mp4" or not path.is_file():
        return False
    ffmpeg, ffprobe = binaries.ffmpeg, binaries.ffprobe
    if ffmpeg is None or ffprobe is None or not ffmpeg.is_file() or not ffprobe.is_file():
        log.warning("ffmpeg/ffprobe unavailable; cannot check MP4 audio of %s", path)
        return False

    codecs = probe_audio_codecs(path, ffprobe, runner, cancel_event)
    if not needs_aac(codecs):
        log.info("MP4 audio OK (%s): %s", ",".join(codecs) or "no audio", path.name)
        return False

    log.info("Converting MP4 audio %s -> AAC (video copied): %s", ",".join(codecs), path.name)
    tmp = path.with_name(path.stem + ".aacfix.tmp.mp4")
    args = [
        str(ffmpeg),
        "-hide_banner", "-nostdin", "-y",
        "-i", str(path),
        "-map", "0:v?", "-map", "0:a?",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AAC_BITRATE,
        "-movflags", "+faststart",
        str(tmp),
    ]  # fmt: skip
    try:
        result = runner(args, cancel_event)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed ({result.returncode}): {result.stderr.strip()}")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return True
