"""Checking for and downloading new VidGrab releases from GitHub.

- One unauthenticated GET of ``/repos/{UPDATE_REPO}/releases/latest``; the only header
  besides ``Accept`` is ``User-Agent: VidGrab/<version>``. Nothing else is sent: no
  telemetry, no identifiers, no settings.
- Any failure (offline, timeout, 404, 403/429 rate limit, bad JSON) is a quiet
  ``CheckStatus.FAILED``: logged, never shown to the user unless they pressed
  "Έλεγχος τώρα".
- Drafts and prereleases are ignored, and so is a release whose zip is not attached yet
  (the release is created in the GitHub UI before the build has uploaded it).
- The download goes to the Downloads folder and is accepted only if its SHA256 matches
  ``SHA256SUMS.txt`` of the same release. Otherwise the file is deleted and the user gets
  an error; it is never accepted silently.

Network access goes through ``opener``, by default this module's ``urlopen`` looked up at
call time, so the tests replace it with a fake (autouse ``fake_http`` fixture) and never
touch the network.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from vidgrab import __version__
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.staging import reserve_destination

log = logging.getLogger(__name__)

UPDATE_REPO = "korinious/vidgrab"
LATEST_RELEASE_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{UPDATE_REPO}/releases"
# Assets are downloaded only from this repository's releases (GitHub then redirects to
# its download host).
ASSET_URL_PREFIX = f"https://github.com/{UPDATE_REPO}/releases/download/"
SUMS_NAME = "SHA256SUMS.txt"
CHECK_TIMEOUT_S = 5.0
DOWNLOAD_TIMEOUT_S = 30.0  # per read; the whole download may take longer
AUTO_CHECK_INTERVAL = timedelta(hours=24)
STALE_YTDLP_DAYS = 60
MAX_RELEASE_JSON = 2 * 1024 * 1024
MAX_SUMS_SIZE = 64 * 1024
CHUNK = 64 * 1024

Opener = Callable[..., Any]  # urllib.request.urlopen(request, timeout=...)
urlopen: Opener = urllib.request.urlopen
ProgressCallback = Callable[[int, int], None]  # bytes done, total (0 if unknown)

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def zip_name(version: str) -> str:
    return f"VidGrab-{version}-win64.zip"


def user_agent() -> str:
    return f"VidGrab/{__version__}"


def parse_version(text: object) -> tuple[int, int, int] | None:
    """(major, minor, patch) for "v0.4.1" or "0.4.1"; None for anything else."""
    if not isinstance(text, str):
        return None
    match = _VERSION.match(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    new, cur = parse_version(candidate), parse_version(current)
    return new is not None and cur is not None and new > cur


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class UpdateInfo:
    version: str  # "0.4.1"
    notes: str  # release body (Markdown), may be empty
    page_url: str
    zip: Asset
    sums: Asset | None  # SHA256SUMS.txt; a missing one fails the download, not the check


class CheckStatus(StrEnum):
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"
    FAILED = "failed"


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    update: UpdateInfo | None = None


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": accept})


def _asset(data: object) -> Asset | None:
    if not isinstance(data, dict):
        return None
    name, url, size = data.get("name"), data.get("browser_download_url"), data.get("size", 0)
    if not isinstance(name, str) or not isinstance(url, str):
        return None
    if not url.startswith(ASSET_URL_PREFIX):
        log.warning("Ignoring release asset %s from an unexpected URL: %s", name, url)
        return None
    return Asset(name, url, size if isinstance(size, int) and size > 0 else 0)


def parse_release(data: object, current: str = __version__) -> CheckResult:
    """What the ``releases/latest`` JSON means for a user of version ``current``."""
    if not isinstance(data, dict):
        log.info("Update check: unexpected response")
        return CheckResult(CheckStatus.FAILED)
    tag = data.get("tag_name")
    if data.get("draft") or data.get("prerelease"):
        log.info("Update check: ignoring draft/prerelease %s", tag)
        return CheckResult(CheckStatus.UP_TO_DATE)
    if parse_version(tag) is None:
        log.info("Update check: ignoring release with tag %r", tag)
        return CheckResult(CheckStatus.UP_TO_DATE)
    version = ".".join(str(n) for n in parse_version(tag))  # type: ignore[union-attr]
    if not is_newer(version, current):
        log.info("Update check: latest release is %s, this is %s", version, current)
        return CheckResult(CheckStatus.UP_TO_DATE)
    assets = [a for a in map(_asset, data.get("assets") or []) if a is not None]
    by_name = {a.name: a for a in assets}
    zip_asset = by_name.get(zip_name(version))
    if zip_asset is None:
        # Created in the GitHub UI, the build has not attached the zip yet.
        log.info("Update check: release %s has no %s yet", version, zip_name(version))
        return CheckResult(CheckStatus.UP_TO_DATE)
    page = data.get("html_url")
    notes = data.get("body")
    log.info("Update check: VidGrab %s is available", version)
    return CheckResult(
        CheckStatus.AVAILABLE,
        UpdateInfo(
            version=version,
            notes=notes if isinstance(notes, str) else "",
            page_url=page if isinstance(page, str) else RELEASES_PAGE,
            zip=zip_asset,
            sums=by_name.get(SUMS_NAME),
        ),
    )


def check_for_update(current: str = __version__, opener: Opener | None = None) -> CheckResult:
    """Ask GitHub for the latest release. Never raises; failures are FAILED and logged."""
    opener = opener or urlopen
    try:
        with opener(
            _request(LATEST_RELEASE_API, "application/vnd.github+json"), timeout=CHECK_TIMEOUT_S
        ) as response:
            raw = response.read(MAX_RELEASE_JSON + 1)
        if len(raw) > MAX_RELEASE_JSON:
            raise ValueError("response too large")
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404: no release yet; 403/429: rate limit (60 requests/hour per IP without a token)
        log.info("Update check failed: HTTP %s %s", exc.code, exc.reason)
        return CheckResult(CheckStatus.FAILED)
    except Exception as exc:  # offline, timeout, TLS, bad JSON: never the user's problem
        log.info("Update check failed: %s: %s", type(exc).__name__, exc)
        return CheckResult(CheckStatus.FAILED)
    return parse_release(data, current)


# --- when to check ---------------------------------------------------------------------


def parse_check_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_check_time(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds")


def should_auto_check(enabled: bool, last_check: str | None, now: datetime) -> bool:
    """At most once per 24 hours, and never when the user turned it off."""
    if not enabled:
        return False
    last = parse_check_time(last_check)
    if last is None:
        return True
    # A last check "in the future" means the clock was changed: check again.
    return last > now or now - last >= AUTO_CHECK_INTERVAL


def should_offer(update: UpdateInfo | None, skipped_version: str | None) -> bool:
    """The banner shows unless the user chose "Παράλειψη αυτής της έκδοσης" for it."""
    return update is not None and update.version != skipped_version


# --- old yt-dlp ------------------------------------------------------------------------


def ytdlp_release_date(version: str | None) -> date | None:
    """yt-dlp versions are dates: "2026.08.19" (or "2026.08.19.233" for nightlies)."""
    match = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", version or "")
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def ytdlp_is_stale(version: str | None, today: date) -> bool:
    released = ytdlp_release_date(version)
    return released is not None and (today - released).days > STALE_YTDLP_DAYS


# --- download --------------------------------------------------------------------------


def parse_sums(text: str) -> dict[str, str]:
    """{file name: sha256} from ``sha256sum`` output ("<hash>  name" or "<hash> *name")."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([0-9a-fA-F]{64}) [ *](.+)$", line.strip())
        if match:
            sums[match.group(2).strip()] = match.group(1).lower()
    return sums


def _network_error(exc: BaseException) -> UserError:
    return UserError(ErrorKind.NETWORK, detail=f"{type(exc).__name__}: {exc}")


def _expected_sha256(update: UpdateInfo, opener: Opener) -> str:
    if update.sums is None:
        raise UserError(
            ErrorKind.UPDATE_CHECKSUM_MISSING, detail=f"{SUMS_NAME} is not in the release"
        )
    try:
        with opener(
            _request(update.sums.url, "application/octet-stream"), timeout=DOWNLOAD_TIMEOUT_S
        ) as response:
            raw = response.read(MAX_SUMS_SIZE + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UserError(ErrorKind.UPDATE_CHECKSUM_MISSING, detail=f"{SUMS_NAME}: 404") from exc
        raise _network_error(exc) from exc
    except OSError as exc:  # URLError, timeouts and connection errors are OSErrors
        raise _network_error(exc) from exc
    expected = parse_sums(raw[:MAX_SUMS_SIZE].decode("utf-8", "replace")).get(update.zip.name)
    if expected is None:
        raise UserError(
            ErrorKind.UPDATE_CHECKSUM_MISSING, detail=f"{update.zip.name} is not in {SUMS_NAME}"
        )
    return expected


def download_update(
    update: UpdateInfo,
    dest_dir: Path,
    progress: ProgressCallback,
    cancel: threading.Event,
    opener: Opener | None = None,
) -> Path:
    """Download the release zip into ``dest_dir`` and verify it; returns the final path.

    Raises ``UserError``: UPDATE_CHECKSUM_MISSING / UPDATE_CHECKSUM_MISMATCH, NETWORK,
    DISK or CANCELLED. On any error nothing is left behind in ``dest_dir``.
    """
    opener = opener or urlopen
    dest_dir = Path(dest_dir)
    if not dest_dir.is_absolute():
        raise ValueError(f"download folder must be absolute: {dest_dir}")
    expected = _expected_sha256(update, opener)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UserError(ErrorKind.DISK, detail=str(exc)) from exc
    part = dest_dir / f"{update.zip.name}.part"
    digest = hashlib.sha256()
    done = 0
    final: Path | None = None
    try:
        with opener(
            _request(update.zip.url, "application/octet-stream"), timeout=DOWNLOAD_TIMEOUT_S
        ) as response:
            total = update.zip.size or int(response.headers.get("Content-Length") or 0)
            progress(0, total)
            with open(part, "wb") as out:
                while chunk := response.read(CHUNK):
                    if cancel.is_set():
                        raise UserError(ErrorKind.CANCELLED)
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, total)
        if cancel.is_set():
            raise UserError(ErrorKind.CANCELLED)
        actual = digest.hexdigest()
        if actual != expected:
            raise UserError(
                ErrorKind.UPDATE_CHECKSUM_MISMATCH,
                detail=f"{update.zip.name}: expected {expected}, got {actual} ({done} bytes)",
            )
        final = reserve_destination(dest_dir, update.zip.name)
        os.replace(part, final)
    except UserError:
        part.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise _network_error(exc) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        part.unlink(missing_ok=True)
        raise _network_error(exc) from exc
    except OSError as exc:
        part.unlink(missing_ok=True)
        if final is not None and final.exists() and final.stat().st_size == 0:
            final.unlink(missing_ok=True)  # the name reserved for the move
        raise UserError(ErrorKind.DISK, detail=str(exc)) from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    log.info("Downloaded and verified %s (sha256 %s)", final, actual)
    return final


def now_utc() -> datetime:
    return datetime.now(UTC)
