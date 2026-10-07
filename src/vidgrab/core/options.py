"""yt-dlp params shared by metadata fetching and downloading."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vidgrab.core.binaries import Binaries
from vidgrab.core.cookies import cookie_options
from vidgrab.core.logging_setup import YtDlpLogger
from vidgrab.core.models import CookieConfig

# %(title).150B keeps the title to 150 bytes so paths stay under the Windows limit.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

# Anything that can be called with a params dict and used as a context manager that has
# extract_info(url, download=...): yt_dlp.YoutubeDL in production, a fake in tests.
YdlFactory = Callable[[dict[str, Any]], Any]


def default_ydl_factory(params: dict[str, Any]) -> Any:
    from yt_dlp import YoutubeDL

    return YoutubeDL(params)


def base_options(binaries: Binaries, cookies: CookieConfig) -> dict[str, Any]:
    return {
        "quiet": True,
        "noprogress": True,
        "logger": YtDlpLogger(),
        "windowsfilenames": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        # Renames inside the staging folder can still hit a brief antivirus lock on Windows.
        "file_access_retries": 10,
        **binaries.ytdlp_options(),
        **cookie_options(cookies),
    }
