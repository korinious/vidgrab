"""History of finished downloads ("Υπάρχει ήδη"), in yt-dlp's download_archive format.

One line per video: ``<extractor key in lower case> <video id>``, e.g. ``youtube abc123``,
so the file stays compatible with ``yt-dlp --download-archive``. The file lives at
``%LOCALAPPDATA%\\VidGrab\\download-archive.txt``.

VidGrab writes it itself, and only after the file reached its destination folder. yt-dlp's
own archive option would record a video while it is still in the staging folder, even if
the final move then fails.

The archive is only consulted for lists: items already in it start unselected on the
selection screen. Single URLs, "Επανάληψη" and "Ξανά σε πλήρη ποιότητα" always download.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import platformdirs

from vidgrab import APP_NAME

log = logging.getLogger(__name__)

ARCHIVE_ENV = "VIDGRAB_ARCHIVE"  # override (tests, portable setups)
_LOCK = threading.Lock()  # download workers record from several threads


def default_archive_path() -> Path:
    if env := os.environ.get(ARCHIVE_ENV):
        return Path(env)
    data_dir = platformdirs.user_data_path(APP_NAME, appauthor=False, roaming=False)
    return data_dir / "download-archive.txt"


def archive_key(extractor: str | None, video_id: str | None) -> str | None:
    """'Youtube', 'abc123' -> 'youtube abc123' (yt-dlp's make_archive_id)."""
    if not extractor or not video_id:
        return None
    return f"{extractor.split(':')[0].lower()} {video_id}"


def load_keys(path: Path | None = None) -> set[str]:
    path = path or default_archive_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    except OSError:
        log.exception("Could not read the download archive %s", path)
        return set()
    return {line.strip() for line in text.splitlines() if line.strip()}


def record(key: str | None, path: Path | None = None) -> None:
    """Append one finished download. Never raises: a broken history must not fail a download."""
    if not key:
        return
    path = path or default_archive_path()
    try:
        with _LOCK:
            if key in load_keys(path):
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(key + "\n")
    except OSError:
        log.exception("Could not write to the download archive %s", path)


def count(path: Path | None = None) -> int:
    return len(load_keys(path))


def clear(path: Path | None = None) -> int:
    """Delete the history ("Καθαρισμός ιστορικού λήψεων"). Returns how many entries it had."""
    path = path or default_archive_path()
    with _LOCK:
        removed = len(load_keys(path))
        path.unlink(missing_ok=True)
    log.info("Download history cleared (%d entries)", removed)
    return removed
