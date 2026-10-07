"""Glue between DownloadQueue (core) and DownloadWorker threads."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import UserError
from vidgrab.core.jobqueue import DownloadJob, DownloadQueue, JobGroup
from vidgrab.core.models import DownloadRequest, DownloadResult, Progress
from vidgrab.core.options import YdlFactory, default_ydl_factory
from vidgrab.ui.workers import DownloadWorker

log = logging.getLogger(__name__)


class DownloadController(QObject):
    job_added = Signal(object)  # DownloadJob
    job_changed = Signal(object)  # DownloadJob
    job_removed = Signal(int)  # job id
    group_added = Signal(object)  # JobGroup, emitted before its jobs' job_added
    group_removed = Signal(int)  # group id, once its last job is gone

    def __init__(
        self,
        binaries: Binaries,
        max_concurrent: int,
        ydl_factory: YdlFactory = default_ydl_factory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._binaries = binaries
        self._ydl_factory = ydl_factory
        self.queue = DownloadQueue(max_concurrent)
        self._workers: dict[int, DownloadWorker] = {}
        # Wakes the queue when a job held back by the per-platform pause may start.
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setSingleShot(True)
        self._cooldown_timer.timeout.connect(self._pump)

    # --- public API (GUI thread only) --------------------------------------------------
    def enqueue(self, request: DownloadRequest, thumbnail_url: str | None = None) -> DownloadJob:
        job = self.queue.add(request, thumbnail_url)
        log.info("Queued job %d: %s (%s)", job.id, request.url, request.quality)
        self.job_added.emit(job)
        self._pump()
        return job

    def enqueue_group(
        self,
        title: str,
        platform: str | None,
        items: list[tuple[DownloadRequest, str | None]],
        skipped: int = 0,
    ) -> tuple[JobGroup, list[DownloadJob]]:
        """Queue the chosen videos of a list as separate jobs under one group."""
        group = self.queue.add_group(title, platform, skipped)
        log.info("Queued list %r: %d videos (%d skipped)", title, len(items), skipped)
        self.group_added.emit(group)
        jobs = []
        for request, thumbnail_url in items:
            job = self.queue.add(request, thumbnail_url, group_id=group.id)
            jobs.append(job)
            self.job_added.emit(job)
        self._pump()
        return group, jobs

    def cancel_group(self, group_id: int) -> None:
        """ "Ακύρωση όλων" of a list."""
        for job_id in self.queue.cancel_group(group_id):
            if worker := self._workers.get(job_id):
                worker.cancel()
        for job in self.queue.group_jobs(group_id):
            self.job_changed.emit(job)
        self._pump()

    def retry_failed(self, group_id: int) -> None:
        """ "Επανάληψη αποτυχημένων" of a list."""
        for job_id in self.queue.retry_failed(group_id):
            self.job_changed.emit(self.queue.get(job_id))
        self._pump()

    def cancel(self, job_id: int) -> None:
        needs_signal = self.queue.cancel(job_id)
        if needs_signal and (worker := self._workers.get(job_id)):
            worker.cancel()
        self.job_changed.emit(self.queue.get(job_id))
        self._pump()

    def retry(self, job_id: int) -> None:
        self.queue.retry(job_id)
        self.job_changed.emit(self.queue.get(job_id))
        self._pump()

    def retry_full_quality(self, job_id: int) -> None:
        """New download with the same choices; replaces the file only if it is better."""
        self.queue.retry_full_quality(job_id)
        log.info("Full-quality retry queued for job %d", job_id)
        self.job_changed.emit(self.queue.get(job_id))
        self._pump()

    def remove(self, job_id: int) -> None:
        self.queue.remove(job_id)
        self.job_removed.emit(job_id)
        self._drop_empty_groups()

    def clear_finished(self) -> None:
        for job_id in self.queue.clear_finished():
            self.job_removed.emit(job_id)
        self._drop_empty_groups()

    def _drop_empty_groups(self) -> None:
        for group_id in self.queue.drop_empty_groups():
            self.group_removed.emit(group_id)

    def set_max_concurrent(self, value: int) -> None:
        self.queue.max_concurrent = value
        self._pump()

    @property
    def has_active(self) -> bool:
        return bool(self._workers) or self.queue.active_count > 0

    def shutdown(self, timeout_ms: int = 10_000) -> None:
        """Cancel everything and wait for worker threads to stop."""
        self._cooldown_timer.stop()
        for job in self.queue.jobs:
            if job.can_cancel:
                self.queue.cancel(job.id)
        for worker in list(self._workers.values()):
            worker.cancel()
        for worker in list(self._workers.values()):
            if not worker.wait(timeout_ms):
                log.warning("Worker for job %d did not stop in time", worker.job_id)

    # --- internals ---------------------------------------------------------------------
    def _pump(self) -> None:
        for job in self.queue.start_next():
            worker = DownloadWorker(
                job.id,
                job.request,
                self._binaries,
                self._ydl_factory,
                self,
                upgrade=job.upgrade_target,
            )
            worker.progressed.connect(self._on_progress)
            worker.completed.connect(self._on_completed)
            worker.failed.connect(self._on_failed)
            worker.finished.connect(lambda w=worker: self._on_thread_finished(w))
            self._workers[job.id] = worker
            self.job_changed.emit(job)
            worker.start()
        wait = self.queue.seconds_until_next_start()
        if wait is not None and wait > 0:
            self._cooldown_timer.start(int(wait * 1000) + 50)

    def _on_progress(self, job_id: int, progress: Progress) -> None:
        self.queue.update_progress(job_id, progress)
        self.job_changed.emit(self.queue.get(job_id))

    def _on_completed(self, job_id: int, result: DownloadResult) -> None:
        self.queue.mark_completed(job_id, result.path, result)
        self.job_changed.emit(self.queue.get(job_id))

    def _on_failed(self, job_id: int, error: UserError) -> None:
        self.queue.mark_failed(job_id, error)
        self.job_changed.emit(self.queue.get(job_id))

    def _on_thread_finished(self, worker: DownloadWorker) -> None:
        if self._workers.get(worker.job_id) is worker:
            del self._workers[worker.job_id]
        worker.deleteLater()
        self._pump()
