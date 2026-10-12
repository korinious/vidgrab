"""scripts/ytdlp_lock_versions.py: the weekly yt-dlp PR opens only for a new version."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ytdlp_lock_versions", ROOT / "scripts" / "ytdlp_lock_versions.py"
)
lock_versions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lock_versions)


def lock(revision: int = 3, ytdlp: str = "2026.8.19", ejs: str = "0.8.0") -> str:
    return f"""version = 1
revision = {revision}
requires-python = "==3.12.*"

[[package]]
name = "certifi"
version = "2026.1.1"

[[package]]
name = "yt-dlp"
version = "{ytdlp}"

[[package]]
name = "yt-dlp-ejs"
version = "{ejs}"
"""


def as_dict(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines)


def test_lockfile_rewrite_without_new_versions_is_not_an_update():
    # PR #6: a newer uv bumped "revision" 3 -> 5, yt-dlp stayed 2026.08.19
    out = as_dict(lock_versions.outputs(lock(revision=3), lock(revision=5)))
    assert out["changed"] == "false"
    assert out["title"] == ""


def test_new_ytdlp_shows_old_and_new_version():
    out = as_dict(lock_versions.outputs(lock(), lock(ytdlp="2026.10.1")))
    assert out["changed"] == "true"
    assert out["title"] == "Update yt-dlp 2026.08.19 → 2026.10.01"
    assert out["ytdlp_change"] == "2026.08.19 → 2026.10.01"
    assert out["ejs_change"] == "0.8.0 (unchanged)"


def test_new_ejs_only_is_an_update():
    out = as_dict(lock_versions.outputs(lock(), lock(ejs="0.9.0")))
    assert out["changed"] == "true"
    assert out["title"] == "Update yt-dlp-ejs 0.8.0 → 0.9.0"
    assert out["ytdlp_change"] == "2026.08.19 (unchanged)"


def test_both_changed():
    out = as_dict(lock_versions.outputs(lock(), lock(ytdlp="2026.10.1.233", ejs="0.9.0")))
    assert out["title"] == "Update yt-dlp 2026.08.19 → 2026.10.01.233, yt-dlp-ejs 0.8.0 → 0.9.0"


def test_writes_github_output_as_utf8(tmp_path, monkeypatch, capsys):
    old, new, gh = tmp_path / "old.lock", tmp_path / "new.lock", tmp_path / "out.txt"
    old.write_text(lock(), encoding="utf-8")
    new.write_text(lock(ytdlp="2026.10.1"), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    assert lock_versions.main([str(old), str(new)]) == 0
    written = gh.read_text(encoding="utf-8").splitlines()
    assert "title=Update yt-dlp 2026.08.19 → 2026.10.01" in written
    assert "changed=true" in capsys.readouterr().out


def test_current_lockfile_has_both_packages():
    versions = lock_versions.locked_versions((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert all(versions.values()), versions
