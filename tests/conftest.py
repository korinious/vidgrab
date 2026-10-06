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
        if not download:
            return info

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

        if sc.final_name:
            final = out / sc.final_name
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
