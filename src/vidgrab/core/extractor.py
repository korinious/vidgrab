"""Fetch metadata without downloading: one video, or the list behind a link.

``probe()`` is what the UI calls for a pasted link. It returns either

- a ``VideoInfo`` (one video; with ``list_url`` set when the link is a video inside a
  YouTube list, so the preview can offer "Μόνο αυτό το βίντεο / Όλη η λίστα"), or
- a ``Listing`` (a playlist, an Instagram carousel, an X post with several videos...).

Lists use yt-dlp's ``extract_flat="in_playlist"``: one cheap request per page of entries,
no full extraction of every video before the user has chosen which ones to download.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlparse

from vidgrab.core.archive import archive_key
from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import ErrorKind, UserError, classify
from vidgrab.core.models import (
    CookieConfig,
    EntryState,
    Listing,
    ListingEntry,
    VideoInfo,
    best_thumbnail,
)
from vidgrab.core.options import YdlFactory, base_options, default_ydl_factory

log = logging.getLogger(__name__)

_LIST_TYPES = ("playlist", "multi_video")
_PRIVATE_AVAILABILITY = {"private", "premium_only", "subscriber_only", "needs_auth"}
_PRIVATE_TITLES = {"[private video]"}
_UNAVAILABLE_TITLES = {"[deleted video]", "[unavailable video]"}
_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "gif"}


def validate_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url and "." in url.split("/")[0]:
        url = "https://" + url  # e.g. "youtu.be/abc"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in url:
        raise UserError(ErrorKind.INVALID_URL, detail=url)
    return url


def _is_youtube_host(host: str) -> bool:
    host = host.lower()
    return host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com")


def has_video_and_list(url: str) -> str | None:
    """For 'watch?v=X&list=Y' (or youtu.be/X?list=Y) return the list's own URL, else None."""
    parsed = urlparse(url)
    if not _is_youtube_host(parsed.hostname or ""):
        return None
    query = parse_qs(parsed.query)
    has_video = bool(query.get("v")) or (parsed.hostname or "").lower() == "youtu.be"
    list_id = (query.get("list") or [""])[0]
    if has_video and list_id:
        return f"https://www.youtube.com/playlist?list={list_id}"
    return None


def _extract(
    url: str,
    binaries: Binaries,
    cookies: CookieConfig | None,
    ydl_factory: YdlFactory,
    **extra: Any,
) -> dict[str, Any]:
    try:
        opts = base_options(binaries, cookies or CookieConfig())
        opts["skip_download"] = True
        opts.update(extra)
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        err = classify(exc)
        log.warning("Metadata fetch failed for %s: %s (%s)", url, err.kind, err.detail)
        raise err from exc
    if not isinstance(info, dict):
        raise UserError(ErrorKind.UNKNOWN, detail=f"yt-dlp returned {type(info).__name__}")
    return info


def fetch_info(
    url: str,
    binaries: Binaries,
    cookies: CookieConfig | None = None,
    ydl_factory: YdlFactory = default_ydl_factory,
    *,
    playlist_item: int | None = None,
) -> VideoInfo:
    """Full metadata of one video. ``playlist_item`` picks one video of a multi-video post.

    Raises UserError.
    """
    url = validate_url(url)
    if playlist_item:
        info = _extract(
            url,
            binaries,
            cookies,
            ydl_factory,
            noplaylist=False,
            playlist_items=str(playlist_item),
        )
    else:
        info = _extract(url, binaries, cookies, ydl_factory, noplaylist=True)
    if info.get("_type") in _LIST_TYPES:
        entries = [e for e in info.get("entries") or () if isinstance(e, dict)]
        if len(entries) != 1:
            raise UserError(ErrorKind.EMPTY_LISTING, detail=f"{url}: {len(entries)} entries")
        info = {"extractor_key": info.get("extractor_key"), **entries[0]}
    video = VideoInfo.from_info_dict(url, info, playlist_item=playlist_item)
    log.info("Fetched metadata for %s: %r (%s)", url, video.title, video.extractor)
    return video


def _duration(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _is_image_only(entry: dict[str, Any]) -> bool:
    """Instagram carousels mix photos and videos; photos are not offered."""
    if entry.get("_type") == "url":
        return False
    formats = entry.get("formats") or [entry]
    for fmt in formats:
        ext = str(fmt.get("ext") or "").lower()
        if ext and ext not in _IMAGE_EXTS:
            return False
        if fmt.get("vcodec") not in (None, "none") or fmt.get("acodec") not in (None, "none"):
            return False
    return all(str(f.get("ext") or "").lower() in _IMAGE_EXTS for f in formats)


def _entry_state(entry: dict[str, Any]) -> EntryState:
    title = str(entry.get("title") or "").strip().lower()
    availability = str(entry.get("availability") or "").lower()
    if availability in _PRIVATE_AVAILABILITY or title in _PRIVATE_TITLES:
        return EntryState.PRIVATE
    if availability == "unavailable" or title in _UNAVAILABLE_TITLES:
        return EntryState.UNAVAILABLE
    return EntryState.AVAILABLE


def _listing_from(url: str, info: dict[str, Any]) -> Listing:
    extractor = info.get("extractor_key") or info.get("extractor")
    entries: list[ListingEntry] = []
    for index, raw in enumerate(info.get("entries") or (), start=1):
        if raw is None:  # yt-dlp leaves None for entries it could not resolve
            entries.append(
                ListingEntry(index, "", f"#{index}", url, index, state=EntryState.UNAVAILABLE)
            )
            continue
        if not isinstance(raw, dict) or _is_image_only(raw):
            continue
        own_url = raw.get("url") if raw.get("_type") == "url" else None
        if not (isinstance(own_url, str) and own_url.startswith(("http://", "https://"))):
            own_url = None
        video_id = str(raw.get("id") or "")
        entries.append(
            ListingEntry(
                position=int(raw.get("playlist_index") or index),
                id=video_id,
                title=str(raw.get("title") or video_id or f"#{index}"),
                url=own_url or url,
                playlist_item=None if own_url else index,
                duration=_duration(raw.get("duration")),
                thumbnail_url=raw.get("thumbnail") or best_thumbnail(raw.get("thumbnails")),
                state=_entry_state(raw),
                archive_key=archive_key(
                    raw.get("ie_key") or raw.get("extractor_key") or extractor, video_id
                ),
            )
        )
    return Listing(
        url=info.get("webpage_url") or url,
        id=str(info.get("id") or ""),
        title=str(info.get("title") or info.get("id") or url),
        entries=tuple(entries),
        extractor=extractor,
        uploader=info.get("uploader") or info.get("channel"),
    )


def fetch_listing(
    url: str,
    binaries: Binaries,
    cookies: CookieConfig | None = None,
    ydl_factory: YdlFactory = default_ydl_factory,
) -> Listing:
    """All entries of a list, from a flat extraction. Raises UserError (EMPTY_LISTING too)."""
    url = validate_url(url)
    info = _extract(
        url, binaries, cookies, ydl_factory, noplaylist=False, extract_flat="in_playlist"
    )
    if info.get("_type") not in _LIST_TYPES:
        raise UserError(ErrorKind.EMPTY_LISTING, detail=f"{url} is not a list")
    listing = _listing_from(url, info)
    if not listing.available_entries:
        raise UserError(ErrorKind.EMPTY_LISTING, detail=f"{url}: no available entries")
    log.info(
        "Fetched list %s: %r, %d entries (%d available)",
        url,
        listing.title,
        len(listing.entries),
        len(listing.available_entries),
    )
    return listing


def probe(
    url: str,
    binaries: Binaries,
    cookies: CookieConfig | None = None,
    ydl_factory: YdlFactory = default_ydl_factory,
) -> VideoInfo | Listing:
    """What a pasted link points at: one video, or a list to choose from. Raises UserError."""
    url = validate_url(url)
    if list_url := has_video_and_list(url):
        return replace(fetch_info(url, binaries, cookies, ydl_factory), list_url=list_url)

    info = _extract(
        url, binaries, cookies, ydl_factory, noplaylist=False, extract_flat="in_playlist"
    )
    if info.get("_type") not in _LIST_TYPES:
        video = VideoInfo.from_info_dict(url, info)
        log.info("Fetched metadata for %s: %r (%s)", url, video.title, video.extractor)
        return video

    listing = _listing_from(url, info)
    available = listing.available_entries
    if not available:
        raise UserError(ErrorKind.EMPTY_LISTING, detail=f"{url}: no available entries")
    if len(available) == 1:
        # Only one video (e.g. a carousel with one video and some photos): skip the
        # selection screen and show the normal preview.
        (entry,) = available
        log.info("List %s has a single video; showing it directly", url)
        return fetch_info(
            entry.url, binaries, cookies, ydl_factory, playlist_item=entry.playlist_item
        )
    log.info(
        "Fetched list %s: %r, %d entries (%d available)",
        url,
        listing.title,
        len(listing.entries),
        len(available),
    )
    return listing
