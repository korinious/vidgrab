import logging
from pathlib import Path

import pytest

from vidgrab import strings
from vidgrab.core import binaries as binmod
from vidgrab.core.binaries import Binaries, exe_name, find_binaries, self_check


def touch_tools(directory: Path, names=("ffmpeg", "ffprobe", "deno")) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / exe_name(name)).write_bytes(b"")


def test_exe_name():
    assert exe_name("ffmpeg", windows=True) == "ffmpeg.exe"
    assert exe_name("ffmpeg", windows=False) == "ffmpeg"


def test_find_all_in_search_dir(tmp_path):
    touch_tools(tmp_path)
    b = find_binaries([tmp_path], use_path=False)
    assert b.ffmpeg == tmp_path / exe_name("ffmpeg")
    assert b.ffprobe == tmp_path / exe_name("ffprobe")
    assert b.deno == tmp_path / exe_name("deno")
    assert b.missing == []
    assert b.warnings() == []


def test_first_search_dir_wins(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    touch_tools(first, ["ffmpeg"])
    touch_tools(second)
    b = find_binaries([first, second], use_path=False)
    assert b.ffmpeg.parent == first
    assert b.deno.parent == second


def test_missing_deno_logs_warning_and_warns_user(tmp_path, caplog):
    touch_tools(tmp_path, ["ffmpeg", "ffprobe"])
    with caplog.at_level(logging.WARNING):
        b = find_binaries([tmp_path], use_path=False)
    assert b.deno is None
    assert b.missing == ["deno"]
    assert any("deno not found" in r.message for r in caplog.records)
    assert b.warnings() == [strings.WARN_DENO_MISSING]


def test_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(binmod.shutil, "which", lambda name: f"/usr/bin/{name}")
    b = find_binaries([tmp_path], use_path=True)
    assert b.ffmpeg == Path("/usr/bin/ffmpeg")


def test_meipass_dir_is_searched_first(tmp_path, monkeypatch):
    monkeypatch.setattr(binmod.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv(binmod.BIN_DIR_ENV, str(tmp_path / "env"))
    dirs = binmod.default_search_dirs()
    assert dirs[0] == tmp_path / "bin"
    assert dirs[1] == tmp_path / "env"


def test_ytdlp_options_all_present(tmp_path):
    b = Binaries(ffmpeg=tmp_path / "ffmpeg", ffprobe=tmp_path / "ffprobe", deno=tmp_path / "deno")
    assert b.ytdlp_options() == {
        "ffmpeg_location": str(tmp_path),
        "js_runtimes": {"deno": {"path": str(tmp_path / "deno")}},
    }


def test_ytdlp_options_ffmpeg_without_ffprobe_alongside(tmp_path):
    b = Binaries(ffmpeg=tmp_path / "a" / "ffmpeg", ffprobe=tmp_path / "b" / "ffprobe")
    assert b.ytdlp_options() == {"ffmpeg_location": str(tmp_path / "a" / "ffmpeg")}


def test_ytdlp_options_none():
    assert Binaries().ytdlp_options() == {}


def test_js_runtimes_option_accepted_by_yt_dlp(tmp_path):
    from yt_dlp import YoutubeDL

    b = Binaries(deno=tmp_path / "deno")
    with YoutubeDL({"quiet": True, **b.ytdlp_options()}) as ydl:
        assert "deno" in ydl.params["js_runtimes"]


def test_self_check_ok(tmp_path):
    touch_tools(tmp_path)
    ok, lines = self_check(find_binaries([tmp_path], use_path=False))
    assert ok, lines
    assert any("yt-dlp-ejs" in line for line in lines)


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe", "deno"])
def test_self_check_fails_on_any_missing_tool(tmp_path, missing):
    touch_tools(tmp_path, [n for n in ("ffmpeg", "ffprobe", "deno") if n != missing])
    ok, lines = self_check(find_binaries([tmp_path], use_path=False))
    assert not ok
    assert strings.SELF_CHECK_MISSING.format(name=missing) in lines
