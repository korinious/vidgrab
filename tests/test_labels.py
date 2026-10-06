from pathlib import Path

import pytest

from vidgrab import strings
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import (
    AudioFormat,
    DownloadRequest,
    JobStatus,
    Progress,
    Quality,
    VideoContainer,
)
from vidgrab.ui.labels import (
    AUDIO_FORMAT_LABELS,
    AUDIO_FORMAT_ORDER,
    CONTAINER_LABELS,
    CONTAINER_ORDER,
    QUALITY_LABELS,
    QUALITY_ORDER,
    STATUS_LABELS,
    format_bytes,
    format_eta,
    format_speed,
    job_status_text,
    progress_text,
    request_format_text,
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


def test_format_labels_cover_all_enums():
    assert set(CONTAINER_LABELS) == set(VideoContainer) == set(CONTAINER_ORDER)
    assert set(AUDIO_FORMAT_LABELS) == set(AudioFormat) == set(AUDIO_FORMAT_ORDER)
    assert CONTAINER_ORDER[0] is VideoContainer.MP4  # MP4 is the default, listed first
    assert AUDIO_FORMAT_ORDER[0] is AudioFormat.MP3


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"quality": Quality.P1080}, "1080p · MP4"),
        ({"quality": Quality.BEST, "container": VideoContainer.MKV}, "Καλύτερη διαθέσιμη · MKV"),
        ({"quality": Quality.AUDIO, "mp3_bitrate": 320}, "Μόνο ήχος · MP3 320 kbps"),
        (
            {"quality": Quality.AUDIO, "audio_format": AudioFormat.ORIGINAL, "mp3_bitrate": 320},
            "Μόνο ήχος · Αρχικό (m4a/opus)",
        ),
    ],
)
def test_request_format_text(kwargs, expected):
    req = DownloadRequest("https://x", output_dir=Path("o"), **kwargs)
    assert request_format_text(req) == expected


def _completed(url, requested, actual):
    from vidgrab.core.models import DownloadResult

    job = DownloadJob(1, DownloadRequest(url, Quality.BEST, Path("o")))
    job.status = JobStatus.COMPLETED
    job.result = DownloadResult(Path("o/v.mp4"), requested, actual)
    return job


def test_lower_resolution_chip():
    from vidgrab.ui.labels import lower_resolution_chip

    text, tooltip = lower_resolution_chip(
        _completed("https://www.youtube.com/watch?v=x", 2160, 1080)
    )
    assert text == "1080p αντί 2160p"
    assert tooltip == "Το YouTube δεν έδωσε την υψηλότερη ποιότητα. Δοκίμασε ξανά αργότερα."
    _, other = lower_resolution_chip(_completed("https://x.com/a/status/1", 1080, 720))
    assert "YouTube" not in other
    assert lower_resolution_chip(_completed("https://youtu.be/x", 1080, 1080)) is None
    assert lower_resolution_chip(_completed("https://youtu.be/x", None, 720)) is None
    job = _completed("https://youtu.be/x", 2160, 1080)
    job.status = JobStatus.FAILED
    assert lower_resolution_chip(job) is None
