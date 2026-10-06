import pytest
from yt_dlp.cookies import CookieLoadError
from yt_dlp.networking.exceptions import TransportError
from yt_dlp.utils import (
    DownloadCancelled,
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    UnsupportedError,
)

from vidgrab import strings
from vidgrab.core.errors import MESSAGES, ErrorKind, UserError, classify, clean_message


def wrapped(inner: BaseException) -> DownloadError:
    """Mimic how YoutubeDL wraps extractor errors."""
    return DownloadError(f"ERROR: {inner}", exc_info=(type(inner), inner, None))


def extractor_error(msg: str) -> ExtractorError:
    return ExtractorError(msg, expected=True, video_id="abc123", ie="youtube")


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        (
            "Private video. Sign in if you've been granted access to this video. "
            "Use --cookies-from-browser or --cookies for the authentication.",
            ErrorKind.PRIVATE,
        ),
        (
            "Sign in to confirm your age. This video may be inappropriate for some users. "
            "Use --cookies-from-browser or --cookies for the authentication.",
            ErrorKind.AGE_RESTRICTED,
        ),
        (
            "Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies",
            ErrorKind.LOGIN_REQUIRED,
        ),
        (
            "Requested content is not available, rate-limit reached or login required. "
            "Use --cookies, --cookies-from-browser",
            ErrorKind.LOGIN_REQUIRED,
        ),
        ("This video is not available in your country", ErrorKind.GEO_BLOCKED),
        (
            "The uploader has not made this video available in your country",
            ErrorKind.GEO_BLOCKED,
        ),
        ("Video unavailable. This video has been removed by the uploader", ErrorKind.UNAVAILABLE),
        ("Requested format is not available", ErrorKind.FORMAT_UNAVAILABLE),
        ("Unable to download webpage: <urlopen error timed out>", ErrorKind.NETWORK),
        ("Unsupported URL: https://example.com/foo", ErrorKind.UNSUPPORTED_URL),
        (
            "ffprobe and ffmpeg not found. Please install or provide the path",
            ErrorKind.FFMPEG_MISSING,
        ),
        ("Could not copy Chrome cookie database. See https://...", ErrorKind.COOKIES_FAILED),
        ("Failed to decrypt with DPAPI. See https://...", ErrorKind.COOKIES_FAILED),
        ("[Errno 28] No space left on device", ErrorKind.DISK),
        ("something nobody anticipated", ErrorKind.UNKNOWN),
    ],
)
def test_message_patterns(message, kind):
    err = classify(wrapped(extractor_error(message)))
    assert err.kind is kind
    assert err.message == MESSAGES[kind]


def test_plain_download_error_without_exc_info():
    err = classify(DownloadError("ERROR: [instagram] xyz: This account is private"))
    assert err.kind is ErrorKind.PRIVATE
    assert err.detail == "This account is private"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (GeoRestrictedError("blocked", countries=["US"]), ErrorKind.GEO_BLOCKED),
        (UnsupportedError("https://example.com"), ErrorKind.UNSUPPORTED_URL),
        (CookieLoadError("failed to load cookies"), ErrorKind.COOKIES_FAILED),
        (DownloadCancelled(), ErrorKind.CANCELLED),
        (TransportError("boom"), ErrorKind.NETWORK),
        (ConnectionResetError(), ErrorKind.NETWORK),
        (PermissionError(13, "nope"), ErrorKind.DISK),
    ],
)
def test_exception_types(exc, kind):
    assert classify(exc).kind is kind
    assert classify(wrapped(exc)).kind is kind


def test_extractor_error_cause_is_followed():
    try:
        raise ConnectionResetError("reset")
    except ConnectionResetError as cause:
        exc = ExtractorError("Unable to fetch", cause=cause, expected=True)
    assert classify(wrapped(exc)).kind is ErrorKind.NETWORK


def test_user_error_passthrough():
    original = UserError(ErrorKind.INVALID_URL)
    assert classify(original) is original
    assert classify(wrapped(original)) is original


def test_unknown_keeps_detail():
    err = classify(RuntimeError("weird thing"))
    assert err.kind is ErrorKind.UNKNOWN
    assert err.detail == "weird thing"
    assert err.message == strings.ERR_UNKNOWN


def test_retryable():
    assert UserError(ErrorKind.NETWORK).retryable
    assert not UserError(ErrorKind.UNSUPPORTED_URL).retryable


def test_every_kind_has_a_message():
    assert set(MESSAGES) == set(ErrorKind)
    assert all(MESSAGES.values())


def test_cookies_failed_message_recommends_firefox():
    assert "Firefox" in MESSAGES[ErrorKind.COOKIES_FAILED]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("ERROR: [youtube] abc123: Private video", "Private video"),
        ("ERROR: Unsupported URL: https://x", "Unsupported URL: https://x"),
        ("\x1b[0;31mERROR:\x1b[0m [generic] boom", "boom"),
        ("plain", "plain"),
    ],
)
def test_clean_message(raw, clean):
    assert clean_message(raw) == clean
