import pytest

from vidgrab.core.cookies import COOKIE_SOURCES_ORDER, cookie_options
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.models import CookieConfig, CookieSource


def test_none():
    assert cookie_options(CookieConfig()) == {}


@pytest.mark.parametrize(
    ("source", "browser"),
    [
        (CookieSource.FIREFOX, "firefox"),
        (CookieSource.CHROME, "chrome"),
        (CookieSource.EDGE, "edge"),
    ],
)
def test_browsers(source, browser):
    assert cookie_options(CookieConfig(source)) == {"cookiesfrombrowser": (browser,)}


def test_file(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    assert cookie_options(CookieConfig(CookieSource.FILE, str(f))) == {"cookiefile": str(f)}


@pytest.mark.parametrize("path", [None, "/does/not/exist.txt"])
def test_missing_file(path):
    with pytest.raises(UserError) as ei:
        cookie_options(CookieConfig(CookieSource.FILE, path))
    assert ei.value.kind is ErrorKind.COOKIES_FAILED


def test_firefox_listed_first_after_none():
    assert COOKIE_SOURCES_ORDER[:2] == (CookieSource.NONE, CookieSource.FIREFOX)
    assert set(COOKIE_SOURCES_ORDER) == set(CookieSource)
