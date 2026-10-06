"""Map quality/format choices to yt-dlp format, sorting and postprocessor options."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from vidgrab.core.models import (
    DEFAULT_MP3_BITRATE,
    MP3_BITRATES,
    AudioFormat,
    Quality,
    VideoContainer,
)

_VIDEO_FORMATS: dict[Quality, str] = {
    Quality.BEST: "bv*+ba/b",
    Quality.P1080: "bv*[height<=1080]+ba/b[height<=1080]/b",
    Quality.P720: "bv*[height<=720]+ba/b[height<=720]/b",
}

# Resolution first; among equal resolutions prefer mp4 video + m4a (AAC) audio, so the
# MP4 merge rarely needs any audio conversion.
MP4_FORMAT_SORT = ["res", "ext:mp4:m4a"]


def format_options(
    quality: Quality,
    container: VideoContainer = VideoContainer.MP4,
    audio_format: AudioFormat = AudioFormat.MP3,
    mp3_bitrate: int = DEFAULT_MP3_BITRATE,
) -> dict[str, Any]:
    """Return the yt-dlp params for the requested quality and output format.

    Plain str values are accepted too (QComboBox hands enums back as str).
    """
    quality = Quality(quality)
    if quality.is_audio:
        return _audio_options(AudioFormat(audio_format), int(mp3_bitrate))
    return _video_options(quality, VideoContainer(container))


def _video_options(quality: Quality, container: VideoContainer) -> dict[str, Any]:
    if container is VideoContainer.MP4:
        return {
            "format": _VIDEO_FORMATS[quality],
            "format_sort": list(MP4_FORMAT_SORT),
            "merge_output_format": "mp4",
            # Single-file formats (no merge) are remuxed too: container change only.
            # If the audio is still not MP4-friendly afterwards, the downloader converts
            # just the audio to AAC (see core/audiofix.py). Video is never re-encoded.
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        }
    return {
        "format": _VIDEO_FORMATS[quality],
        "merge_output_format": "mkv",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"}],
    }


def _audio_options(audio_format: AudioFormat, mp3_bitrate: int) -> dict[str, Any]:
    if audio_format is AudioFormat.MP3:
        if mp3_bitrate not in MP3_BITRATES:
            raise ValueError(f"unsupported MP3 bitrate {mp3_bitrate}; use one of {MP3_BITRATES}")
        return {
            "format": "ba/b",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(mp3_bitrate),
                }
            ],
        }
    # Original: keep the source codec (m4a/AAC or opus). "best" makes yt-dlp copy the
    # stream; for sites without audio-only formats it extracts the audio track by copying.
    return {
        "format": "ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}],
    }


def exclude_format_ids(format_spec: str, format_ids: Sequence[str]) -> str:
    """Add ``[format_id!=X]`` filters to every selector in ``format_spec``.

    Used after an HTTP 403 to avoid the format whose URL was refused.
    """
    if not format_ids:
        return format_spec
    filters = "".join(f"[format_id!='{fid}']" for fid in dict.fromkeys(format_ids))
    parts = re.split(r"([/+,()])", format_spec)
    return "".join(p if p in "/+,()" or not p.strip() else p + filters for p in parts)
