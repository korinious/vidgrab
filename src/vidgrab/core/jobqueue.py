"""Download queue state machine.

Pure bookkeeping: it decides which jobs should run and tracks their state, but never
starts threads itself. The UI owns one instance and calls it only from the GUI thread.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.models import (
    DownloadRequest,
    DownloadResult,
    JobStatus,
    Phase,
    Progress,
    UpgradeTarget,
)
from vidgrab.core.settings import DEFAULT_CONCURRENT, MAX_CONCURRENT, MIN_CONCURRENT


@dataclass
class DownloadJob:
    id: int
    request: DownloadRequest
    status: JobStatus = JobStatus.QUEUED
    progress: Progress | None = None
    error: UserError | None = None
    output_path: Path | None = None
    result: DownloadResult | None = None  # set when completed (resolution check etc.)
    # Set by "Ξανά σε πλήρη ποιότητα": the existing file the next run may replace.
    upgrade_target: UpgradeTarget | None = None
    attempts: int = 0
    thumbnail_url: str | None = field(default=None, compare=False)

    @property
    def can_cancel(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING)

    @property
    def can_upgrade(self) -> bool:
        """Completed below the requested resolution: offer "Ξανά σε πλήρη ποιότητα"."""
        r = self.result
        return (
            self.status is JobStatus.COMPLETED
            and r is not None
            and r.downgraded
            and r.actual_height is not None
            and self.output_path is not None
        )

    @property
    def can_retry(self) -> bool:
        if self.status is JobStatus.CANCELLED:
            return True
        return self.status is JobStatus.FAILED and (self.error is None or self.error.retryable)


class InvalidTransition(Exception):
    pass


class DownloadQueue:
    def __init__(self, max_concurrent: int = DEFAULT_CONCURRENT) -> None:
        self._jobs: dict[int, DownloadJob] = {}
        self._ids = itertools.count(1)
        self.max_concurrent = max_concurrent

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        self._max_concurrent = max(MIN_CONCURRENT, min(MAX_CONCURRENT, int(value)))

    # --- queries ---------------------------------------------------------------------
    @property
    def jobs(self) -> list[DownloadJob]:
        return list(self._jobs.values())

    def get(self, job_id: int) -> DownloadJob:
        return self._jobs[job_id]

    @property
    def active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status.is_active)

    # --- transitions -----------------------------------------------------------------
    def add(self, request: DownloadRequest, thumbnail_url: str | None = None) -> DownloadJob:
        job = DownloadJob(id=next(self._ids), request=request, thumbnail_url=thumbnail_url)
        self._jobs[job.id] = job
        return job

    def start_next(self) -> list[DownloadJob]:
        """Mark as many queued jobs as allowed as DOWNLOADING and return them (FIFO)."""
        free = self.max_concurrent - self.active_count
        started: list[DownloadJob] = []
        for job in self._jobs.values():
            if free <= 0:
                break
            if job.status is JobStatus.QUEUED:
                job.status = JobStatus.DOWNLOADING
                job.attempts += 1
                job.progress = None
                started.append(job)
                free -= 1
        return started

    def update_progress(self, job_id: int, progress: Progress) -> None:
        job = self._jobs[job_id]
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING):
            return  # late update after cancel/finish; ignore
        job.progress = progress
        job.status = (
            JobStatus.POSTPROCESSING
            if progress.phase is Phase.POSTPROCESSING
            else JobStatus.DOWNLOADING
        )

    def mark_completed(
        self, job_id: int, output_path: Path | None, result: DownloadResult | None = None
    ) -> None:
        job = self._jobs[job_id]
        if job.status is JobStatus.CANCELLING:
            # Finished before the cancel request reached yt-dlp: the file is complete.
            pass
        elif not job.status.is_active:
            raise InvalidTransition(f"job {job_id} is {job.status}, cannot complete")
        job.status = JobStatus.COMPLETED
        job.output_path = output_path
        job.result = result
        job.upgrade_target = None
        job.error = None

    def mark_failed(self, job_id: int, error: UserError) -> None:
        job = self._jobs[job_id]
        if not job.status.is_active:
            raise InvalidTransition(f"job {job_id} is {job.status}, cannot fail")
        if error.kind is ErrorKind.CANCELLED or job.status is JobStatus.CANCELLING:
            job.status = JobStatus.CANCELLED
            job.error = None
        else:
            job.status = JobStatus.FAILED
            job.error = error

    def cancel(self, job_id: int) -> bool:
        """Request cancellation. Returns True if a running worker must be signalled."""
        job = self._jobs[job_id]
        if job.status is JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            return False
        if job.status in (JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING):
            job.status = JobStatus.CANCELLING
            return True
        return False

    def retry(self, job_id: int) -> None:
        job = self._jobs[job_id]
        if not job.can_retry:
            raise InvalidTransition(f"job {job_id} is {job.status}, cannot retry")
        job.status = JobStatus.QUEUED
        job.error = None
        job.progress = None
        job.output_path = None
        job.result = None

    def retry_full_quality(self, job_id: int) -> None:
        """Queue a new download that replaces the file only if its resolution is higher."""
        job = self._jobs[job_id]
        if not job.can_upgrade:
            raise InvalidTransition(f"job {job_id} has nothing to upgrade")
        assert job.result is not None and job.output_path is not None
        assert job.result.actual_height is not None
        job.upgrade_target = UpgradeTarget(
            job.output_path, job.result.actual_height, job.result.requested_height
        )
        job.status = JobStatus.QUEUED
        job.progress = None
        job.error = None

    def remove(self, job_id: int) -> None:
        job = self._jobs[job_id]
        if not job.status.is_finished:
            raise InvalidTransition(f"job {job_id} is {job.status}, cannot remove")
        del self._jobs[job_id]

    def clear_finished(self) -> list[int]:
        """Remove completed and cancelled jobs (failed ones stay for retry)."""
        removed = [
            j.id
            for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.CANCELLED)
        ]
        for job_id in removed:
            del self._jobs[job_id]
        return removed
