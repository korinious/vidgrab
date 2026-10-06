"""Run a single download with progress reporting and cooperative cancellation."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yt_dlp.utils import DownloadCancelled

from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import ErrorKind, UserError, classify
from vidgrab.core.formats import format_options
from vidgrab.core.models import DownloadRequest, Phase, Progress
from vidgrab.core.options import OUTPUT_TEMPLATE, YdlFactory, base_options, default_ydl_factory

log = logging.getLogger(__name__)

ProgressCallback = Callable[[Progress], None]

# Leftovers yt-dlp may create next to a file it is writing.
_PARTIAL_SUFFIXES = (".part", ".ytdl")


class _Tracker:
    """Collects state from yt-dlp hooks during one download."""

    def __init__(self, on_progress: ProgressCallback, cancel_event: threading.Event) -> None:
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        self.streams: list[str] = []  # files we actually started writing, in order
        self.final_path: str | None = None

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled()

    def progress_hook(self, d: dict[str, Any]) -> None:
        self.check_cancel()
        if d.get("status") != "downloading":
            return
        filename = d.get("filename")
        if filename and filename not in self.streams:
            self.streams.append(filename)
        info = d.get("info_dict") or {}
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

    def cleanup_partials(self) -> None:
        """Remove files left by an interrupted download.

        Only files this run started writing are touched, so an already complete file
        with the same name (which yt-dlp skips) is never deleted.
        """
        for stream in self.streams:
            for candidate in (stream, *(stream + s for s in _PARTIAL_SUFFIXES)):
                path = Path(candidate)
                try:
                    if path.is_file():
                        path.unlink()
                        log.info("Removed partial file %s", path)
                except OSError:
                    log.warning("Could not remove partial file %s", path, exc_info=True)


def _final_path(info: Any, tracker: _Tracker) -> Path | None:
    if tracker.final_path:
        return Path(tracker.final_path)
    if isinstance(info, dict):
        for entry in reversed(info.get("requested_downloads") or []):
            if entry.get("filepath"):
                return Path(entry["filepath"])
        if info.get("filepath"):
            return Path(info["filepath"])
    return Path(tracker.streams[-1]) if tracker.streams else None


def download(
    request: DownloadRequest,
    binaries: Binaries,
    on_progress: ProgressCallback,
    cancel_event: threading.Event,
    ydl_factory: YdlFactory = default_ydl_factory,
) -> Path | None:
    """Download one video. Returns the final file path (if known). Raises UserError."""
    tracker = _Tracker(on_progress, cancel_event)
    log.info(
        "Starting download %s (quality=%s) -> %s", request.url, request.quality, request.output_dir
    )
    try:
        tracker.check_cancel()
        request.output_dir.mkdir(parents=True, exist_ok=True)
        opts = base_options(binaries, request.cookies)
        opts.update(format_options(request.quality))
        opts.update(
            {
                "outtmpl": {"default": str(request.output_dir / OUTPUT_TEMPLATE)},
                "progress_hooks": [tracker.progress_hook],
                "postprocessor_hooks": [tracker.postprocessor_hook],
            }
        )
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(request.url, download=True)
    except Exception as exc:
        err = UserError(ErrorKind.CANCELLED) if cancel_event.is_set() else classify(exc)
        if err.kind is ErrorKind.CANCELLED:
            log.info("Download cancelled: %s", request.url)
            tracker.cleanup_partials()
        else:
            log.error(
                "Download failed for %s: %s (%s)",
                request.url,
                err.kind,
                err.detail,
                exc_info=err.kind is ErrorKind.UNKNOWN,
            )
        raise err from exc

    path = _final_path(info, tracker)
    log.info("Download finished: %s -> %s", request.url, path)
    return path
