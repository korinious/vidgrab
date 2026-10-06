import itertools

import pytest

from vidgrab.core.formats import MP4_FORMAT_SORT, format_options
from vidgrab.core.models import MP3_BITRATES, AudioFormat, Quality, VideoContainer

VIDEO_QUALITIES = [Quality.BEST, Quality.P1080, Quality.P720]


def postprocessor_keys(opts):
    return [pp["key"] for pp in opts.get("postprocessors", [])]


@pytest.mark.parametrize(("quality", "height"), [(Quality.P1080, 1080), (Quality.P720, 720)])
@pytest.mark.parametrize("container", list(VideoContainer))
def test_height_capped_formats(quality, height, container):
    opts = format_options(quality, container)
    assert f"[height<={height}]" in opts["format"]


@pytest.mark.parametrize("container", list(VideoContainer))
def test_best_has_no_height_cap(container):
    assert format_options(Quality.BEST, container)["format"] == "bv*+ba/b"


@pytest.mark.parametrize("quality", VIDEO_QUALITIES)
def test_mp4(quality):
    opts = format_options(quality, VideoContainer.MP4)
    # resolution first, then prefer mp4 video + m4a audio
    assert opts["format_sort"] == ["res", "ext:mp4:m4a"]
    assert opts["format_sort"][0] == "res"
    assert opts["merge_output_format"] == "mp4"
    assert opts["postprocessors"] == [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]
    # never a video re-encode
    assert "FFmpegVideoConvertor" not in postprocessor_keys(opts)
    assert "FFmpegExtractAudio" not in postprocessor_keys(opts)


def test_format_sort_is_a_copy():
    format_options(Quality.BEST, VideoContainer.MP4)["format_sort"].append("junk")
    assert format_options(Quality.BEST, VideoContainer.MP4)["format_sort"] == MP4_FORMAT_SORT


@pytest.mark.parametrize("quality", VIDEO_QUALITIES)
def test_mkv_keeps_original_streams(quality):
    opts = format_options(quality, VideoContainer.MKV)
    assert "format_sort" not in opts  # no codec/ext preference: originals as ranked by yt-dlp
    assert opts["merge_output_format"] == "mkv"
    # remux only (container change); no conversion postprocessors
    assert opts["postprocessors"] == [{"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"}]


@pytest.mark.parametrize("bitrate", MP3_BITRATES)
def test_audio_mp3_bitrates(bitrate):
    opts = format_options(Quality.AUDIO, audio_format=AudioFormat.MP3, mp3_bitrate=bitrate)
    assert opts["format"] == "ba/b"
    (pp,) = opts["postprocessors"]
    assert pp == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": str(bitrate),
    }
    assert "merge_output_format" not in opts


def test_audio_mp3_default_bitrate_is_192():
    (pp,) = format_options(Quality.AUDIO)["postprocessors"]
    assert pp["preferredquality"] == "192"


@pytest.mark.parametrize("bitrate", [0, 96, 193, 512])
def test_audio_mp3_rejects_other_bitrates(bitrate):
    with pytest.raises(ValueError):
        format_options(Quality.AUDIO, audio_format=AudioFormat.MP3, mp3_bitrate=bitrate)


def test_audio_original_copies_stream():
    opts = format_options(Quality.AUDIO, audio_format=AudioFormat.ORIGINAL, mp3_bitrate=320)
    assert opts["format"] == "ba/b"
    # "best" = keep the source codec (m4a/opus); yt-dlp copies instead of converting
    assert opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}]


def test_audio_ignores_container_and_video_ignores_audio_choices():
    a = format_options(Quality.AUDIO, VideoContainer.MP4, AudioFormat.ORIGINAL)
    b = format_options(Quality.AUDIO, VideoContainer.MKV, AudioFormat.ORIGINAL)
    assert a == b
    c = format_options(Quality.P720, VideoContainer.MKV, AudioFormat.MP3, 128)
    d = format_options(Quality.P720, VideoContainer.MKV, AudioFormat.ORIGINAL, 320)
    assert c == d


def test_plain_string_values_are_accepted():
    assert format_options("audio", "mkv", "mp3", 256) == format_options(  # type: ignore[arg-type]
        Quality.AUDIO, VideoContainer.MKV, AudioFormat.MP3, 256
    )
    assert format_options("720p", "mkv") == format_options(  # type: ignore[arg-type]
        Quality.P720, VideoContainer.MKV
    )


ALL_COMBOS = [
    *itertools.product(VIDEO_QUALITIES, VideoContainer, [AudioFormat.MP3], [192]),
    *itertools.product([Quality.AUDIO], [VideoContainer.MP4], [AudioFormat.MP3], MP3_BITRATES),
    (Quality.AUDIO, VideoContainer.MP4, AudioFormat.ORIGINAL, 192),
]


class _Collect:
    def __init__(self):
        self.warnings = []

    def debug(self, msg):
        pass

    info = debug

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        self.warnings.append(msg)


@pytest.mark.parametrize(("quality", "container", "audio", "bitrate"), ALL_COMBOS)
def test_every_combination_is_accepted_by_yt_dlp(quality, container, audio, bitrate):
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor import get_postprocessor
    from yt_dlp.utils import FormatSorter

    opts = format_options(quality, container, audio, bitrate)
    logger = _Collect()
    with YoutubeDL({"quiet": True, "logger": logger, **opts}) as ydl:
        ydl.build_format_selector(opts["format"])  # raises on an invalid format spec
        FormatSorter(ydl, opts.get("format_sort", []))  # warns on unknown sort fields
        for pp in opts.get("postprocessors", []):
            args = {k: v for k, v in pp.items() if k != "key"}
            get_postprocessor(pp["key"])(ydl, **args)  # raises on a bad key/argument
    assert logger.warnings == []


def _fmt(fid, ext, height=None, vcodec="none", acodec="none", abr=None):
    f = {
        "format_id": fid,
        "ext": ext,
        "vcodec": vcodec,
        "acodec": acodec,
        "url": f"https://x/{fid}",
    }
    if height:
        f.update(height=height, width=height * 16 // 9)
    if abr:
        f["abr"] = abr
    return f


def _ranked(format_sort):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import FormatSorter

    formats = [
        _fmt("webm1080", "webm", 1080, vcodec="vp9"),
        _fmt("mp41080", "mp4", 1080, vcodec="avc1"),
        _fmt("webm1440", "webm", 1440, vcodec="vp9"),
        _fmt("opus", "webm", acodec="opus", abr=160),
        _fmt("m4a", "m4a", acodec="mp4a.40.2", abr=128),
    ]
    with YoutubeDL({"quiet": True}) as ydl:
        sorter = FormatSorter(ydl, format_sort)
        return [
            f["format_id"] for f in sorted(formats, key=sorter.calculate_preference, reverse=True)
        ]


def test_mp4_sort_puts_resolution_first_then_mp4_and_m4a():
    ranked = _ranked(MP4_FORMAT_SORT)
    assert ranked.index("webm1440") < ranked.index("mp41080")  # resolution beats container
    assert ranked.index("mp41080") < ranked.index("webm1080")  # same res: mp4 preferred
    assert ranked.index("m4a") < ranked.index("opus")  # AAC audio preferred: no conversion
    # yt-dlp's default would pick opus for audio, which an MP4 would then have to convert
    default = _ranked([])
    assert default.index("opus") < default.index("m4a")


@pytest.mark.parametrize(("quality", "container", "audio", "bitrate"), ALL_COMBOS)
def test_403_fallback_options_are_valid_for_yt_dlp(quality, container, audio, bitrate):
    from yt_dlp import YoutubeDL

    from vidgrab.core.downloader import _apply_forbidden_fallback

    opts = format_options(quality, container, audio, bitrate)
    changes = _apply_forbidden_fallback(
        opts, "https://www.youtube.com/watch?v=x", ["401", "140-16"]
    )
    assert len(changes) == 2
    logger = _Collect()
    with YoutubeDL({"quiet": True, "logger": logger, **opts}) as ydl:
        ydl.build_format_selector(opts["format"])
        assert ydl.params["extractor_args"]["youtube"]["player_client"][0] == "default"
    assert logger.warnings == []


def test_exclude_format_ids_selects_next_best():
    from yt_dlp import YoutubeDL

    from vidgrab.core.formats import exclude_format_ids

    spec = exclude_format_ids(format_options(Quality.BEST)["format"], ["401", "140-16"])
    formats = [
        _fmt("401", "mp4", 2160, vcodec="av01"),
        _fmt("400", "mp4", 1440, vcodec="av01"),
        _fmt("140-16", "m4a", acodec="mp4a.40.2", abr=129),
        _fmt("140", "m4a", acodec="mp4a.40.2", abr=128),
    ]
    with YoutubeDL({"quiet": True}) as ydl:
        chosen = next(
            ydl.build_format_selector(spec)(
                {"formats": formats, "has_merged_format": False, "incomplete_formats": False}
            )
        )
    assert [f["format_id"] for f in chosen["requested_formats"]] == ["400", "140"]


# --- resolution check -------------------------------------------------------------------

from vidgrab.core.formats import actual_height, requested_height, video_height  # noqa: E402


def _v(height, fid="x", **kw):
    return {"format_id": fid, "height": height, "vcodec": "vp9", "ext": "webm", **kw}


AUDIO = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}


def test_video_height_ignores_non_video():
    assert video_height(_v(1080)) == 1080
    assert video_height(AUDIO) is None
    assert video_height({"height": 90, "ext": "mhtml", "vcodec": "none"}) is None  # storyboard
    assert video_height(_v(2160, has_drm=True)) is None
    assert video_height(_v(None)) is None


@pytest.mark.parametrize(
    ("quality", "heights", "attempted", "expected"),
    [
        (Quality.BEST, [2160, 1440, 1080], [], 2160),
        (Quality.P1080, [2160, 1440, 1080, 720], [], 1080),
        (Quality.P1080, [720, 480], [], 720),  # no 1080p exists: 720p is what you can get
        (Quality.P720, [2160, 1080], [], None),  # nothing at or below 720p
        (Quality.BEST, [1440], [2160], 2160),  # 4K was tried before a 403, then gone
        (Quality.P1080, [720], [2160], 720),  # attempted 4K is above the 1080p cap
        (Quality.AUDIO, [2160], [], None),
    ],
)
def test_requested_height(quality, heights, attempted, expected):
    info = {"formats": [AUDIO, *(_v(h) for h in heights)]}
    assert requested_height(quality, info, attempted) == expected


def test_actual_height():
    assert actual_height({"requested_formats": [_v(1440), AUDIO]}) == 1440
    assert actual_height({"height": 720, "vcodec": "avc1"}) == 720  # single-file format
    assert actual_height({"requested_formats": [AUDIO]}) is None
    assert actual_height(None) is None
