"""Run a single download: staging folder, 403 retries, post-processing, final move.

Flow for one job:
1. yt-dlp downloads, merges and post-processes inside a private staging folder
   (``core/staging.py``), never in the destination folder, which may be synced by
   OneDrive or scanned by antivirus.
2. On HTTP 403 the whole ``extract_info`` is repeated (fresh URLs), up to
   ``RetryPolicy.forbidden_retries`` times. The last retry also switches YouTube
   player clients and excludes the format whose URL was refused.
3. MP4 audio is fixed if needed (``core/audiofix.py``).
4. The finished file is moved to the destination with lock retries and without ever
   overwriting an existing file. The staging folder is always removed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from yt_dlp.utils import DownloadCancelled

from vidgrab import strings
from vidgrab.core.audiofix import CommandRunner, ensure_mp4_audio, run_command
from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import ErrorKind, UserError, classify
from vidgrab.core.formats import (
    actual_height,
    exclude_format_ids,
    format_options,
    requested_height,
    video_height,
)
from vidgrab.core.models import (
    DownloadRequest,
    DownloadResult,
    Phase,
    Progress,
    Quality,
    VideoContainer,
)
from vidgrab.core.options import OUTPUT_TEMPLATE, YdlFactory, base_options, default_ydl_factory
from vidgrab.core.staging import MOVE_BACKOFF_S, move_to_destination, staging_dir

log = logging.getLogger(__name__)

ProgressCallback = Callable[[Progress], None]

# For the last 403 retry on YouTube: yt-dlp's default clients without "visionos" (the
# client whose URLs were refused in the reported case), plus "tv_downgraded" and
# "web_embedded", which the yt-dlp README documents as the fallbacks it uses itself when
# visionos cannot access a video. "default" keeps the right set for logged-in users.
YOUTUBE_FALLBACK_CLIENTS = ["default", "-visionos", "tv_downgraded", "web_embedded"]


@dataclass(frozen=True)
class RetryPolicy:
    forbidden_retries: int = 2  # extra full extract_info attempts after an HTTP 403
    forbidden_delays: Sequence[float] = (2.0, 5.0)  # wait before retry 1, 2 (cancellable)
    move_backoff: Sequence[float] = field(default=MOVE_BACKOFF_S)  # final move, WinError 32
    sleep: Callable[[float], None] = time.sleep


DEFAULT_POLICY = RetryPolicy()


class _Tracker:
    """Collects state from yt-dlp hooks during one download attempt."""

    def __init__(self, on_progress: ProgressCallback, cancel_event: threading.Event) -> None:
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        # Video heights any attempt started downloading (kept across 403 retries).
        self.attempted_heights: list[int] = []
        self.reset()

    def reset(self) -> None:
        self.streams: list[str] = []  # files this attempt started writing, in order
        self.final_path: str | None = None
        self.current_format_id: str | None = None

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled()

    def progress_hook(self, d: dict[str, Any]) -> None:
        self.check_cancel()
        if d.get("status") != "downloading":
            return
        info = d.get("info_dict") or {}
        if info.get("format_id"):
            self.current_format_id = str(info["format_id"])
        if (height := video_height(info)) and height not in self.attempted_heights:
            self.attempted_heights.append(height)
        filename = d.get("filename")
        if filename and filename not in self.streams:
            self.streams.append(filename)
        stream_count = max(len(info.get("requested_formats") or ()), 1, len(self.streams))
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        self.on_progress(
            Progress(
                phase=Phase.DOWNLOADING,
                downloaded_bytes=int(d.get("downloaded_bytes") or 0),
                total_bytes=int(total) if total else None,
                speed=d.get("speed"),
                eta=int(d["eta"]) if d.get("eta") is not None else None,
                stream_index=max(1, len(self.streams)),
                stream_count=stream_count,
            )
        )

    def postprocessor_hook(self, d: dict[str, Any]) -> None:
        self.check_cancel()
        status = d.get("status")
        if status == "started":
            self.on_progress(Progress(phase=Phase.POSTPROCESSING))
        elif status == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                self.final_path = path


def _final_path(info: Any, tracker: _Tracker) -> Path | None:
    candidates: list[str] = []
    if tracker.final_path:
        candidates.append(tracker.final_path)
    if isinstance(info, dict):
        candidates += [
            e["filepath"]
            for e in reversed(info.get("requested_downloads") or [])
            if e.get("filepath")
        ]
        if info.get("filepath"):
            candidates.append(info["filepath"])
    candidates += reversed(tracker.streams)
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def _wants_mp4_audio_check(request: DownloadRequest) -> bool:
    quality, container = Quality(request.quality), VideoContainer(request.container)
    return not quality.is_audio and container is VideoContainer.MP4


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def _build_options(
    request: DownloadRequest, binaries: Binaries, tracker: _Tracker, stage: Path
) -> dict[str, Any]:
    opts = base_options(binaries, request.cookies)
    opts.update(
        format_options(
            request.quality, request.container, request.audio_format, request.mp3_bitrate
        )
    )
    opts.update(
        {
            "outtmpl": {"default": str(stage / OUTPUT_TEMPLATE)},
            "progress_hooks": [tracker.progress_hook],
            "postprocessor_hooks": [tracker.postprocessor_hook],
        }
    )
    return opts


def _apply_forbidden_fallback(
    opts: dict[str, Any], url: str, failed_format_ids: Sequence[str]
) -> list[str]:
    """Adjust options for the last attempt after repeated 403s. Returns what changed."""
    changes: list[str] = []
    if is_youtube_url(url):
        extractor_args = dict(opts.get("extractor_args") or {})
        youtube = dict(extractor_args.get("youtube") or {})
        youtube["player_client"] = list(YOUTUBE_FALLBACK_CLIENTS)
        extractor_args["youtube"] = youtube
        opts["extractor_args"] = extractor_args
        changes.append("player_client=" + ",".join(YOUTUBE_FALLBACK_CLIENTS))
    if failed_format_ids:
        opts["format"] = exclude_format_ids(opts["format"], failed_format_ids)
        changes.append("excluding format(s) " + ",".join(dict.fromkeys(failed_format_ids)))
    return changes


def _extract_with_retries(
    request: DownloadRequest,
    binaries: Binaries,
    tracker: _Tracker,
    stage: Path,
    ydl_factory: YdlFactory,
    policy: RetryPolicy,
) -> Any:
    attempts = policy.forbidden_retries + 1
    failed_format_ids: list[str] = []
    for attempt in range(1, attempts + 1):
        tracker.reset()
        opts = _build_options(request, binaries, tracker, stage)
        if attempt > 1 and attempt == attempts:
            changes = _apply_forbidden_fallback(opts, request.url, failed_format_ids)
            log.warning("403 fallback for %s: %s", request.url, "; ".join(changes) or "none")
        log.info("Download attempt %d/%d: %s", attempt, attempts, request.url)
        try:
            # A new YoutubeDL each attempt: extract_info runs again and gets fresh URLs.
            with ydl_factory(opts) as ydl:
                return ydl.extract_info(request.url, download=True)
        except Exception as exc:
            if tracker.cancel_event.is_set():
                raise
            err = classify(exc)
            if err.kind is not ErrorKind.FORBIDDEN or attempt == attempts:
                raise
            if tracker.current_format_id:
                failed_format_ids.append(tracker.current_format_id)
            delay = policy.forbidden_delays[min(attempt, len(policy.forbidden_delays)) - 1]
            log.warning(
                "HTTP 403 on attempt %d/%d for %s (format %s): %s; retrying with a fresh "
                "extract_info in %.1fs",
                attempt,
                attempts,
                request.url,
                tracker.current_format_id or "unknown",
                err.detail,
                delay,
            )
            if tracker.cancel_event.wait(delay):
                raise DownloadCancelled() from exc
    raise AssertionError("unreachable")


def download(
    request: DownloadRequest,
    binaries: Binaries,
    on_progress: ProgressCallback,
    cancel_event: threading.Event,
    ydl_factory: YdlFactory = default_ydl_factory,
    runner: CommandRunner = run_command,
    *,
    job_id: int | None = None,
    staging_root: Path | None = None,
    policy: RetryPolicy | None = None,
) -> DownloadResult:
    """Download one video into ``request.output_dir``.

    Returns the final path plus the requested and actual video height, so the UI can flag
    a lower resolution than asked for (e.g. after the 403 fallback).

    Raises UserError. Every call does a full, fresh ``extract_info``; nothing is cached,
    so a retry from the UI always gets new URLs.
    """
    policy = policy or DEFAULT_POLICY
    tracker = _Tracker(on_progress, cancel_event)
    log.info(
        "Starting download %s (job=%s, quality=%s, container=%s, audio=%s, mp3=%dk) -> %s",
        request.url,
        job_id,
        request.quality,
        request.container,
        request.audio_format,
        request.mp3_bitrate,
        request.output_dir,
    )
    try:
        tracker.check_cancel()
        if not request.output_dir.is_absolute():
            # A relative dir would silently resolve against the current working directory.
            raise UserError(
                ErrorKind.DISK, detail=f"output dir is not absolute: {request.output_dir}"
            )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        with staging_dir(staging_root, job_id) as stage:
            info = _extract_with_retries(request, binaries, tracker, stage, ydl_factory, policy)
            staged = _final_path(info, tracker)
            if staged is None:
                log.warning("yt-dlp reported no output file for %s", request.url)
                return DownloadResult(None)
            if _wants_mp4_audio_check(request):
                tracker.check_cancel()
                on_progress(Progress(phase=Phase.POSTPROCESSING))
                ensure_mp4_audio(staged, binaries, cancel_event, runner)
            tracker.check_cancel()
            path = move_to_destination(
                staged, request.output_dir, sleep=policy.sleep, backoff=policy.move_backoff
            )
    except Exception as exc:
        err = UserError(ErrorKind.CANCELLED) if cancel_event.is_set() else classify(exc)
        if err.kind is ErrorKind.FORBIDDEN and not is_youtube_url(request.url):
            err = UserError(ErrorKind.FORBIDDEN, strings.ERR_FORBIDDEN_OTHER_SITE, err.detail)
        if err.kind is ErrorKind.CANCELLED:
            log.info("Download cancelled: %s", request.url)
        else:
            log.error(
                "Download failed for %s: %s (%s)",
                request.url,
                err.kind,
                err.detail,
                exc_info=err.kind is ErrorKind.UNKNOWN,
            )
        raise err from exc

    result = DownloadResult(
        path,
        requested_height=requested_height(request.quality, info, tracker.attempted_heights),
        actual_height=actual_height(info),
    )
    if result.downgraded:
        log.warning(
            "Lower resolution than requested for %s: got %sp, wanted %sp",
            request.url,
            result.actual_height,
            result.requested_height,
        )
    log.info("Download finished: %s -> %s", request.url, path)
    return result
