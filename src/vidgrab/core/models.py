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
    AUDIO = "audio"

    @property
    def is_audio(self) -> bool:
        return self is Quality.AUDIO


class VideoContainer(StrEnum):
    MP4 = "mp4"  # H.264/AAC-friendly, plays everywhere; audio converted to AAC if needed
    MKV = "mkv"  # original streams, no conversion


class AudioFormat(StrEnum):
    MP3 = "mp3"
    ORIGINAL = "original"  # m4a/opus as delivered, no conversion


MP3_BITRATES: tuple[int, ...] = (128, 192, 256, 320)
DEFAULT_MP3_BITRATE = 192


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
    max_height: int | None = None  # best video resolution offered, e.g. 2160
    # 1-based item of a multi-video post (Instagram carousel, X post) that has no URL of
    # its own: download ``url`` with yt-dlp's playlist_items.
    playlist_item: int | None = None
    # Set when the link points at a video inside a list (watch?v=...&list=...): the
    # preview then offers "Μόνο αυτό το βίντεο / Όλη η λίστα".
    list_url: str | None = None

    @classmethod
    def from_info_dict(
        cls, url: str, info: dict[str, Any], playlist_item: int | None = None
    ) -> VideoInfo:
        from vidgrab.core.formats import video_height  # local: formats imports models

        duration = info.get("duration")
        heights = [h for h in map(video_height, info.get("formats") or [info]) if h]
        return cls(
            url=url if playlist_item else (info.get("webpage_url") or url),
            id=str(info.get("id") or ""),
            title=info.get("title") or info.get("id") or url,
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            thumbnail_url=info.get("thumbnail") or best_thumbnail(info.get("thumbnails")),
            uploader=info.get("uploader") or info.get("channel"),
            extractor=info.get("extractor_key") or info.get("extractor"),
            max_height=max(heights, default=None),
            playlist_item=playlist_item,
        )


class EntryState(StrEnum):
    AVAILABLE = "available"
    PRIVATE = "private"  # "Ιδιωτικό"
    UNAVAILABLE = "unavailable"  # deleted, blocked... "Μη διαθέσιμο"


@dataclass(frozen=True)
class ListingEntry:
    """One video of a playlist or multi-video post, from a flat (cheap) extraction."""

    position: int  # 1-based position in the list (used for "03 - title")
    id: str
    title: str
    url: str  # what to download: the video's own URL, or the post URL with playlist_item
    playlist_item: int | None = None
    duration: int | None = None
    thumbnail_url: str | None = None
    state: EntryState = EntryState.AVAILABLE
    archive_key: str | None = None  # "youtube abc123", to check the download history

    @property
    def available(self) -> bool:
        return self.state is EntryState.AVAILABLE


@dataclass(frozen=True)
class Listing:
    """A YouTube playlist, an Instagram carousel, an X post with several videos..."""

    url: str
    id: str
    title: str
    entries: tuple[ListingEntry, ...]
    extractor: str | None = None
    uploader: str | None = None

    @property
    def available_entries(self) -> list[ListingEntry]:
        return [e for e in self.entries if e.available]

    @property
    def total_duration(self) -> int | None:
        durations = [e.duration for e in self.available_entries if e.duration]
        return sum(durations) if durations else None


def best_thumbnail(thumbnails: Any) -> str | None:
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
    """Everything one queued download needs. Frozen: changing the UI later never affects it."""

    url: str
    quality: Quality
    output_dir: Path
    cookies: CookieConfig = field(default_factory=CookieConfig)
    title: str | None = None  # display only
    container: VideoContainer = VideoContainer.MP4  # used when quality is a video quality
    audio_format: AudioFormat = AudioFormat.MP3  # used when quality is AUDIO
    mp3_bitrate: int = DEFAULT_MP3_BITRATE  # kbps, used for AudioFormat.MP3
    playlist_item: int | None = None  # download only this item of a multi-video post
    # Final file name without extension (already sanitised), e.g. "03 - Title" for list
    # items. None: yt-dlp's "Title [id]" as for single videos.
    filename: str | None = None


class UpgradeOutcome(StrEnum):
    """Result of "Ξανά σε πλήρη ποιότητα" on a card that got a lower resolution."""

    UPGRADED = "upgraded"  # higher resolution: replaced the old file (old one to the bin)
    NO_BETTER = "no_better"  # same or lower: kept the old file, discarded the new one


@dataclass(frozen=True)
class UpgradeTarget:
    """An existing download that a full-quality retry may replace."""

    path: Path
    height: int  # resolution of the existing file; the retry must beat it
    requested_height: int | None = None  # what was wanted originally (kept for the chip)


@dataclass(frozen=True)
class DownloadResult:
    """What a finished download produced."""

    path: Path | None
    requested_height: int | None = None  # best height that was asked for and available
    actual_height: int | None = None  # height of the video that was actually saved
    upgrade: UpgradeOutcome | None = None  # set only for a full-quality retry

    @property
    def downgraded(self) -> bool:
        """True if the saved video is smaller than what was requested (e.g. after a 403)."""
        return bool(
            self.requested_height
            and self.actual_height
            and self.actual_height < self.requested_height
        )
