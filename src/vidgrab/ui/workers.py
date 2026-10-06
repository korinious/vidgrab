"""QThread wrappers around core calls. They only translate callbacks into signals."""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal

from vidgrab.core.binaries import Binaries
from vidgrab.core.downloader import download
from vidgrab.core.errors import UserError, classify
from vidgrab.core.extractor import fetch_info
from vidgrab.core.models import CookieConfig, DownloadRequest, Progress
from vidgrab.core.options import YdlFactory, default_ydl_factory

log = logging.getLogger(__name__)

PROGRESS_INTERVAL_S = 0.1  # max ~10 UI updates per second per download


class MetadataWorker(QThread):
    succeeded = Signal(object)  # VideoInfo
    failed = Signal(object)  # UserError

    def __init__(
        self,
        url: str,
        binaries: Binaries,
        cookies: CookieConfig,
        ydl_factory: YdlFactory = default_ydl_factory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self._binaries = binaries
        self._cookies = cookies
        self._ydl_factory = ydl_factory

    def run(self) -> None:
        try:
            info = fetch_info(self.url, self._binaries, self._cookies, self._ydl_factory)
        except Exception as exc:
            self.failed.emit(classify(exc))
        else:
            self.succeeded.emit(info)


class DownloadWorker(QThread):
    progressed = Signal(int, object)  # job id, Progress
    completed = Signal(int, object)  # job id, Path | None
    failed = Signal(int, object)  # job id, UserError

    def __init__(
        self,
        job_id: int,
        request: DownloadRequest,
        binaries: Binaries,
        ydl_factory: YdlFactory = default_ydl_factory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.job_id = job_id
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
            path = download(
                self._request,
                self._binaries,
                self._on_progress,
                self._cancel_event,
                self._ydl_factory,
                job_id=self.job_id,
            )
        except UserError as err:
            self.failed.emit(self.job_id, err)
        except Exception as exc:  # defensive: download() already classifies
            log.exception("Unexpected error in download worker")
            self.failed.emit(self.job_id, classify(exc))
        else:
            self.completed.emit(self.job_id, path)
