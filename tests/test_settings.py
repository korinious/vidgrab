import json

import platformdirs
import pytest

from vidgrab.core.models import (
    AudioFormat,
    CookieConfig,
    CookieSource,
    Quality,
    VideoContainer,
)
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


def test_default_output_dir_is_the_users_downloads_folder():
    # Computed per user at runtime, never a hardcoded path.
    expected = platformdirs.user_downloads_path()
    assert Settings().output_dir == str(expected)
    assert expected.is_absolute()


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    s = Settings(
        output_dir=str(tmp_path / "Videos"),
        quality=Quality.AUDIO,
        cookie_source=CookieSource.FILE,
        cookie_file="C:/c.txt",
        max_concurrent=3,
    )
    save_settings(s, path)
    assert load_settings(path) == s
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["quality"] == "audio"
    assert data["cookie_source"] == "file"
    assert list(path.parent.iterdir()) == [path]  # no temp files left behind


def test_greek_paths_survive(tmp_path):
    path = tmp_path / "settings.json"
    greek = str(tmp_path / "Χρήστες" / "Βίντεο")
    save_settings(Settings(output_dir=greek), path)
    assert load_settings(path).output_dir == greek


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
        ({"output_dir": "relative/dir"}, lambda s: s.output_dir == Settings().output_dir),
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


def test_format_defaults():
    s = Settings()
    assert s.video_container is VideoContainer.MP4
    assert s.audio_format is AudioFormat.MP3
    assert s.mp3_bitrate == 192


@pytest.mark.parametrize("container", list(VideoContainer))
@pytest.mark.parametrize("audio", list(AudioFormat))
@pytest.mark.parametrize("bitrate", [128, 192, 256, 320])
def test_format_choices_roundtrip(tmp_path, container, audio, bitrate):
    path = tmp_path / "settings.json"
    s = Settings(video_container=container, audio_format=audio, mp3_bitrate=bitrate)
    save_settings(s, path)
    loaded = load_settings(path)
    assert (loaded.video_container, loaded.audio_format, loaded.mp3_bitrate) == (
        container,
        audio,
        bitrate,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["video_container"] == container.value
    assert data["audio_format"] == audio.value


def test_v010_audio_mp3_quality_is_migrated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"quality": "audio_mp3"}), encoding="utf-8")
    s = load_settings(path)
    assert s.quality is Quality.AUDIO
    assert s.audio_format is AudioFormat.MP3


@pytest.mark.parametrize(
    ("data", "check"),
    [
        ({"video_container": "avi"}, lambda s: s.video_container is VideoContainer.MP4),
        ({"audio_format": "flac"}, lambda s: s.audio_format is AudioFormat.MP3),
        ({"mp3_bitrate": 999}, lambda s: s.mp3_bitrate == 192),
        ({"mp3_bitrate": "320"}, lambda s: s.mp3_bitrate == 192),
        ({"mp3_bitrate": True}, lambda s: s.mp3_bitrate == 192),
    ],
)
def test_bad_format_fields_fall_back(tmp_path, data, check):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check(load_settings(path))
