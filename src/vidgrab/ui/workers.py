"""QThread wrappers around core calls. They only translate callbacks into signals."""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal

from vidgrab.core.binaries import Binaries
from vidgrab.core.downloader import download
from vidgrab.core.errors import UserError, classify
from vidgrab.core.extractor import fetch_listing, probe
from vidgrab.core.models import CookieConfig, DownloadRequest, Progress, UpgradeTarget
from vidgrab.core.options import YdlFactory, default_ydl_factory

log = logging.getLogger(__name__)

PROGRESS_INTERVAL_S = 0.1  # max ~10 UI updates per second per download


class MetadataWorker(QThread):
    """What a link points at: ``probe()`` (VideoInfo or Listing), or with ``listing=True``
    the whole list ("Όλη η λίστα" on a video inside a list)."""

    succeeded = Signal(object)  # VideoInfo | Listing
    failed = Signal(object)  # UserError

    def __init__(
        self,
        url: str,
        binaries: Binaries,
        cookies: CookieConfig,
        ydl_factory: YdlFactory = default_ydl_factory,
        parent: QObject | None = None,
        *,
        listing: bool = False,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.listing = listing
        self._binaries = binaries
        self._cookies = cookies
        self._ydl_factory = ydl_factory

    def run(self) -> None:
        try:
            fetch = fetch_listing if self.listing else probe
            info = fetch(self.url, self._binaries, self._cookies, self._ydl_factory)
        except Exception as exc:
            self.failed.emit(classify(exc))
        else:
            self.succeeded.emit(info)


class DownloadWorker(QThread):
    progressed = Signal(int, object)  # job id, Progress
    completed = Signal(int, object)  # job id, DownloadResult
    failed = Signal(int, object)  # job id, UserError

    def __init__(
        self,
        job_id: int,
        request: DownloadRequest,
        binaries: Binaries,
        ydl_factory: YdlFactory = default_ydl_factory,
        parent: QObject | None = None,
        upgrade: UpgradeTarget | None = None,
    ) -> None:
        super().__init__(parent)
        self.job_id = job_id
        self._upgrade = upgrade
        self._request = request
        self._binaries = binaries
        self._ydl_factory = ydl_factory
        self._cancel_event = threading.Event()
        self._last_emit = 0.0
        self._last_phase: object = None

    def cancel(self) -> None:
        self._cancel_event.set()

    def _on_progress(self, progress: Progress) -> None:
        now = time.monotonic()
        if progress.phase == self._last_phase and now - self._last_emit < PROGRESS_INTERVAL_S:
            return
        self._last_emit = now
        self._last_phase = progress.phase
        self.progressed.emit(self.job_id, progress)

    def run(self) -> None:
        try:
            result = download(
                self._request,
                self._binaries,
                self._on_progress,
                self._cancel_event,
                self._ydl_factory,
                job_id=self.job_id,
                upgrade=self._upgrade,
            )
        except UserError as err:
            self.failed.emit(self.job_id, err)
        except Exception as exc:  # defensive: download() already classifies
            log.exception("Unexpected error in download worker")
            self.failed.emit(self.job_id, classify(exc))
        else:
            self.completed.emit(self.job_id, result)


def _tool_version(path, args: list[str], pattern: str) -> str | None:
    """First regex group from ``path args`` output, or None. Never raises."""
    import os
    import re
    import subprocess

    if path is None:
        return None
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # no console flash
    try:
        out = subprocess.run(
            [str(path), *args], capture_output=True, text=True, timeout=10, check=False,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", **kwargs,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(pattern, out or "")
    return match.group(1) if match else None


class VersionsWorker(QThread):
    """Reads the yt-dlp, FFmpeg and Deno versions for the footer, off the GUI thread."""

    ready = Signal(object)  # dict[str, str | None]

    def __init__(self, binaries: Binaries, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._binaries = binaries

    def run(self) -> None:
        from vidgrab.core.binaries import component_versions

        versions = {
            "yt-dlp": component_versions().get("yt-dlp"),
            # "ffmpeg version 8.0-essentials_build-www.gyan.dev" -> "8.0"
            "ffmpeg": _tool_version(self._binaries.ffmpeg, ["-version"], r"version\s+n?([\d.]+)"),
            # "deno 2.9.6 (stable, release, ...)" -> "2.9.6"
            "deno": _tool_version(self._binaries.deno, ["--version"], r"deno\s+([\d.]+)"),
        }
        self.ready.emit(versions)
