import pytest

from vidgrab.core.models import JobStatus, Phase, Progress, VideoInfo, format_duration


def test_video_info_from_info_dict():
    info = {
        "id": "abc",
        "title": "Hello",
        "duration": 125.4,
        "thumbnail": "https://img/x.jpg",
        "uploader": "Someone",
        "webpage_url": "https://www.youtube.com/watch?v=abc",
        "extractor_key": "Youtube",
    }
    v = VideoInfo.from_info_dict("https://youtu.be/abc", info)
    assert v.url == "https://www.youtube.com/watch?v=abc"
    assert v.title == "Hello"
    assert v.duration == 125
    assert v.thumbnail_url == "https://img/x.jpg"
    assert v.uploader == "Someone"
    assert v.extractor == "Youtube"


def test_video_info_falls_back_to_thumbnails_list_and_url():
    info = {"id": "x1", "thumbnails": [{"url": "low"}, {"url": "high"}]}
    v = VideoInfo.from_info_dict("https://x.com/a/status/1", info)
    assert v.thumbnail_url == "high"
    assert v.title == "x1"
    assert v.url == "https://x.com/a/status/1"
    assert v.duration is None


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, None), (-1, None), (0, "0:00"), (65, "1:05"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_progress_fractions():
    p = Progress(downloaded_bytes=50, total_bytes=100, stream_index=2, stream_count=2)
    assert p.stream_fraction == 0.5
    assert p.overall_fraction == 0.75
    assert Progress(total_bytes=None).overall_fraction is None
    assert Progress(phase=Phase.POSTPROCESSING).overall_fraction == 1.0
    assert Progress(downloaded_bytes=200, total_bytes=100).stream_fraction == 1.0


def test_job_status_groups():
    assert JobStatus.DOWNLOADING.is_active
    assert JobStatus.CANCELLING.is_active
    assert not JobStatus.QUEUED.is_active
    assert JobStatus.FAILED.is_finished
    assert not JobStatus.QUEUED.is_finished


def test_video_info_max_height():
    formats = [
        {"format_id": "140", "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "137", "height": 1080, "vcodec": "avc1"},
        {"format_id": "401", "height": 2160, "vcodec": "av01"},
        {"format_id": "sb0", "height": 90, "ext": "mhtml", "vcodec": "none"},
    ]
    assert VideoInfo.from_info_dict("u", {"id": "x", "formats": formats}).max_height == 2160
    assert VideoInfo.from_info_dict("u", {"id": "x", "height": 720}).max_height == 720
    assert VideoInfo.from_info_dict("u", {"id": "x"}).max_height is None
