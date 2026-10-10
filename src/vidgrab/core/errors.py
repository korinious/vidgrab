"""Turn yt-dlp (and other) exceptions into user-friendly, typed errors."""

from __future__ import annotations

import re
from enum import StrEnum

from yt_dlp.cookies import CookieLoadError
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.utils import (
    DownloadCancelled,
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    PostProcessingError,
    UnsupportedError,
)

from vidgrab import strings


class ErrorKind(StrEnum):
    INVALID_URL = "invalid_url"
    UNSUPPORTED_URL = "unsupported_url"
    EMPTY_LISTING = "empty_listing"
    PRIVATE = "private"
    GEO_BLOCKED = "geo_blocked"
    LOGIN_REQUIRED = "login_required"
    AGE_RESTRICTED = "age_restricted"
    UNAVAILABLE = "unavailable"
    FORMAT_UNAVAILABLE = "format_unavailable"
    NETWORK = "network"
    FFMPEG_MISSING = "ffmpeg_missing"
    COOKIES_FAILED = "cookies_failed"
    FILE_LOCKED = "file_locked"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    POSTPROCESSING = "postprocessing"
    DISK = "disk"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


MESSAGES: dict[ErrorKind, str] = {
    ErrorKind.INVALID_URL: strings.ERR_INVALID_URL,
    ErrorKind.UNSUPPORTED_URL: strings.ERR_UNSUPPORTED_URL,
    ErrorKind.EMPTY_LISTING: strings.ERR_EMPTY_LISTING,
    ErrorKind.PRIVATE: strings.ERR_PRIVATE,
    ErrorKind.GEO_BLOCKED: strings.ERR_GEO_BLOCKED,
    ErrorKind.LOGIN_REQUIRED: strings.ERR_LOGIN_REQUIRED,
    ErrorKind.AGE_RESTRICTED: strings.ERR_AGE_RESTRICTED,
    ErrorKind.UNAVAILABLE: strings.ERR_UNAVAILABLE,
    ErrorKind.FORMAT_UNAVAILABLE: strings.ERR_FORMAT_UNAVAILABLE,
    ErrorKind.NETWORK: strings.ERR_NETWORK,
    ErrorKind.FFMPEG_MISSING: strings.ERR_FFMPEG_MISSING,
    ErrorKind.COOKIES_FAILED: strings.ERR_COOKIES_FAILED,
    ErrorKind.FILE_LOCKED: strings.ERR_FILE_LOCKED,
    ErrorKind.FORBIDDEN: strings.ERR_FORBIDDEN,
    ErrorKind.RATE_LIMITED: strings.ERR_RATE_LIMITED,
    ErrorKind.POSTPROCESSING: strings.ERR_POSTPROCESSING,
    ErrorKind.DISK: strings.ERR_DISK,
    ErrorKind.CANCELLED: strings.ERR_CANCELLED,
    ErrorKind.UNKNOWN: strings.ERR_UNKNOWN,
}


class UserError(Exception):
    """An error with a message that can be shown to the user as-is."""

    def __init__(self, kind: ErrorKind, message: str | None = None, detail: str = "") -> None:
        self.kind = kind
        self.message = message or MESSAGES[kind]
        self.detail = detail
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.kind not in (
            ErrorKind.INVALID_URL,
            ErrorKind.UNSUPPORTED_URL,
            ErrorKind.EMPTY_LISTING,
        )


# Ordered: the first match wins. Age checks come before generic "sign in" (login) checks,
# and cookie failures before everything (their messages mention browsers/login too).
_PATTERNS: list[tuple[ErrorKind, re.Pattern[str]]] = [
    (
        ErrorKind.COOKIES_FAILED,
        re.compile(
            r"could not (?:copy|find|decrypt|open).{0,40}cookie"
            r"|failed to (?:load|decrypt|read) cookies"
            r"|cookies? database"
            r"|dpapi"
            r"|app[- ]bound",
            re.I,
        ),
    ),
    (
        ErrorKind.AGE_RESTRICTED,
        re.compile(
            r"confirm your age|age[- ]restricted|age[- ]gated|inappropriate for some users",
            re.I,
        ),
    ),
    (
        ErrorKind.PRIVATE,
        re.compile(
            r"private video|video is private|this video is private|private account"
            r"|account is private|this content is private|\bis private\b",
            re.I,
        ),
    ),
    (
        ErrorKind.GEO_BLOCKED,
        re.compile(
            r"not available in your (?:country|region)|geo[- ]?restrict"
            r"|not available from your location|blocked it in your country"
            r"|not made this video available in your country",
            re.I,
        ),
    ),
    (
        ErrorKind.LOGIN_REQUIRED,
        re.compile(
            r"login required|log ?in (?:is )?required|requires? (?:a )?(?:login|authentication)"
            r"|sign in to confirm you.re not a bot|sign in to view|you need to log in"
            r"|--cookies|cookies-from-browser|account authentication"
            r"|only available for registered users"
            r"|members[- ]only|rate[- ]limit reached",
            re.I,
        ),
    ),
    (
        ErrorKind.FFMPEG_MISSING,
        re.compile(
            r"ffmpeg (?:is )?not (?:found|installed)|ffprobe (?:is )?not (?:found|installed)"
            r"|ffmpeg could not be found|ffprobe and ffmpeg not found",
            re.I,
        ),
    ),
    (
        # Windows sharing violation (antivirus, OneDrive sync, indexer holding the file).
        ErrorKind.FILE_LOCKED,
        re.compile(
            r"winerror 3[23]\b|being used by another process|sharing violation"
            r"|another process has locked a portion of the file",
            re.I,
        ),
    ),
    (ErrorKind.FORBIDDEN, re.compile(r"http error 403|\b403:? forbidden", re.I)),
    (ErrorKind.RATE_LIMITED, re.compile(r"http error 429|too many requests", re.I)),
    (ErrorKind.UNSUPPORTED_URL, re.compile(r"unsupported url", re.I)),
    (ErrorKind.FORMAT_UNAVAILABLE, re.compile(r"requested format is not available", re.I)),
    (
        ErrorKind.UNAVAILABLE,
        re.compile(
            r"video unavailable|has been removed|no longer available|does not exist"
            r"|content isn.t available|is not available|http error 404|this post is unavailable"
            r"|terminated|been deleted",
            re.I,
        ),
    ),
    (
        ErrorKind.NETWORK,
        re.compile(
            r"timed out|getaddrinfo|name or service not known|temporary failure in name resolution"
            r"|network is unreachable|connection (?:reset|refused|aborted)|remote end closed"
            r"|http error 5\d\d|\bssl\b|unable to download webpage|failed to resolve",
            re.I,
        ),
    ),
    (
        ErrorKind.DISK,
        re.compile(
            r"no space left|disk full|permission denied|access is denied|errno 13|errno 28",
            re.I,
        ),
    ),
]

_PREFIX = re.compile(r"^(?:ERROR:\s*)?(?:\[[^\]]+\]\s*(?:[\w-]+:\s+)?)?", re.I)


# Windows error codes: ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
LOCK_WINERRORS = frozenset({32, 33})


def is_lock_error(exc: BaseException) -> bool:
    """True for "file is being used by another process" errors (Windows sharing violation)."""
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in LOCK_WINERRORS


def clean_message(text: str) -> str:
    """Strip yt-dlp's 'ERROR: [extractor] id: ' prefix from a message."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    return _PREFIX.sub("", text, count=1).strip() or text


def _unwrap(exc: BaseException) -> list[BaseException]:
    """Return exc plus the exceptions it wraps (DownloadError.exc_info, __cause__)."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        nxt: BaseException | None = None
        if isinstance(current, DownloadError) and current.exc_info and current.exc_info[1]:
            nxt = current.exc_info[1]
        elif isinstance(current, ExtractorError) and isinstance(current.cause, BaseException):
            nxt = current.cause
        nxt = nxt or current.__cause__
        current = nxt
    return chain


def classify(exc: BaseException) -> UserError:
    """Map any exception raised while talking to yt-dlp to a UserError."""
    if isinstance(exc, UserError):
        return exc

    chain = _unwrap(exc)
    detail = clean_message(str(exc))

    for e in chain:
        if isinstance(e, UserError):
            return e
        if isinstance(e, DownloadCancelled):
            return UserError(ErrorKind.CANCELLED, detail=detail)
        if isinstance(e, CookieLoadError):
            return UserError(ErrorKind.COOKIES_FAILED, detail=detail)
        if isinstance(e, GeoRestrictedError):
            return UserError(ErrorKind.GEO_BLOCKED, detail=detail)
        if isinstance(e, UnsupportedError):
            return UserError(ErrorKind.UNSUPPORTED_URL, detail=detail)

    text = "\n".join(str(e) for e in chain)
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return UserError(kind, detail=detail)

    # Type-based fallbacks run after the message patterns, so e.g. an Instagram
    # "login required" error caused by an HTTP 403 stays LOGIN_REQUIRED.
    for e in chain:
        if isinstance(e, HTTPError):
            if e.status == 403:
                return UserError(ErrorKind.FORBIDDEN, detail=detail)
            if e.status == 429:
                return UserError(ErrorKind.RATE_LIMITED, detail=detail)
        if isinstance(e, TransportError | ConnectionError | TimeoutError):
            return UserError(ErrorKind.NETWORK, detail=detail)
        if is_lock_error(e):
            return UserError(ErrorKind.FILE_LOCKED, detail=detail)
        if isinstance(e, OSError):
            return UserError(ErrorKind.DISK, detail=detail)
        if isinstance(e, PostProcessingError):
            return UserError(ErrorKind.POSTPROCESSING, detail=detail)

    return UserError(ErrorKind.UNKNOWN, detail=detail)
