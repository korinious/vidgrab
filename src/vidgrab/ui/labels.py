"""Display text for enums and numbers. No Qt here, so it is unit-testable."""

from __future__ import annotations

from vidgrab import strings
from vidgrab.core.errors import UserError
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import (
    AudioFormat,
    DownloadRequest,
    JobStatus,
    Progress,
    Quality,
    UpgradeOutcome,
    VideoContainer,
)

QUALITY_ORDER: tuple[Quality, ...] = (
    Quality.BEST,
    Quality.P1080,
    Quality.P720,
    Quality.AUDIO,
)

QUALITY_LABELS: dict[Quality, str] = {
    Quality.BEST: strings.QUALITY_BEST,
    Quality.P1080: strings.QUALITY_1080P,
    Quality.P720: strings.QUALITY_720P,
    Quality.AUDIO: strings.QUALITY_AUDIO,
}

CONTAINER_ORDER: tuple[VideoContainer, ...] = (VideoContainer.MP4, VideoContainer.MKV)
CONTAINER_LABELS: dict[VideoContainer, str] = {
    VideoContainer.MP4: strings.FORMAT_MP4,
    VideoContainer.MKV: strings.FORMAT_MKV,
}

AUDIO_FORMAT_ORDER: tuple[AudioFormat, ...] = (AudioFormat.MP3, AudioFormat.ORIGINAL)
AUDIO_FORMAT_LABELS: dict[AudioFormat, str] = {
    AudioFormat.MP3: strings.AUDIO_FORMAT_MP3,
    AudioFormat.ORIGINAL: strings.AUDIO_FORMAT_ORIGINAL,
}


def bitrate_label(kbps: int) -> str:
    return strings.BITRATE_ITEM.format(kbps=kbps)


def request_format_text(request: DownloadRequest) -> str:
    """Short description of a job's choices, e.g. "1080p · MP4" or "Μόνο ήχος · MP3 192 kbps"."""
    quality = Quality(request.quality)
    if quality.is_audio:
        audio = AudioFormat(request.audio_format)
        fmt = AUDIO_FORMAT_LABELS[audio]
        if audio is AudioFormat.MP3:
            fmt = f"{fmt} {bitrate_label(request.mp3_bitrate)}"
    else:
        fmt = CONTAINER_LABELS[VideoContainer(request.container)]
    return strings.JOB_FORMAT.format(quality=QUALITY_LABELS[quality], format=fmt)


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
        text = strings.STATUS_WITH_MESSAGE.format(status=status, message=job.output_path.name)
        outcome = job.result.upgrade if job.result is not None else None
        if outcome is UpgradeOutcome.NO_BETTER:
            text = f"{text} · {strings.STATUS_NO_BETTER_QUALITY}"
        elif outcome is UpgradeOutcome.UPGRADED:
            height = job.result.actual_height if job.result is not None else None
            text = f"{text} · {strings.STATUS_UPGRADED.format(height=height)}"
        return text
    return status


def lower_resolution_chip(job: DownloadJob) -> tuple[str, str] | None:
    """(text, tooltip) when a completed job got a lower resolution than requested."""
    from vidgrab.core.downloader import is_youtube_url

    result = job.result
    if job.status is not JobStatus.COMPLETED or result is None or not result.downgraded:
        return None
    text = strings.CHIP_LOWER_RESOLUTION.format(
        actual=result.actual_height, requested=result.requested_height
    )
    tooltip = (
        strings.TOOLTIP_LOWER_RESOLUTION
        if is_youtube_url(job.request.url)
        else strings.TOOLTIP_LOWER_RESOLUTION_OTHER_SITE
    )
    return text, tooltip
