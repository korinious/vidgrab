"""core/updates.py with a fake HTTP layer (``fake_http`` fixture): never the real network."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
from datetime import UTC, date, datetime, timedelta

import pytest

from vidgrab import __version__
from vidgrab.core import updates
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.settings import Settings
from vidgrab.core.updates import (
    LATEST_RELEASE_API,
    CheckStatus,
    check_for_update,
    download_update,
    parse_sums,
    should_auto_check,
    should_offer,
    ytdlp_is_stale,
)

BASE = "https://github.com/korinious/vidgrab/releases/download"
ZIP = b"PK\x03\x04 fake VidGrab zip " * 1000


def release(
    tag: str = "v9.0.1",
    *,
    draft: bool = False,
    prerelease: bool = False,
    assets: list[str] | None = None,
    body: str = "## Τι νέο\n\n- **Νέο:** κάτι",
) -> dict:
    names = ["VidGrab-9.0.1-win64.zip", "SHA256SUMS.txt"] if assets is None else assets
    version = tag.lstrip("v")
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/korinious/vidgrab/releases/tag/{tag}",
        "body": body,
        "assets": [
            {
                "name": name.replace("9.0.1", version),
                "browser_download_url": f"{BASE}/{tag}/{name.replace('9.0.1', version)}",
                "size": len(ZIP) if name.endswith(".zip") else 100,
            }
            for name in names
        ],
    }


def serve_release(fake_http, data) -> None:
    fake_http.routes[LATEST_RELEASE_API] = json.dumps(data).encode()


def sums_for(content: bytes, name: str = "VidGrab-9.0.1-win64.zip") -> bytes:
    return f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()


# --- version check -------------------------------------------------------------------------


def test_newer_release_is_available(fake_http):
    serve_release(fake_http, release("v9.0.1"))
    result = check_for_update("0.4.0")
    assert result.status is CheckStatus.AVAILABLE
    assert result.update.version == "9.0.1"
    assert result.update.zip.name == "VidGrab-9.0.1-win64.zip"
    assert result.update.sums.name == "SHA256SUMS.txt"
    assert "**Νέο:**" in result.update.notes


@pytest.mark.parametrize("tag", ["v0.4.0", "v0.3.9", "v0.1.0"])
def test_same_or_older_release_is_up_to_date(fake_http, tag):
    serve_release(fake_http, release(tag))
    assert check_for_update("0.4.0").status is CheckStatus.UP_TO_DATE


def test_semver_is_compared_numerically(fake_http):
    serve_release(fake_http, release("v0.10.0"))
    assert check_for_update("0.9.3").status is CheckStatus.AVAILABLE


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_drafts_and_prereleases_are_ignored(fake_http, flag):
    serve_release(fake_http, release("v9.0.1", **{flag: True}))
    assert check_for_update("0.4.0").status is CheckStatus.UP_TO_DATE


def test_release_without_its_zip_yet_is_not_offered(fake_http):
    # The release is created in the GitHub UI; the build attaches the zip ~15 min later.
    serve_release(fake_http, release("v9.0.1", assets=[]))
    assert check_for_update("0.4.0").status is CheckStatus.UP_TO_DATE


def test_release_without_sums_is_offered_but_cannot_be_installed(fake_http):
    serve_release(fake_http, release("v9.0.1", assets=["VidGrab-9.0.1-win64.zip"]))
    result = check_for_update("0.4.0")
    assert result.status is CheckStatus.AVAILABLE and result.update.sums is None


@pytest.mark.parametrize("tag", ["nightly", "v1.2", "v1.2.3-beta", None])
def test_odd_tags_are_ignored(fake_http, tag):
    serve_release(fake_http, release("v9.0.1") | {"tag_name": tag})
    assert check_for_update("0.4.0").status is CheckStatus.UP_TO_DATE


def test_assets_from_elsewhere_are_ignored(fake_http):
    data = release("v9.0.1")
    for asset in data["assets"]:
        asset["browser_download_url"] = "https://evil.example/" + asset["name"]
    serve_release(fake_http, data)
    assert check_for_update("0.4.0").status is CheckStatus.UP_TO_DATE


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("timed out"),
        TimeoutError("timed out"),
        urllib.error.URLError("getaddrinfo failed"),
        urllib.error.HTTPError(LATEST_RELEASE_API, 404, "Not Found", {}, None),
        urllib.error.HTTPError(LATEST_RELEASE_API, 403, "rate limit exceeded", {}, None),
        urllib.error.HTTPError(LATEST_RELEASE_API, 429, "Too Many Requests", {}, None),
        urllib.error.HTTPError(LATEST_RELEASE_API, 500, "Server Error", {}, None),
        ConnectionResetError("reset"),
    ],
    ids=["socket-timeout", "timeout", "offline", "404", "403-rate-limit", "429", "500", "reset"],
)
def test_network_failures_are_silent(fake_http, caplog, failure):
    fake_http.routes[LATEST_RELEASE_API] = failure
    with caplog.at_level("INFO", logger="vidgrab.core.updates"):
        result = check_for_update("0.4.0")  # never raises
    assert result.status is CheckStatus.FAILED and result.update is None
    assert "Update check failed" in caplog.text


@pytest.mark.parametrize("body", [b"not json", b"", b"[1, 2]", b'"text"', b"\xff\xfe"])
def test_invalid_json_is_silent(fake_http, body):
    fake_http.routes[LATEST_RELEASE_API] = body
    assert check_for_update("0.4.0").status is CheckStatus.FAILED


def test_only_the_user_agent_is_sent(fake_http):
    serve_release(fake_http, release("v0.0.1"))
    check_for_update("0.4.0")
    (request,) = fake_http.requests
    assert request.full_url == "https://api.github.com/repos/korinious/vidgrab/releases/latest"
    assert request.get_method() == "GET" and request.data is None
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers == {
        "user-agent": f"VidGrab/{__version__}",
        "accept": "application/vnd.github+json",
    }


# --- when to check -----------------------------------------------------------------------

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def iso(when: datetime) -> str:
    return updates.format_check_time(when)


@pytest.mark.parametrize(
    ("last", "expected"),
    [
        (None, True),
        (iso(NOW - timedelta(hours=1)), False),
        (iso(NOW - timedelta(hours=23, minutes=59)), False),
        (iso(NOW - timedelta(hours=24)), True),
        (iso(NOW - timedelta(days=9)), True),
        (iso(NOW + timedelta(days=2)), True),  # clock was turned back
        ("garbage", True),
    ],
)
def test_auto_check_at_most_once_per_24_hours(last, expected):
    assert should_auto_check(True, last, NOW) is expected


def test_auto_check_switched_off_never_checks():
    assert should_auto_check(False, None, NOW) is False
    assert should_auto_check(False, iso(NOW - timedelta(days=30)), NOW) is False


def test_skip_this_version_hides_it_but_not_the_next(fake_http):
    serve_release(fake_http, release("v9.0.1"))
    update = check_for_update("0.4.0").update
    assert should_offer(update, None)
    assert not should_offer(update, "9.0.1")
    serve_release(fake_http, release("v9.0.2"))
    assert should_offer(check_for_update("0.4.0").update, "9.0.1")


def test_update_settings_round_trip(tmp_path):
    from vidgrab.core.settings import load_settings, save_settings

    path = tmp_path / "settings.json"
    save_settings(
        Settings(
            output_dir=str(tmp_path),
            auto_update_check=False,
            last_update_check=iso(NOW),
            skipped_update_version="9.0.1",
        ),
        path,
    )
    loaded = load_settings(path)
    assert loaded.auto_update_check is False
    assert loaded.last_update_check == iso(NOW)
    assert loaded.skipped_update_version == "9.0.1"
    assert (
        Settings.from_json({"auto_update_check": "no", "skipped_update_version": 5}) == Settings()
    )


# --- old yt-dlp ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "today", "stale"),
    [
        ("2026.08.19", date(2026, 10, 17), False),  # 59 days
        ("2026.08.19", date(2026, 10, 18), False),  # 60 days
        ("2026.08.19", date(2026, 10, 19), True),  # 61 days
        ("2026.8.19", date(2027, 1, 1), True),
        ("2026.08.19.233", date(2026, 8, 20), False),
        ("unknown", date(2030, 1, 1), False),
        (None, date(2030, 1, 1), False),
    ],
)
def test_ytdlp_staleness(version, today, stale):
    assert ytdlp_is_stale(version, today) is stale


# --- download and SHA256 -------------------------------------------------------------------


def available(fake_http, zip_body: bytes = ZIP, sums: bytes | None = None):
    serve_release(fake_http, release("v9.0.1"))
    fake_http.routes[f"{BASE}/v9.0.1/VidGrab-9.0.1-win64.zip"] = zip_body
    if sums is not None:
        fake_http.routes[f"{BASE}/v9.0.1/SHA256SUMS.txt"] = sums
    return check_for_update("0.4.0").update


def test_download_with_matching_sha256(fake_http, tmp_path):
    update = available(fake_http, sums=sums_for(ZIP))
    seen = []
    path = download_update(update, tmp_path, lambda d, t: seen.append((d, t)), threading.Event())
    assert path == tmp_path / "VidGrab-9.0.1-win64.zip"
    assert path.read_bytes() == ZIP
    assert seen[0] == (0, len(ZIP)) and seen[-1] == (len(ZIP), len(ZIP))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["VidGrab-9.0.1-win64.zip"]


def test_existing_file_is_never_overwritten(fake_http, tmp_path):
    (tmp_path / "VidGrab-9.0.1-win64.zip").write_bytes(b"older")
    update = available(fake_http, sums=sums_for(ZIP))
    path = download_update(update, tmp_path, lambda *_: None, threading.Event())
    assert path.name == "VidGrab-9.0.1-win64 (2).zip"
    assert (tmp_path / "VidGrab-9.0.1-win64.zip").read_bytes() == b"older"


def test_sha256_mismatch_deletes_the_file(fake_http, tmp_path):
    update = available(fake_http, zip_body=ZIP[:-1] + b"X", sums=sums_for(ZIP))
    with pytest.raises(UserError) as info:
        download_update(update, tmp_path, lambda *_: None, threading.Event())
    assert info.value.kind is ErrorKind.UPDATE_CHECKSUM_MISMATCH
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "sums",
    [None, b"", sums_for(ZIP, "VidGrab-9.0.0-win64.zip"), b"not a checksum file"],
    ids=["404", "empty", "other-file", "garbage"],
)
def test_missing_sha256_is_an_error(fake_http, tmp_path, sums):
    update = available(fake_http, sums=sums)
    with pytest.raises(UserError) as info:
        download_update(update, tmp_path, lambda *_: None, threading.Event())
    assert info.value.kind is ErrorKind.UPDATE_CHECKSUM_MISSING
    assert list(tmp_path.iterdir()) == []


def test_release_without_sums_asset_is_an_error(fake_http, tmp_path):
    serve_release(fake_http, release("v9.0.1", assets=["VidGrab-9.0.1-win64.zip"]))
    fake_http.routes[f"{BASE}/v9.0.1/VidGrab-9.0.1-win64.zip"] = ZIP
    update = check_for_update("0.4.0").update
    with pytest.raises(UserError) as info:
        download_update(update, tmp_path, lambda *_: None, threading.Event())
    assert info.value.kind is ErrorKind.UPDATE_CHECKSUM_MISSING
    assert list(tmp_path.iterdir()) == []
    # The zip was never even requested.
    assert all(not r.full_url.endswith(".zip") for r in fake_http.requests)


def test_cancel_leaves_nothing_behind(fake_http, tmp_path):
    update = available(fake_http, sums=sums_for(ZIP))
    cancel = threading.Event()

    def progress(done, total):
        if done > 0:
            cancel.set()

    with pytest.raises(UserError) as info:
        download_update(update, tmp_path, progress, cancel)
    assert info.value.kind is ErrorKind.CANCELLED
    assert list(tmp_path.iterdir()) == []


def test_network_error_during_download(fake_http, tmp_path):
    update = available(fake_http, sums=sums_for(ZIP))
    fake_http.routes[update.zip.url] = ConnectionResetError("reset")
    with pytest.raises(UserError) as info:
        download_update(update, tmp_path, lambda *_: None, threading.Event())
    assert info.value.kind is ErrorKind.NETWORK
    assert list(tmp_path.iterdir()) == []


def test_relative_download_folder_is_rejected(fake_http):
    update = available(fake_http, sums=sums_for(ZIP))
    with pytest.raises(ValueError):
        download_update(update, "Downloads", lambda *_: None, threading.Event())


def test_parse_sums_formats():
    h = "a" * 64
    assert parse_sums(f"{h}  a.zip\r\n{h.upper()} *b.zip\n# comment\nbad line\n") == {
        "a.zip": h,
        "b.zip": h,
    }
