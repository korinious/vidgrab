"""Map a Quality choice to yt-dlp format/postprocessor options."""

from __future__ import annotations

from typing import Any

from vidgrab.core.models import Quality

MP3_BITRATE = "192"

_VIDEO_FORMATS: dict[Quality, str] = {
    Quality.BEST: "bv*+ba/b",
    Quality.P1080: "bv*[height<=1080]+ba/b[height<=1080]/b",
    Quality.P720: "bv*[height<=720]+ba/b[height<=720]/b",
}


def format_options(quality: Quality) -> dict[str, Any]:
    """Return the yt-dlp params for the requested quality."""
    quality = Quality(quality)  # also accept the plain str value
    if quality is Quality.AUDIO_MP3:
        return {
            "format": "ba/b",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": MP3_BITRATE,
                }
            ],
        }
    return {
        "format": _VIDEO_FORMATS[quality],
        # Prefer an mp4 container when merging; yt-dlp falls back to mkv if the
        # codecs cannot go into mp4.
        "merge_output_format": "mp4/mkv",
    }
