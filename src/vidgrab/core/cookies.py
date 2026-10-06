"""Translate the cookie setting into yt-dlp options."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vidgrab import strings
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.models import CookieConfig, CookieSource

# Display order in the UI: Firefox first (most reliable on Windows, see CLAUDE.md).
COOKIE_SOURCES_ORDER: tuple[CookieSource, ...] = (
    CookieSource.NONE,
    CookieSource.FIREFOX,
    CookieSource.CHROME,
    CookieSource.EDGE,
    CookieSource.FILE,
)

COOKIE_SOURCE_LABELS: dict[CookieSource, str] = {
    CookieSource.NONE: strings.COOKIES_NONE,
    CookieSource.FIREFOX: strings.COOKIES_FIREFOX,
    CookieSource.CHROME: strings.COOKIES_CHROME,
    CookieSource.EDGE: strings.COOKIES_EDGE,
    CookieSource.FILE: strings.COOKIES_FILE,
}

_BROWSERS: dict[CookieSource, str] = {
    CookieSource.FIREFOX: "firefox",
    CookieSource.CHROME: "chrome",
    CookieSource.EDGE: "edge",
}


def cookie_options(config: CookieConfig) -> dict[str, Any]:
    """Return yt-dlp params for the cookie config. Raises UserError for a missing file."""
    config = CookieConfig(CookieSource(config.source), config.file_path)  # accept plain str
    if config.source is CookieSource.NONE:
        return {}
    if config.source is CookieSource.FILE:
        path = Path(config.file_path or "")
        if not config.file_path or not path.is_file():
            raise UserError(
                ErrorKind.COOKIES_FAILED,
                message=strings.ERR_COOKIE_FILE_MISSING.format(path=config.file_path or ""),
            )
        return {"cookiefile": str(path)}
    return {"cookiesfrombrowser": (_BROWSERS[config.source],)}
