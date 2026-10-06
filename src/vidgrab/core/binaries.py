"""Locate bundled external tools (ffmpeg, ffprobe, deno) and build yt-dlp options for them.

Search order:
1. ``<frozen app>/_internal/bin`` (PyInstaller ``sys._MEIPASS``)
2. ``$VIDGRAB_BIN_DIR``
3. ``<repo>/bin`` (development)
4. ``PATH``
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vidgrab import strings

log = logging.getLogger(__name__)

TOOLS = ("ffmpeg", "ffprobe", "deno")
BIN_DIR_ENV = "VIDGRAB_BIN_DIR"


def exe_name(name: str, windows: bool | None = None) -> str:
    if windows is None:
        windows = os.name == "nt"
    return f"{name}.exe" if windows else name


def default_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "bin")
    if env := os.environ.get(BIN_DIR_ENV):
        dirs.append(Path(env))
    dirs.append(Path(__file__).resolve().parents[3] / "bin")  # repo root in dev checkouts
    return dirs


def locate(name: str, search_dirs: Iterable[Path], use_path: bool = True) -> Path | None:
    filename = exe_name(name)
    for directory in search_dirs:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    if use_path:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


@dataclass(frozen=True)
class Binaries:
    ffmpeg: Path | None = None
    ffprobe: Path | None = None
    deno: Path | None = None

    @property
    def missing(self) -> list[str]:
        return [name for name in TOOLS if getattr(self, name) is None]

    def ytdlp_options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        if self.ffmpeg is not None:
            # A directory lets yt-dlp find both ffmpeg and ffprobe next to each other.
            same_dir = self.ffprobe is not None and self.ffprobe.parent == self.ffmpeg.parent
            opts["ffmpeg_location"] = str(self.ffmpeg.parent if same_dir else self.ffmpeg)
        if self.deno is not None:
            opts["js_runtimes"] = {"deno": {"path": str(self.deno)}}
        return opts

    def warnings(self) -> list[str]:
        """User-facing warnings about missing tools."""
        out: list[str] = []
        if self.ffmpeg is None or self.ffprobe is None:
            out.append(strings.WARN_FFMPEG_MISSING)
        if self.deno is None:
            out.append(strings.WARN_DENO_MISSING)
        return out


def find_binaries(search_dirs: Sequence[Path] | None = None, use_path: bool = True) -> Binaries:
    dirs = list(default_search_dirs() if search_dirs is None else search_dirs)
    found = Binaries(**{name: locate(name, dirs, use_path) for name in TOOLS})
    for name in TOOLS:
        path = getattr(found, name)
        if path is None:
            level = logging.WARNING
            suffix = " (YouTube quality may be limited)" if name == "deno" else ""
            log.log(level, "%s not found in %s or PATH%s", name, dirs, suffix)
        else:
            log.info("%s: %s", name, path)
    return found


def self_check(binaries: Binaries | None = None) -> tuple[bool, list[str]]:
    """Check that all tools and the yt-dlp JS components are available.

    Returns (ok, report lines). Used by ``VidGrab.exe --self-check`` in CI.
    """
    binaries = binaries or find_binaries()
    lines: list[str] = []
    ok = True
    for name in TOOLS:
        path = getattr(binaries, name)
        if path is None:
            ok = False
            lines.append(strings.SELF_CHECK_MISSING.format(name=name))
        else:
            lines.append(strings.SELF_CHECK_FOUND.format(name=name, path=path))
    try:
        # The YouTube challenge solver scripts must be bundled as data files.
        import yt_dlp_ejs.yt.solver as solver

        if not (solver.core() and solver.lib()):
            raise ImportError("empty solver scripts")
    except Exception as exc:
        ok = False
        lines.append(strings.SELF_CHECK_MISSING.format(name=f"yt-dlp-ejs ({exc})"))
    else:
        lines.append(strings.SELF_CHECK_FOUND.format(name="yt-dlp-ejs", path="solver scripts ok"))
    return ok, lines
