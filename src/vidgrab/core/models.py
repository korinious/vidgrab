"""Plain data types shared by core and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Quality(StrEnum):
    BEST = "best"
    P1080 = "1080p"
    P720 = "720p"
    AUDIO_MP3 = "audio_mp3"


class CookieSource(StrEnum):
    NONE = "none"
    FIREFOX = "firefox"
    CHROME = "chrome"
    EDGE = "edge"
    FILE = "file"


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    POSTPROCESSING = "postprocessing"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING, JobStatus.CANCELLING)

    @property
    def is_finished(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)


class Phase(StrEnum):
    DOWNLOADING = "downloading"
    POSTPROCESSING = "postprocessing"


@dataclass(frozen=True)
class CookieConfig:
    source: CookieSource = CookieSource.NONE
    file_path: str | None = None


@dataclass(frozen=True)
class VideoInfo:
    url: str
    id: str
    title: str
    duration: int | None = None
    thumbnail_url: str | None = None
    uploader: str | None = None
    extractor: str | None = None

    @classmethod
    def from_info_dict(cls, url: str, info: dict[str, Any]) -> VideoInfo:
        duration = info.get("duration")
        return cls(
            url=info.get("webpage_url") or url,
            id=str(info.get("id") or ""),
            title=info.get("title") or info.get("id") or url,
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            thumbnail_url=info.get("thumbnail") or _best_thumbnail(info.get("thumbnails")),
            uploader=info.get("uploader") or info.get("channel"),
            extractor=info.get("extractor_key") or info.get("extractor"),
        )


def _best_thumbnail(thumbnails: Any) -> str | None:
    if not isinstance(thumbnails, list):
        return None
    urls = [t.get("url") for t in thumbnails if isinstance(t, dict) and t.get("url")]
    return urls[-1] if urls else None  # yt-dlp sorts thumbnails worst -> best


def format_duration(seconds: int | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass(frozen=True)
class Progress:
    phase: Phase = Phase.DOWNLOADING
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None  # bytes/s
    eta: int | None = None  # seconds
    stream_index: int = 1  # 1-based: video and audio are downloaded as separate streams
    stream_count: int = 1

    @property
    def stream_fraction(self) -> float | None:
        if not self.total_bytes:
            return None
        return max(0.0, min(1.0, self.downloaded_bytes / self.total_bytes))

    @property
    def overall_fraction(self) -> float | None:
        if self.phase is Phase.POSTPROCESSING:
            return 1.0
        frac = self.stream_fraction
        if frac is None:
            return None
        count = max(1, self.stream_count)
        index = min(max(1, self.stream_index), count)
        return (index - 1 + frac) / count


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    quality: Quality
    output_dir: Path
    cookies: CookieConfig = field(default_factory=CookieConfig)
    title: str | None = None  # display only
