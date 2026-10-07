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


# --- errors reported from Windows testing: none of these may end up as "unknown" -------

import io  # noqa: E402

from yt_dlp.networking import Response  # noqa: E402
from yt_dlp.networking.exceptions import HTTPError  # noqa: E402
from yt_dlp.utils import PostProcessingError  # noqa: E402


def http_error(status):
    return HTTPError(Response(io.BytesIO(b""), "https://x", {}, status=status))


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        # exact message from the WinError 32 report
        (
            DownloadError(
                "ERROR: Unable to rename file: [WinError 32] The process cannot access the file "
                "because it is being used by another process: "
                "'C:\\\\Users\\\\u\\\\Downloads\\\\t [x5d2DKqraZk].f401.mp4.part' -> "
                "'C:\\\\Users\\\\u\\\\Downloads\\\\t [x5d2DKqraZk].f401.mp4'. "
                "Giving up after 3 retries"
            ),
            ErrorKind.FILE_LOCKED,
        ),
        # exact message from the 403 report
        (
            DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden"),
            ErrorKind.FORBIDDEN,
        ),
        (wrapped(http_error(403)), ErrorKind.FORBIDDEN),
        (http_error(429), ErrorKind.RATE_LIMITED),
        (
            DownloadError(
                "ERROR: unable to download video data: HTTP Error 429: Too Many Requests"
            ),
            ErrorKind.RATE_LIMITED,
        ),
        (PostProcessingError("Conversion failed!"), ErrorKind.POSTPROCESSING),
        (wrapped(PostProcessingError("Conversion failed!")), ErrorKind.POSTPROCESSING),
    ],
)
def test_reported_errors_are_never_unknown(exc, kind):
    err = classify(exc)
    assert err.kind is kind
    assert err.kind is not ErrorKind.UNKNOWN
    assert err.message == MESSAGES[kind]


def test_forbidden_message_text():
    assert MESSAGES[ErrorKind.FORBIDDEN] == (
        "Το YouTube αρνήθηκε τη λήψη (403). Δοκίμασε χαμηλότερη ποιότητα, cookies από browser, "
        "ή ξανά σε λίγα λεπτά."
    )
    assert MESSAGES[ErrorKind.FILE_LOCKED] == (
        "Το αρχείο χρησιμοποιείται από άλλο πρόγραμμα, π.χ. antivirus ή OneDrive. "
        "Δοκίμασε ξανά ή άλλαξε φάκελο λήψεων."
    )


def test_login_required_403_stays_login_required():
    # Instagram/Facebook answer 403 when cookies are needed; the message must say so.
    inner = ExtractorError(
        "Requested content is not available, rate-limit reached or login required",
        cause=http_error(403),
        expected=True,
    )
    assert classify(wrapped(inner)).kind is ErrorKind.LOGIN_REQUIRED


def test_ffmpeg_missing_beats_generic_postprocessing():
    exc = PostProcessingError("ffprobe and ffmpeg not found. Please install or provide the path")
    assert classify(exc).kind is ErrorKind.FFMPEG_MISSING


def test_empty_listing_message_and_not_retryable():
    err = UserError(ErrorKind.EMPTY_LISTING, detail="https://x/list")
    assert err.message == "Δεν βρέθηκαν διαθέσιμα βίντεο σε αυτόν τον σύνδεσμο."
    assert not err.retryable
