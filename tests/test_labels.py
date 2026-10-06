from pathlib import Path

import pytest

from vidgrab import strings
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import DownloadRequest, JobStatus, Progress, Quality
from vidgrab.ui.labels import (
    QUALITY_LABELS,
    QUALITY_ORDER,
    STATUS_LABELS,
    format_bytes,
    format_eta,
    format_speed,
    job_status_text,
    progress_text,
)


def test_every_enum_has_a_label():
    assert set(QUALITY_LABELS) == set(Quality) == set(QUALITY_ORDER)
    assert set(STATUS_LABELS) == set(JobStatus)


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (None, strings.UNKNOWN_VALUE),
        (0, "0 B"),
        (1023, "1023 B"),
        (1536, "1.5 KB"),
        (5 * 1024**3, "5.0 GB"),
    ],
)
def test_format_bytes(n, text):
    assert format_bytes(n) == text


def test_format_speed_and_eta():
    assert format_speed(None) == strings.UNKNOWN_VALUE
    assert format_speed(2048) == "2.0 KB/s"
    assert format_eta(None) == strings.UNKNOWN_VALUE
    assert format_eta(75) == "1:15"
    assert format_eta(3675) == "1:01:15"


def test_progress_text_with_streams():
    text = progress_text(
        Progress(
            downloaded_bytes=50, total_bytes=100, speed=1024, eta=3, stream_index=1, stream_count=2
        )
    )
    assert "25%" in text and "1.0 KB/s" in text and "0:03" in text
    assert strings.PROGRESS_STREAM.format(index=1, count=2) in text


def test_job_status_text():
    job = DownloadJob(1, DownloadRequest("https://x", Quality.BEST, Path("o")))
    assert job_status_text(job) == strings.STATUS_QUEUED
    job.status = JobStatus.FAILED
    job.error = UserError(ErrorKind.PRIVATE)
    assert strings.ERR_PRIVATE in job_status_text(job)
    job.status = JobStatus.COMPLETED
    job.error = None
    job.output_path = Path("o/video.mp4")
    assert "video.mp4" in job_status_text(job)
