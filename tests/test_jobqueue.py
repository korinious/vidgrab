from pathlib import Path

import pytest

from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.jobqueue import DownloadQueue, InvalidTransition
from vidgrab.core.models import DownloadRequest, JobStatus, Phase, Progress, Quality


def req(n: int = 1) -> DownloadRequest:
    return DownloadRequest(f"https://youtu.be/{n}", Quality.BEST, Path("out"))


def test_default_concurrency_is_two():
    q = DownloadQueue()
    jobs = [q.add(req(i)) for i in range(4)]
    started = q.start_next()
    assert [j.id for j in started] == [jobs[0].id, jobs[1].id]
    assert all(j.status is JobStatus.DOWNLOADING and j.attempts == 1 for j in started)
    assert q.start_next() == []
    assert q.active_count == 2


def test_finishing_frees_a_slot_fifo():
    q = DownloadQueue()
    a, _b, c = (q.add(req(i)) for i in range(3))
    q.start_next()
    q.mark_completed(a.id, Path("out/a.mp4"))
    assert a.status is JobStatus.COMPLETED and a.output_path == Path("out/a.mp4")
    assert q.start_next() == [c]


def test_max_concurrent_is_clamped():
    q = DownloadQueue(max_concurrent=99)
    assert q.max_concurrent == 5
    q.max_concurrent = 0
    assert q.max_concurrent == 1


def test_progress_updates_status():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.update_progress(job.id, Progress(downloaded_bytes=1, total_bytes=2))
    assert job.progress.stream_fraction == 0.5
    q.update_progress(job.id, Progress(phase=Phase.POSTPROCESSING))
    assert job.status is JobStatus.POSTPROCESSING


def test_progress_ignored_after_cancel():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    assert q.cancel(job.id) is True
    q.update_progress(job.id, Progress(downloaded_bytes=1, total_bytes=2))
    assert job.status is JobStatus.CANCELLING
    assert job.progress is None


def test_cancel_queued_job_needs_no_signal():
    q = DownloadQueue(max_concurrent=1)
    q.add(req(1))
    queued = q.add(req(2))
    q.start_next()
    assert q.cancel(queued.id) is False
    assert queued.status is JobStatus.CANCELLED
    assert q.cancel(queued.id) is False  # idempotent


def test_cancelling_job_counts_as_active_until_worker_reports():
    q = DownloadQueue(max_concurrent=1)
    running = q.add(req(1))
    waiting = q.add(req(2))
    q.start_next()
    q.cancel(running.id)
    assert q.start_next() == []
    q.mark_failed(running.id, UserError(ErrorKind.CANCELLED))
    assert running.status is JobStatus.CANCELLED
    assert running.error is None
    assert q.start_next() == [waiting]


def test_cancel_race_with_completion_keeps_file():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.cancel(job.id)
    q.mark_completed(job.id, Path("out/x.mp4"))
    assert job.status is JobStatus.COMPLETED


def test_cancel_race_with_failure_counts_as_cancel():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.cancel(job.id)
    q.mark_failed(job.id, UserError(ErrorKind.NETWORK))
    assert job.status is JobStatus.CANCELLED


def test_fail_then_retry():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.mark_failed(job.id, UserError(ErrorKind.NETWORK))
    assert job.status is JobStatus.FAILED and job.error.kind is ErrorKind.NETWORK
    assert job.can_retry
    q.retry(job.id)
    assert job.status is JobStatus.QUEUED and job.error is None
    q.start_next()
    assert job.attempts == 2


def test_retry_cancelled():
    q = DownloadQueue()
    job = q.add(req())
    q.cancel(job.id)
    q.retry(job.id)
    assert job.status is JobStatus.QUEUED


def test_non_retryable_errors():
    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.mark_failed(job.id, UserError(ErrorKind.UNSUPPORTED_URL))
    assert not job.can_retry
    with pytest.raises(InvalidTransition):
        q.retry(job.id)


def test_invalid_transitions():
    q = DownloadQueue()
    job = q.add(req())
    with pytest.raises(InvalidTransition):
        q.mark_completed(job.id, None)
    with pytest.raises(InvalidTransition):
        q.mark_failed(job.id, UserError(ErrorKind.UNKNOWN))
    with pytest.raises(InvalidTransition):
        q.remove(job.id)
    with pytest.raises(InvalidTransition):
        q.retry(job.id)


def test_remove_and_clear_finished():
    q = DownloadQueue(max_concurrent=3)
    done, failed, cancelled = (q.add(req(i)) for i in range(3))
    queued = q.add(req(4))
    q.start_next()
    q.mark_completed(done.id, None)
    q.mark_failed(failed.id, UserError(ErrorKind.NETWORK))
    q.cancel(cancelled.id)
    q.mark_failed(cancelled.id, UserError(ErrorKind.CANCELLED))
    assert sorted(q.clear_finished()) == sorted([done.id, cancelled.id])
    assert [j.id for j in q.jobs] == [failed.id, queued.id]
    q.remove(failed.id)
    assert [j.id for j in q.jobs] == [queued.id]


def test_result_is_kept_on_completion_and_cleared_on_retry():
    from vidgrab.core.models import DownloadResult

    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    result = DownloadResult(Path("out/v.mp4"), 2160, 1080)
    q.mark_completed(job.id, result.path, result)
    assert job.result is result
    job.status = JobStatus.CANCELLED  # e.g. a later cancel; retry must clear old results
    q.retry(job.id)
    assert job.result is None


def test_retry_full_quality():
    from vidgrab.core.models import DownloadResult, UpgradeTarget

    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    with pytest.raises(InvalidTransition):
        q.retry_full_quality(job.id)  # still downloading
    q.mark_completed(job.id, Path("out/v.mp4"), DownloadResult(Path("out/v.mp4"), 2160, 1080))
    assert job.can_upgrade
    q.retry_full_quality(job.id)
    assert job.status is JobStatus.QUEUED
    assert job.upgrade_target == UpgradeTarget(Path("out/v.mp4"), 1080, 2160)
    q.start_next()
    q.mark_completed(job.id, Path("out/v.mp4"), DownloadResult(Path("out/v.mp4"), 2160, 2160))
    assert job.upgrade_target is None
    assert not job.can_upgrade  # full quality now: no button


def test_no_full_quality_retry_without_downgrade():
    from vidgrab.core.models import DownloadResult

    q = DownloadQueue()
    job = q.add(req())
    q.start_next()
    q.mark_completed(job.id, Path("out/v.mp4"), DownloadResult(Path("out/v.mp4"), 1080, 1080))
    assert not job.can_upgrade
    with pytest.raises(InvalidTransition):
        q.retry_full_quality(job.id)
