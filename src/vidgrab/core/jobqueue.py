"""Download queue state machine.

Pure bookkeeping: it decides which jobs should run and tracks their state, but never
starts threads itself. The UI owns one instance and calls it only from the GUI thread.

Jobs from a list belong to a ``JobGroup`` (one card header in the queue). The
concurrency limit is global. Starts from the same platform are spaced by a random
2-5 s (``Cooldown``) to get fewer 403/429 responses when a whole list is queued.
"""

from __future__ import annotations

import itertools
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

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
    group_id: int | None = None

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


@dataclass
class JobGroup:
    """The videos of one list, shown under a single header card in the queue."""

    id: int
    title: str
    platform: str | None = None
    skipped: int = 0  # entries left out because they were already downloaded


@dataclass(frozen=True)
class GroupProgress:
    done: int  # completed
    total: int
    failed: int
    active: int  # queued or running

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


@dataclass(frozen=True)
class Cooldown:
    """Random pause between two download starts from the same platform."""

    min_s: float = 2.0
    max_s: float = 5.0
    clock: Callable[[], float] = time.monotonic
    rng: Callable[[float, float], float] = random.uniform


DEFAULT_COOLDOWN = Cooldown()


def platform_key(url: str) -> str:
    """'https://www.youtube.com/watch?v=1' -> 'youtube'; youtu.be counts as YouTube too."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com"):
        return "youtube"
    if host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com")):
        return "x"
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


class InvalidTransition(Exception):
    pass


class DownloadQueue:
    def __init__(
        self, max_concurrent: int = DEFAULT_CONCURRENT, cooldown: Cooldown | None = None
    ) -> None:
        self._jobs: dict[int, DownloadJob] = {}
        self._groups: dict[int, JobGroup] = {}
        self._ids = itertools.count(1)
        self._group_ids = itertools.count(1)
        self.max_concurrent = max_concurrent
        self.cooldown = cooldown or DEFAULT_COOLDOWN
        self._next_start: dict[str, float] = {}  # platform -> earliest next start

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

    @property
    def groups(self) -> list[JobGroup]:
        return list(self._groups.values())

    def group(self, group_id: int) -> JobGroup:
        return self._groups[group_id]

    def group_jobs(self, group_id: int) -> list[DownloadJob]:
        return [j for j in self._jobs.values() if j.group_id == group_id]

    def group_progress(self, group_id: int) -> GroupProgress:
        jobs = self.group_jobs(group_id)
        return GroupProgress(
            done=sum(1 for j in jobs if j.status is JobStatus.COMPLETED),
            total=len(jobs),
            failed=sum(1 for j in jobs if j.status is JobStatus.FAILED),
            active=sum(1 for j in jobs if j.status is JobStatus.QUEUED or j.status.is_active),
        )

    def seconds_until_next_start(self) -> float | None:
        """When a queued job held back only by the platform cooldown may start; None if no
        job is waiting for that (nothing queued, or every slot is busy)."""
        if self.active_count >= self.max_concurrent:
            return None
        now = self.cooldown.clock()
        waits = [
            self._next_start.get(platform_key(j.request.url), 0.0) - now
            for j in self._jobs.values()
            if j.status is JobStatus.QUEUED
        ]
        return max(0.0, min(waits)) if waits else None

    # --- transitions -----------------------------------------------------------------
    def add(
        self,
        request: DownloadRequest,
        thumbnail_url: str | None = None,
        group_id: int | None = None,
    ) -> DownloadJob:
        if group_id is not None and group_id not in self._groups:
            raise KeyError(f"no group {group_id}")
        job = DownloadJob(
            id=next(self._ids), request=request, thumbnail_url=thumbnail_url, group_id=group_id
        )
        self._jobs[job.id] = job
        return job

    def add_group(self, title: str, platform: str | None = None, skipped: int = 0) -> JobGroup:
        group = JobGroup(next(self._group_ids), title, platform, skipped)
        self._groups[group.id] = group
        return group

    def start_next(self) -> list[DownloadJob]:
        """Mark as many queued jobs as allowed as DOWNLOADING and return them (FIFO).

        A job whose platform started a download less than the cooldown ago waits; jobs from
        other platforms behind it may go first.
        """
        free = self.max_concurrent - self.active_count
        started: list[DownloadJob] = []
        now = self.cooldown.clock()
        for job in self._jobs.values():
            if free <= 0:
                break
            if job.status is not JobStatus.QUEUED:
                continue
            platform = platform_key(job.request.url)
            if self._next_start.get(platform, 0.0) > now:
                continue
            delay = self.cooldown.rng(self.cooldown.min_s, self.cooldown.max_s)
            self._next_start[platform] = now + max(0.0, delay)
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

    def cancel_group(self, group_id: int) -> list[int]:
        """ "Ακύρωση όλων": cancel every queued or running job of a list. Returns the ids
        whose running worker must be signalled."""
        return [j.id for j in self.group_jobs(group_id) if self.cancel(j.id)]

    def retry_failed(self, group_id: int) -> list[int]:
        """ "Επανάληψη αποτυχημένων": queue again the failed (retryable) jobs of a list."""
        retried = []
        for job in self.group_jobs(group_id):
            if job.status is JobStatus.FAILED and job.can_retry:
                self.retry(job.id)
                retried.append(job.id)
        return retried

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

    def drop_empty_groups(self) -> list[int]:
        """Forget groups whose jobs were all removed. Returns their ids."""
        used = {j.group_id for j in self._jobs.values()}
        empty = [gid for gid in self._groups if gid not in used]
        for gid in empty:
            del self._groups[gid]
        return empty
