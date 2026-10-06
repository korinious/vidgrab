"""Fetch video metadata (title, thumbnail, duration) without downloading."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import ErrorKind, UserError, classify
from vidgrab.core.models import CookieConfig, VideoInfo
from vidgrab.core.options import YdlFactory, base_options, default_ydl_factory

log = logging.getLogger(__name__)


def validate_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url and "." in url.split("/")[0]:
        url = "https://" + url  # e.g. "youtu.be/abc"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in url:
        raise UserError(ErrorKind.INVALID_URL, detail=url)
    return url


def fetch_info(
    url: str,
    binaries: Binaries,
    cookies: CookieConfig | None = None,
    ydl_factory: YdlFactory = default_ydl_factory,
) -> VideoInfo:
    """Return metadata for a single video. Raises UserError."""
    url = validate_url(url)
    try:
        opts = base_options(binaries, cookies or CookieConfig())
        opts["skip_download"] = True
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        err = classify(exc)
        log.warning("Metadata fetch failed for %s: %s (%s)", url, err.kind, err.detail)
        raise err from exc

    if not isinstance(info, dict):
        raise UserError(ErrorKind.UNKNOWN, detail=f"yt-dlp returned {type(info).__name__}")
    if info.get("_type") in ("playlist", "multi_video"):
        raise UserError(ErrorKind.PLAYLIST_NOT_SUPPORTED, detail=url)

    video = VideoInfo.from_info_dict(url, info)
    log.info("Fetched metadata for %s: %r (%s)", url, video.title, video.extractor)
    return video
