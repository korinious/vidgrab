"""Workflows, license collection and FFmpeg notices: what the release zip relies on."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def steps(workflow: dict):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_a_commit(path):
    for step in steps(yaml.safe_load(path.read_text(encoding="utf-8"))):
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_permissions_are_per_job(path):
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {}
    for name, job in workflow["jobs"].items():
        assert "permissions" in job, name


def test_only_the_release_job_can_write_in_build():
    workflow = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8"))
    writers = [
        n for n, j in workflow["jobs"].items() if "write" in (j["permissions"] or {}).values()
    ]
    assert writers == ["release"]
    assert workflow["jobs"]["release"]["if"].startswith("startsWith(github.ref, 'refs/tags/v')")
    assert "pull_request_target" not in workflow[True]  # "on:" parses as True


def test_every_setup_uv_uses_the_same_pinned_uv():
    build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8"))
    pinned = build["env"]["UV_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned)
    for path in WORKFLOWS:
        for step in steps(yaml.safe_load(path.read_text(encoding="utf-8"))):
            if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                assert step["with"]["version"] in (pinned, "${{ env.UV_VERSION }}"), path.name
    # uv.lock is in the format this uv writes, so the CI never rewrites it (PR #6)
    lock_head = (ROOT / "uv.lock").read_text(encoding="utf-8").splitlines()[:2]
    assert lock_head == ["version = 1", "revision = 5"]


def test_release_uploads_zip_sums_and_ffmpeg_source():
    text = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    assert text.count("VidGrab-*-win64.zip SHA256SUMS.txt ffmpeg-*.tar.xz") == 2
    assert "sha256sum --check --strict SHA256SUMS.txt" in text


def test_ffmpeg_notices_match_their_check(tmp_path):
    check = load_script("check_ffmpeg_buildconf")
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    flags = check.configure_flags(notices)
    assert flags[:2] == ["--enable-gpl", "--enable-version3"]
    assert {"--enable-libx264", "--enable-libx265"} <= set(flags)
    buildconf = tmp_path / "buildconf.txt"
    buildconf.write_text("  configuration:\n" + "".join(f"    {f}\n" for f in flags), "utf-8")
    assert check.main([str(ROOT / "THIRD-PARTY-NOTICES.md"), str(buildconf)]) == 0
    buildconf.write_text("  configuration:\n    --enable-gpl\n", "utf-8")
    assert check.main([str(ROOT / "THIRD-PARTY-NOTICES.md"), str(buildconf)]) == 1


def test_gpl_libraries_have_source_links():
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    for lib in ("x264", "x265", "Xvid", "vid.stab", "Rubber Band"):
        row = next(line for line in notices.splitlines() if line.startswith(f"| {lib}"))
        assert "GPL" in row and "https://" in row


def test_license_files_are_in_place():
    assert (
        (ROOT / "LICENSE")
        .read_text(encoding="utf-8")
        .lstrip()
        .startswith("GNU GENERAL PUBLIC LICENSE")
    )
    names = {p.name for p in (ROOT / "LICENSES").iterdir()}
    assert {"deno-MIT.txt", "python-PSF.txt", "qt-pyside6-LGPL-3.0.txt", "lucide-ISC.txt"} <= names
    assert 'license = "GPL-3.0-or-later"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_python_package_licenses_are_collected(tmp_path):
    collector = load_script("third_party_licenses")
    assert collector.collect(tmp_path) == []
    index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    for package in ("yt-dlp", "mutagen", "certifi", "requests", "PySide6"):
        assert package in index
    assert any(p.name.startswith("mutagen-") for p in tmp_path.iterdir())
    # dev tools are not shipped
    assert "pytest" not in index and "pyinstaller" not in index.lower()


def test_ffmpeg_source_is_pinned():
    build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{64}", build["env"]["FFMPEG_SRC_SHA256"])
    assert build["env"]["FFMPEG_SRC_URL"].endswith(
        f"ffmpeg-{build['env']['FFMPEG_VERSION']}.tar.xz"
    )
