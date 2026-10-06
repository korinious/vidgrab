import pytest
from yt_dlp.utils import DownloadError, ExtractorError

from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.extractor import fetch_info, validate_url
from vidgrab.core.models import CookieConfig, CookieSource


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  https://www.youtube.com/watch?v=abc  ", "https://www.youtube.com/watch?v=abc"),
        ("youtu.be/abc", "https://youtu.be/abc"),
        ("http://x.com/a/status/1", "http://x.com/a/status/1"),
    ],
)
def test_validate_url_ok(raw, expected):
    assert validate_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "hello", "ftp://x.com/a", "file:///C:/x", "https://"])
def test_validate_url_rejects(raw):
    with pytest.raises(UserError) as ei:
        validate_url(raw)
    assert ei.value.kind is ErrorKind.INVALID_URL


def test_fetch_info_returns_metadata(fake_ydl, binaries):
    info = fetch_info("https://youtu.be/abc123", binaries, ydl_factory=fake_ydl)
    assert info.title == "Test video"
    assert info.duration == 61
    assert info.thumbnail_url == "https://img.example/abc123.jpg"
    (ydl,) = fake_ydl.instances
    assert ydl.extract_calls == [("https://youtu.be/abc123", False)]


def test_fetch_info_passes_shared_options(fake_ydl, binaries):
    fetch_info(
        "https://www.instagram.com/p/xyz/",
        binaries,
        CookieConfig(CookieSource.FIREFOX),
        ydl_factory=fake_ydl,
    )
    params = fake_ydl.last_params
    assert params["noplaylist"] is True
    assert params["skip_download"] is True
    assert params["cookiesfrombrowser"] == ("firefox",)
    assert params["js_runtimes"] == {"deno": {"path": str(binaries.deno)}}
    assert params["ffmpeg_location"] == str(binaries.ffmpeg.parent)


def test_fetch_info_maps_errors(fake_ydl, binaries):
    inner = ExtractorError("Private video. Sign in if you've been granted access", expected=True)
    fake_ydl.scenario.error = DownloadError(f"ERROR: {inner}", (type(inner), inner, None))
    with pytest.raises(UserError) as ei:
        fetch_info("https://youtu.be/abc123", binaries, ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.PRIVATE


def test_fetch_info_rejects_playlists(fake_ydl, binaries):
    fake_ydl.scenario.info = {"_type": "playlist", "id": "PL1", "entries": []}
    with pytest.raises(UserError) as ei:
        fetch_info("https://www.youtube.com/playlist?list=PL1", binaries, ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.PLAYLIST_NOT_SUPPORTED


def test_fetch_info_invalid_url_never_calls_ytdlp(fake_ydl, binaries):
    with pytest.raises(UserError):
        fetch_info("not a url", binaries, ydl_factory=fake_ydl)
    assert fake_ydl.instances == []


def test_missing_cookie_file_is_reported(fake_ydl, binaries):
    with pytest.raises(UserError) as ei:
        fetch_info(
            "https://www.instagram.com/p/xyz/",
            binaries,
            CookieConfig(CookieSource.FILE, "/nope/cookies.txt"),
            ydl_factory=fake_ydl,
        )
    assert ei.value.kind is ErrorKind.COOKIES_FAILED
