import pytest

from vidgrab.core.formats import format_options
from vidgrab.core.models import Quality


@pytest.mark.parametrize(("quality", "height"), [(Quality.P1080, 1080), (Quality.P720, 720)])
def test_height_capped_formats(quality, height):
    opts = format_options(quality)
    assert f"[height<={height}]" in opts["format"]
    assert opts["merge_output_format"].startswith("mp4")
    assert "postprocessors" not in opts


def test_best():
    opts = format_options(Quality.BEST)
    assert opts["format"] == "bv*+ba/b"
    assert "height" not in opts["format"]


def test_audio_mp3():
    opts = format_options(Quality.AUDIO_MP3)
    assert opts["format"] == "ba/b"
    (pp,) = opts["postprocessors"]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert "merge_output_format" not in opts


@pytest.mark.parametrize("quality", list(Quality))
def test_every_quality_has_a_valid_yt_dlp_format(quality):
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True}) as ydl:
        # Raises SyntaxError on an invalid format spec.
        ydl.build_format_selector(format_options(quality)["format"])
