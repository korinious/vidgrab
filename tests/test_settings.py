import json

import pytest

from vidgrab.core.models import CookieConfig, CookieSource, Quality
from vidgrab.core.settings import (
    DEFAULT_CONCURRENT,
    MAX_CONCURRENT,
    Settings,
    load_settings,
    save_settings,
)


def test_defaults_when_missing(tmp_path):
    s = load_settings(tmp_path / "nope.json")
    assert s == Settings()
    assert s.max_concurrent == DEFAULT_CONCURRENT == 2
    assert s.quality is Quality.BEST
    assert s.cookie_source is CookieSource.NONE


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    s = Settings(
        output_dir="D:/Videos",
        quality=Quality.AUDIO_MP3,
        cookie_source=CookieSource.FILE,
        cookie_file="C:/c.txt",
        max_concurrent=3,
    )
    save_settings(s, path)
    assert load_settings(path) == s
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["quality"] == "audio_mp3"
    assert data["cookie_source"] == "file"
    assert list(path.parent.iterdir()) == [path]  # no temp files left behind


def test_greek_paths_survive(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(output_dir="C:/Χρήστες/Βίντεο"), path)
    assert load_settings(path).output_dir == "C:/Χρήστες/Βίντεο"


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()


@pytest.mark.parametrize(
    ("data", "check"),
    [
        ({"quality": "4k"}, lambda s: s.quality is Quality.BEST),
        ({"cookie_source": "opera"}, lambda s: s.cookie_source is CookieSource.NONE),
        ({"max_concurrent": 99}, lambda s: s.max_concurrent == MAX_CONCURRENT),
        ({"max_concurrent": 0}, lambda s: s.max_concurrent == 1),
        ({"max_concurrent": True}, lambda s: s.max_concurrent == DEFAULT_CONCURRENT),
        ({"output_dir": ""}, lambda s: s.output_dir == Settings().output_dir),
        ([1, 2, 3], lambda s: s == Settings()),
    ],
)
def test_bad_fields_fall_back(tmp_path, data, check):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check(load_settings(path))


def test_cookies_property():
    s = Settings(cookie_source=CookieSource.FIREFOX)
    assert s.cookies == CookieConfig(CookieSource.FIREFOX, None)
