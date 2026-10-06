"""Display text for enums and numbers. No Qt here, so it is unit-testable."""

from __future__ import annotations

from vidgrab import strings
from vidgrab.core.errors import UserError
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import JobStatus, Progress, Quality

QUALITY_ORDER: tuple[Quality, ...] = (
    Quality.BEST,
    Quality.P1080,
    Quality.P720,
    Quality.AUDIO_MP3,
)

QUALITY_LABELS: dict[Quality, str] = {
    Quality.BEST: strings.QUALITY_BEST,
    Quality.P1080: strings.QUALITY_1080P,
    Quality.P720: strings.QUALITY_720P,
    Quality.AUDIO_MP3: strings.QUALITY_AUDIO_MP3,
}

STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.QUEUED: strings.STATUS_QUEUED,
    JobStatus.DOWNLOADING: strings.STATUS_DOWNLOADING,
    JobStatus.POSTPROCESSING: strings.STATUS_POSTPROCESSING,
    JobStatus.CANCELLING: strings.STATUS_CANCELLING,
    JobStatus.COMPLETED: strings.STATUS_COMPLETED,
    JobStatus.FAILED: strings.STATUS_FAILED,
    JobStatus.CANCELLED: strings.STATUS_CANCELLED,
}

_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(n: float | None) -> str:
    if n is None or n < 0:
        return strings.UNKNOWN_VALUE
    value = float(n)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def format_speed(bytes_per_s: float | None) -> str:
    if not bytes_per_s:
        return strings.UNKNOWN_VALUE
    return f"{format_bytes(bytes_per_s)}/s"


def format_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return strings.UNKNOWN_VALUE
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def progress_text(p: Progress) -> str:
    frac = p.overall_fraction
    percent = f"{frac * 100:.0f}%" if frac is not None else format_bytes(p.downloaded_bytes)
    text = strings.PROGRESS_DETAIL.format(
        percent=percent, speed=format_speed(p.speed), eta=format_eta(p.eta)
    )
    if p.stream_count > 1:
        stream = strings.PROGRESS_STREAM.format(index=p.stream_index, count=p.stream_count)
        text = f"{text} · {stream}"
    return text


def job_status_text(job: DownloadJob) -> str:
    status = STATUS_LABELS[job.status]
    if job.status is JobStatus.DOWNLOADING and job.progress is not None:
        return progress_text(job.progress)
    if job.status is JobStatus.FAILED and isinstance(job.error, UserError):
        return strings.STATUS_WITH_MESSAGE.format(status=status, message=job.error.message)
    if job.status is JobStatus.COMPLETED and job.output_path is not None:
        return strings.STATUS_WITH_MESSAGE.format(status=status, message=job.output_path.name)
    return status
