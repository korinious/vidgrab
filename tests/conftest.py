"""Shared fixtures. FakeYoutubeDL stands in for yt_dlp.YoutubeDL: no network, ever."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from vidgrab.core.binaries import Binaries

# UI tests run headless (also on the Linux dev VM, which has no display).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HookEvent = dict[str, Any]


@dataclass
class FakeScenario:
    """What the next FakeYoutubeDL instances should do."""

    info: dict[str, Any] = field(
        default_factory=lambda: {
            "id": "abc123",
            "title": "Test video",
            "duration": 61,
            "thumbnail": "https://img.example/abc123.jpg",
            "uploader": "Uploader",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "extractor_key": "Youtube",
        }
    )
    error: BaseException | None = None
    # Per download call: the n-th extract_info(download=True) uses attempt_errors[n]
    # (None = succeeds) instead of `error`. Models "403, then 403, then OK".
    attempt_errors: list[BaseException | None] = field(default_factory=list)
    # Each event is passed to the progress hooks. A "create" key (relative file name) makes
    # the fake write that file into the output dir first, like yt-dlp would.
    progress_events: list[HookEvent] = field(default_factory=list)
    postprocessor_events: list[HookEvent] = field(default_factory=list)
    # Called between progress events (index) — lets tests flip a cancel flag mid-download.
    between_events: Callable[[int], None] | None = None
    final_name: str | None = None
    # Returned instead of ``info`` when yt-dlp is asked for one video only (noplaylist=True),
    # e.g. the video of a "watch?v=...&list=..." link while ``info`` is the list.
    single_info: dict[str, Any] | None = None
    # With no final_name: name the finished file like yt-dlp would from the outtmpl
    # ("03 - Title.mp4", "Title [id].mp4"), so list downloads get distinct files.
    name_from_outtmpl: bool = False


class FakeYoutubeDL:
    def __init__(self, params: dict[str, Any], scenario: FakeScenario) -> None:
        self.params = params
        self.scenario = scenario
        self.extract_calls: list[tuple[str, bool]] = []

    def __enter__(self) -> FakeYoutubeDL:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _output_dir(self) -> Path:
        return Path(self.params["outtmpl"]["default"]).parent

    def extract_info(self, url: str, download: bool = True, **_: Any) -> dict[str, Any]:
        self.extract_calls.append((url, download))
        sc = self.scenario
        error = sc.error
        if download and sc.attempt_errors:
            error = sc.attempt_errors.pop(0)
        if error is not None and not sc.progress_events:
            raise error
        info = dict(sc.info)
        if self.params.get("noplaylist") and sc.single_info is not None:
            info = dict(sc.single_info)
        is_list = info.get("_type") in ("playlist", "multi_video")
        if is_list and self.params.get("noplaylist"):
            # A list item's own URL (watch?v=...): yt-dlp returns just that video.
            entry = next(
                (e for e in info["entries"] if isinstance(e, dict) and e.get("url") == url), None
            )
            if entry is not None:
                info = {
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "duration": entry.get("duration"),
                    "extractor_key": entry.get("ie_key"),
                    "webpage_url": url,
                }
                is_list = False
        if not download:
            if is_list and self.params.get("playlist_items"):
                n = int(self.params["playlist_items"])
                info["entries"] = [info["entries"][n - 1]]
            return info
        if is_list and self.params.get("playlist_items"):
            # Download one item of a multi-video post: yt-dlp returns the post as a
            # playlist holding just that entry, with requested_downloads on the entry.
            n = int(self.params["playlist_items"])
            post = info
            entry = self._download_one(dict(post["entries"][n - 1]), sc, error)
            return {**post, "entries": [entry]}
        return self._download_one(info, sc, error)

    def _download_one(
        self, info: dict[str, Any], sc: FakeScenario, error: BaseException | None
    ) -> dict[str, Any]:
        out = self._output_dir()
        for index, event in enumerate(sc.progress_events):
            if sc.between_events:
                sc.between_events(index)
            event = dict(event)
            if "create" in event:
                path = out / event.pop("create")
                path.write_bytes(b"x")
                event["filename"] = str(path)
                event.setdefault("tmpfilename", str(path) + ".part")
            event.setdefault("info_dict", info)
            for hook in self.params.get("progress_hooks", []):
                hook(event)
        if error is not None:
            raise error

        for event in sc.postprocessor_events:
            event = dict(event)
            if "create" in event:  # the postprocessor writes this file (e.g. the .mp3)
                created = out / event.pop("create")
                created.write_bytes(b"pp")
                event["info_dict"] = {**info, "filepath": str(created)}
            event.setdefault("info_dict", info)
            for hook in self.params.get("postprocessor_hooks", []):
                hook(event)

        name = sc.final_name
        if name is None and sc.name_from_outtmpl:
            name = (
                Path(self.params["outtmpl"]["default"])
                .name.replace("%(title).150B", str(info.get("title")))
                .replace("%(id)s", str(info.get("id")))
                .replace("%(ext)s", "mp4")
                .replace("%%", "%")
            )
        if name:
            final = out / name
            final.write_bytes(b"done")
            info["requested_downloads"] = [{"filepath": str(final)}]
        return info


class FakeYdlFactory:
    """Callable used as ``ydl_factory``; records every instance it creates."""

    def __init__(self) -> None:
        self.scenario = FakeScenario()
        self.instances: list[FakeYoutubeDL] = []

    def __call__(self, params: dict[str, Any]) -> FakeYoutubeDL:
        ydl = FakeYoutubeDL(params, self.scenario)
        self.instances.append(ydl)
        return ydl

    @property
    def last_params(self) -> dict[str, Any]:
        return self.instances[-1].params


@pytest.fixture
def fake_ydl() -> FakeYdlFactory:
    return FakeYdlFactory()


@pytest.fixture(autouse=True)
def staging_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test stages downloads under its own tmp_path, never in the real app data."""
    root = tmp_path / "staging"
    monkeypatch.setenv("VIDGRAB_TMP_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real waiting between 403 retries or lock retries (also for UI-driven downloads)."""
    from vidgrab.core import downloader

    monkeypatch.setattr(
        downloader,
        "DEFAULT_POLICY",
        downloader.RetryPolicy(
            forbidden_delays=(0, 0), move_backoff=(0, 0, 0), sleep=lambda s: None
        ),
    )


@pytest.fixture(autouse=True)
def download_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The download history ("Υπάρχει ήδη") lives in tmp_path, never in the real app data."""
    path = tmp_path / "download-archive.txt"
    monkeypatch.setenv("VIDGRAB_ARCHIVE", str(path))
    return path


@pytest.fixture(autouse=True)
def no_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """No pause between downloads from the same platform (tests that need it build one)."""
    from vidgrab.core import jobqueue

    monkeypatch.setattr(jobqueue, "DEFAULT_COOLDOWN", jobqueue.Cooldown(0.0, 0.0))


@pytest.fixture(autouse=True)
def recycle_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, bytes]]:
    """Fake Recycle Bin: records (path, content) and removes the file. Never the real one."""
    from vidgrab.core import trash

    binned: list[tuple[Path, bytes]] = []

    def fake_send2trash(path: str) -> None:
        p = Path(path)
        binned.append((p, p.read_bytes()))
        p.unlink()

    monkeypatch.setattr(trash, "_send2trash", fake_send2trash)
    return binned


@pytest.fixture
def binaries(tmp_path: Path) -> Binaries:
    bin_dir = tmp_path / "bin"
    return Binaries(
        ffmpeg=bin_dir / "ffmpeg.exe",
        ffprobe=bin_dir / "ffprobe.exe",
        deno=bin_dir / "deno.exe",
    )


# --- Repo hygiene: tests must only write to tmp_path ------------------------------------
# Untracked, non-ignored files that appear in the checkout during a test run fail the run.
# (A stray relative output dir once committed "C:/Users/.../Downloads" into the repo, which
# broke the Windows checkout.)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _untracked_files() -> set[str] | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None  # not a git checkout (e.g. sdist): nothing to compare
    return {p for p in out.decode("utf-8", "surrogateescape").split("\0") if p}


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_UNTRACKED_KEY] = _untracked_files()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_UNTRACKED_KEY, None)
    after = _untracked_files()
    if before is None or after is None:
        return
    leaked = sorted(after - before)
    if leaked:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        lines = ["Tests left files inside the repository (use tmp_path):", *leaked]
        if reporter is not None:
            reporter.write_sep("=", "repo hygiene", red=True)
            for line in lines:
                reporter.write_line(line)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


_UNTRACKED_KEY = pytest.StashKey[set[str] | None]()


# --- List fixtures (shapes as yt-dlp returns them) ----------------------------------------


def yt_flat_entry(i: int, **extra: Any) -> dict[str, Any]:
    """One entry of a YouTube playlist from extract_flat="in_playlist"."""
    vid = f"vid{i:03d}"
    return {
        "_type": "url",
        "ie_key": "Youtube",
        "id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": f"Βίντεο {i}",
        "duration": 60 + i,
        "thumbnails": [{"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}],
        **extra,
    }


def yt_playlist(n: int = 5, extra_entries: list[Any] | None = None) -> dict[str, Any]:
    return {
        "_type": "playlist",
        "id": "PLtest",
        "title": "Λίστα δοκιμής",
        "uploader": "Κανάλι",
        "extractor_key": "YoutubeTab",
        "webpage_url": "https://www.youtube.com/playlist?list=PLtest",
        "entries": [yt_flat_entry(i) for i in range(1, n + 1)] + (extra_entries or []),
    }


def instagram_carousel() -> dict[str, Any]:
    """A post with two videos and a photo; entries have no URL of their own."""

    def video(i: int) -> dict[str, Any]:
        return {
            "id": f"ig{i}",
            "title": f"Video by user {i}",
            "duration": 15,
            "ext": "mp4",
            "thumbnail": f"https://ig.example/{i}.jpg",
            "formats": [{"format_id": "v", "ext": "mp4", "vcodec": "avc1", "acodec": "aac"}],
        }

    photo = {"id": "igp", "title": "photo", "ext": "jpg", "formats": [{"ext": "jpg"}]}
    return {
        "_type": "playlist",
        "id": "CARO1",
        "title": "Post by user",
        "extractor_key": "Instagram",
        "webpage_url": "https://www.instagram.com/p/CARO1/",
        "entries": [video(1), photo, video(3)],
    }


def x_post(n: int = 2) -> dict[str, Any]:
    return {
        "_type": "playlist",
        "id": "1700",
        "title": "user - post with videos",
        "extractor_key": "Twitter",
        "webpage_url": "https://x.com/user/status/1700",
        "entries": [
            {
                "id": f"1700_{i}",
                "title": f"user - video {i}",
                "ext": "mp4",
                "duration": 10 * i,
                "formats": [{"format_id": "h", "ext": "mp4", "vcodec": "avc1"}],
            }
            for i in range(1, n + 1)
        ],
    }


class _PerUrlYdl:
    def __init__(self, params: dict[str, Any], factory: PerUrlYdlFactory) -> None:
        self.params = params
        self._factory = factory

    def __enter__(self) -> _PerUrlYdl:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True, **kw: Any) -> dict[str, Any]:
        scenario = self._factory.scenarios.get(url, self._factory.scenario)
        ydl = FakeYoutubeDL(self.params, scenario)
        self._factory.calls.append((url, download, self.params))
        return ydl.extract_info(url, download, **kw)


class PerUrlYdlFactory:
    """Like FakeYdlFactory, but each URL can have its own scenario (one video completes,
    another gets a 403, a third stays downloading...). Unknown URLs use ``scenario``."""

    def __init__(self) -> None:
        self.scenario = FakeScenario()
        self.scenarios: dict[str, FakeScenario] = {}
        self.calls: list[tuple[str, bool, dict[str, Any]]] = []

    def __call__(self, params: dict[str, Any]) -> _PerUrlYdl:
        return _PerUrlYdl(params, self)

    def downloads(self) -> list[str]:
        return [url for url, download, _ in self.calls if download]
