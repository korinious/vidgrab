"""Core support for playlists and multi-video posts (no Qt)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from conftest import instagram_carousel, x_post, yt_flat_entry, yt_playlist
from vidgrab.core import archive
from vidgrab.core.downloader import download
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.extractor import fetch_info, fetch_listing, has_video_and_list, probe
from vidgrab.core.filenames import name_problems, numbered_name, sanitize_filename
from vidgrab.core.jobqueue import Cooldown, DownloadQueue, platform_key
from vidgrab.core.models import (
    DownloadRequest,
    EntryState,
    JobStatus,
    Listing,
    Quality,
    VideoInfo,
)
from vidgrab.core.settings import Settings

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLtest"


# --- file names ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Normal title", "Normal title"),
        ('a<b>c:d"e/f\\g|h?i*j', "a b c -d'e-f-g-h i j"),
        ("trailing dots...", "trailing dots"),
        ("  spaces   inside  ", "spaces inside"),
        ("CON", "CON_"),
        ("nul.txt", "nul_.txt"),
        ("", "video"),
        ("???", "video"),
        ("tab\tand\nnewline", "tab and newline"),
        ("Ελληνικά: τίτλος", "Ελληνικά - τίτλος"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["a" * 400, "x. . .", "COM1.mp4", 'q"u:o*t?e', "\x00\x1fctrl", "LPT9 ", " .hidden"],
)
def test_sanitized_names_pass_the_repo_path_check(raw):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("check_paths", root / "scripts/check_paths.py")
    check_paths = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_paths)
    name = sanitize_filename(raw)
    assert name and len(name) <= 150
    assert name_problems(name) == []
    assert check_paths.windows_path_problems(f"dir/{name}.mp4") == []


def test_numbered_name_uses_list_position_and_width():
    assert numbered_name(3, 48, "Title") == "03 - Title"
    assert numbered_name(7, 120, "Title") == "007 - Title"
    assert numbered_name(1, 5, "T") == "01 - T"


# --- download history ----------------------------------------------------------------------


def test_archive_record_load_count_clear(download_archive):
    assert archive.default_archive_path() == download_archive
    assert archive.load_keys() == set()
    archive.record("youtube a")
    archive.record("youtube a")  # no duplicates
    archive.record("instagram b")
    archive.record(None)
    assert archive.load_keys() == {"youtube a", "instagram b"}
    assert download_archive.read_text(encoding="utf-8") == "youtube a\ninstagram b\n"
    assert archive.count() == 2
    assert archive.clear() == 2
    assert not download_archive.exists()
    assert archive.count() == 0


def test_archive_key_matches_ytdlp():
    assert archive.archive_key("Youtube", "abc") == "youtube abc"
    assert archive.archive_key("youtube:tab", "abc") == "youtube abc"
    assert archive.archive_key(None, "abc") is None


# --- detection ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "list_url"),
    [
        (
            "https://www.youtube.com/watch?v=abc&list=PL1",
            "https://www.youtube.com/playlist?list=PL1",
        ),
        ("https://youtu.be/abc?list=PL2", "https://www.youtube.com/playlist?list=PL2"),
        ("https://www.youtube.com/watch?v=abc", None),
        ("https://www.youtube.com/playlist?list=PL1", None),
        ("https://example.com/watch?v=a&list=b", None),
    ],
)
def test_has_video_and_list(url, list_url):
    assert has_video_and_list(url) == list_url


def test_probe_returns_listing_from_flat_extraction(fake_ydl, binaries, download_archive):
    archive.record("youtube vid002")
    fake_ydl.scenario.info = yt_playlist(
        3,
        [
            yt_flat_entry(4, title="[Private video]"),
            yt_flat_entry(5, title="[Deleted video]"),
            yt_flat_entry(6, availability="subscriber_only"),
        ],
    )
    result = probe(PLAYLIST_URL, binaries, ydl_factory=fake_ydl)
    assert isinstance(result, Listing)
    params = fake_ydl.last_params
    assert params["extract_flat"] == "in_playlist"
    assert params["noplaylist"] is False
    assert result.title == "Λίστα δοκιμής"
    assert [e.position for e in result.entries] == [1, 2, 3, 4, 5, 6]
    assert [e.state for e in result.entries] == [EntryState.AVAILABLE] * 3 + [
        EntryState.PRIVATE,
        EntryState.UNAVAILABLE,
        EntryState.PRIVATE,
    ]
    first = result.entries[0]
    assert first.url == "https://www.youtube.com/watch?v=vid001"
    assert first.playlist_item is None
    assert first.duration == 61
    assert first.thumbnail_url == "https://i.ytimg.com/vi/vid001/hqdefault.jpg"
    assert first.archive_key == "youtube vid001"
    assert result.total_duration == 61 + 62 + 63
    # one extract_info only: no full extraction per entry before the user chooses
    assert sum(len(y.extract_calls) for y in fake_ydl.instances) == 1


def test_probe_single_video(fake_ydl, binaries):
    result = probe("https://youtu.be/abc123", binaries, ydl_factory=fake_ydl)
    assert isinstance(result, VideoInfo)
    assert result.list_url is None and result.playlist_item is None


def test_probe_video_and_list_fetches_the_video_and_offers_the_list(fake_ydl, binaries):
    fake_ydl.scenario.single_info = dict(fake_ydl.scenario.info)
    fake_ydl.scenario.info = yt_playlist(3)
    result = probe(
        "https://www.youtube.com/watch?v=abc123&list=PLtest", binaries, ydl_factory=fake_ydl
    )
    assert isinstance(result, VideoInfo)
    assert result.title == "Test video"
    assert result.list_url == PLAYLIST_URL
    assert fake_ydl.last_params["noplaylist"] is True
    listing = fetch_listing(result.list_url, binaries, ydl_factory=fake_ydl)
    assert len(listing.entries) == 3


def test_probe_carousel_skips_photos_and_uses_playlist_items(fake_ydl, binaries):
    fake_ydl.scenario.info = instagram_carousel()
    result = probe("https://www.instagram.com/p/CARO1/", binaries, ydl_factory=fake_ydl)
    assert isinstance(result, Listing)
    assert [(e.position, e.playlist_item) for e in result.entries] == [(1, 1), (3, 3)]
    assert all(e.url == "https://www.instagram.com/p/CARO1/" for e in result.entries)
    assert result.entries[0].archive_key == "instagram ig1"


def test_probe_x_post_with_two_videos(fake_ydl, binaries):
    fake_ydl.scenario.info = x_post(2)
    result = probe("https://x.com/user/status/1700", binaries, ydl_factory=fake_ydl)
    assert isinstance(result, Listing)
    assert [e.title for e in result.entries] == ["user - video 1", "user - video 2"]


def test_probe_list_with_one_video_shows_it_directly(fake_ydl, binaries):
    post = instagram_carousel()
    post["entries"] = post["entries"][:2]  # one video + one photo
    fake_ydl.scenario.info = post
    result = probe("https://www.instagram.com/p/CARO1/", binaries, ydl_factory=fake_ydl)
    assert isinstance(result, VideoInfo)
    assert result.title == "Video by user 1"
    assert result.playlist_item == 1
    assert result.url == "https://www.instagram.com/p/CARO1/"
    assert fake_ydl.last_params["playlist_items"] == "1"


def test_probe_list_without_available_videos(fake_ydl, binaries):
    fake_ydl.scenario.info = yt_playlist(0, [yt_flat_entry(1, title="[Private video]")])
    with pytest.raises(UserError) as ei:
        probe(PLAYLIST_URL, binaries, ydl_factory=fake_ydl)
    assert ei.value.kind is ErrorKind.EMPTY_LISTING


def test_unresolved_entries_are_unavailable_not_fatal(fake_ydl, binaries):
    fake_ydl.scenario.info = yt_playlist(2, [None])
    listing = fetch_listing(PLAYLIST_URL, binaries, ydl_factory=fake_ydl)
    assert [e.state for e in listing.entries][-1] is EntryState.UNAVAILABLE
    assert len(listing.available_entries) == 2


def test_fetch_info_for_one_carousel_item(fake_ydl, binaries):
    fake_ydl.scenario.info = instagram_carousel()
    info = fetch_info(
        "https://www.instagram.com/p/CARO1/", binaries, ydl_factory=fake_ydl, playlist_item=3
    )
    assert info.title == "Video by user 3"
    assert info.playlist_item == 3


# --- downloading list items ------------------------------------------------------------


def _download(fake_ydl, binaries, request, **kw):
    return download(request, binaries, lambda p: None, threading.Event(), fake_ydl, **kw)


def test_download_item_of_a_post_uses_playlist_items(
    fake_ydl, binaries, tmp_path, download_archive
):
    fake_ydl.scenario.info = instagram_carousel()
    fake_ydl.scenario.name_from_outtmpl = True
    request = DownloadRequest(
        "https://www.instagram.com/p/CARO1/",
        Quality.BEST,
        tmp_path / "out" / "Post by user",
        playlist_item=3,
        filename="03 - Video by user 3",
    )
    result = _download(fake_ydl, binaries, request)
    params = fake_ydl.last_params
    assert params["playlist_items"] == "3"
    assert params["noplaylist"] is False
    assert params["outtmpl"]["default"].endswith("03 - Video by user 3.%(ext)s")
    assert result.path == tmp_path / "out" / "Post by user" / "03 - Video by user 3.mp4"
    assert result.path.is_file()
    assert archive.load_keys() == {"instagram ig3"}


def test_single_download_keeps_title_id_name_and_is_recorded(fake_ydl, binaries, tmp_path):
    fake_ydl.scenario.name_from_outtmpl = True
    request = DownloadRequest("https://youtu.be/abc123", Quality.BEST, tmp_path / "out")
    result = _download(fake_ydl, binaries, request)
    assert result.path.name == "Test video [abc123].mp4"
    assert fake_ydl.last_params["noplaylist"] is True
    assert "playlist_items" not in fake_ydl.last_params
    assert archive.load_keys() == {"youtube abc123"}


def test_percent_in_chosen_name_is_not_a_template_field(fake_ydl, binaries, tmp_path):
    fake_ydl.scenario.name_from_outtmpl = True
    request = DownloadRequest(
        "https://youtu.be/abc123", Quality.BEST, tmp_path / "out", filename="100% (live)"
    )
    result = _download(fake_ydl, binaries, request)
    assert fake_ydl.last_params["outtmpl"]["default"].endswith("100%% (live).%(ext)s")
    assert result.path.name == "100% (live).mp4"


def test_failed_download_is_not_recorded(fake_ydl, binaries, tmp_path, download_archive):
    from yt_dlp.utils import DownloadError

    fake_ydl.scenario.error = DownloadError("ERROR: [youtube] abc123: Video unavailable")
    request = DownloadRequest("https://youtu.be/abc123", Quality.BEST, tmp_path / "out")
    with pytest.raises(UserError):
        _download(fake_ydl, binaries, request)
    assert not download_archive.exists()


def test_download_ignores_history_for_single_urls(fake_ydl, binaries, tmp_path):
    """The history only pre-unselects list items; a single URL always downloads."""
    archive.record("youtube abc123")
    fake_ydl.scenario.final_name = "v.mp4"
    request = DownloadRequest("https://youtu.be/abc123", Quality.BEST, tmp_path / "out")
    result = _download(fake_ydl, binaries, request)
    assert result.path.is_file()
    assert "download_archive" not in fake_ydl.last_params


# --- queue: groups and per-platform pause ---------------------------------------------------


def _req(url="https://www.youtube.com/watch?v=1", tmp=Path("/tmp")):
    return DownloadRequest(url, Quality.BEST, tmp)


def test_group_progress_cancel_all_and_retry_failed():
    q = DownloadQueue(max_concurrent=2, cooldown=Cooldown(0, 0))
    group = q.add_group("Λίστα", "youtube", skipped=1)
    jobs = [q.add(_req(f"https://youtu.be/{i}"), group_id=group.id) for i in range(4)]
    single = q.add(_req())
    assert [j.group_id for j in jobs] == [group.id] * 4 and single.group_id is None
    started = q.start_next()
    assert [j.id for j in started] == [jobs[0].id, jobs[1].id]  # global limit of 2
    q.mark_completed(jobs[0].id, None)
    q.mark_failed(jobs[1].id, UserError(ErrorKind.FORBIDDEN))
    progress = q.group_progress(group.id)
    assert (progress.done, progress.total, progress.failed, progress.active) == (1, 4, 1, 2)
    assert progress.fraction == 0.25

    to_signal = q.cancel_group(group.id)
    assert to_signal == []  # nothing of the group was running
    assert jobs[2].status is JobStatus.CANCELLED and jobs[3].status is JobStatus.CANCELLED
    assert single.status is JobStatus.QUEUED  # other jobs untouched

    assert q.retry_failed(group.id) == [jobs[1].id]
    assert jobs[1].status is JobStatus.QUEUED


def test_cancel_group_signals_running_jobs():
    q = DownloadQueue(max_concurrent=2, cooldown=Cooldown(0, 0))
    group = q.add_group("L")
    a = q.add(_req("https://youtu.be/a"), group_id=group.id)
    q.start_next()
    assert q.cancel_group(group.id) == [a.id]
    assert a.status is JobStatus.CANCELLING


def test_retry_failed_skips_not_retryable():
    q = DownloadQueue(cooldown=Cooldown(0, 0))
    group = q.add_group("L")
    job = q.add(_req(), group_id=group.id)
    q.start_next()
    q.mark_failed(job.id, UserError(ErrorKind.UNSUPPORTED_URL))
    assert q.retry_failed(group.id) == []


def test_empty_groups_are_dropped_after_clearing():
    q = DownloadQueue(cooldown=Cooldown(0, 0))
    group = q.add_group("L")
    job = q.add(_req(), group_id=group.id)
    q.start_next()
    q.mark_completed(job.id, None)
    assert q.clear_finished() == [job.id]
    assert q.drop_empty_groups() == [group.id]
    assert q.groups == []


def test_unknown_group_is_rejected():
    with pytest.raises(KeyError):
        DownloadQueue().add(_req(), group_id=99)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_cooldown_spaces_starts_per_platform():
    clock = FakeClock()
    q = DownloadQueue(max_concurrent=3, cooldown=Cooldown(2, 5, clock, lambda lo, hi: 3.0))
    yt1 = q.add(_req("https://www.youtube.com/watch?v=1"))
    yt2 = q.add(_req("https://youtu.be/2"))
    ig = q.add(_req("https://www.instagram.com/p/x/"))
    assert [j.id for j in q.start_next()] == [yt1.id, ig.id]  # yt2 waits for YouTube
    assert yt2.status is JobStatus.QUEUED
    assert q.seconds_until_next_start() == pytest.approx(3.0)
    clock.now += 2.9
    assert q.start_next() == []
    clock.now += 0.2
    assert q.start_next() == [yt2]
    assert q.seconds_until_next_start() is None


def test_cooldown_uses_two_to_five_seconds():
    seen = []

    def rng(lo, hi):
        seen.append((lo, hi))
        return lo

    q = DownloadQueue(cooldown=Cooldown(clock=FakeClock(), rng=rng))
    q.add(_req())
    q.start_next()
    assert seen == [(2.0, 5.0)]


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://www.youtube.com/watch?v=1", "youtube"),
        ("https://youtu.be/1", "youtube"),
        ("https://m.youtube.com/watch?v=1", "youtube"),
        ("https://twitter.com/a/status/1", "x"),
        ("https://x.com/a/status/1", "x"),
        ("https://www.instagram.com/p/1/", "instagram"),
        ("https://www.facebook.com/watch/?v=1", "facebook"),
    ],
)
def test_platform_key(url, key):
    assert platform_key(url) == key


# --- settings ----------------------------------------------------------------------------


def test_list_options_default_on_and_round_trip():
    s = Settings()
    assert (s.list_subfolder, s.list_numbering, s.skip_downloaded) == (True, True, True)
    data = s.to_json()
    data.update(list_subfolder=False, skip_downloaded=False, list_numbering="yes")
    back = Settings.from_json(data)
    assert (back.list_subfolder, back.list_numbering, back.skip_downloaded) == (
        False,
        True,  # invalid value ignored
        False,
    )
    # settings files from v0.2.0 have none of these keys
    old = Settings.from_json({"quality": "best"})
    assert old.skip_downloaded is True
