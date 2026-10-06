import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_paths", ROOT / "scripts" / "check_paths.py")
check_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_paths)


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/someone/Downloads/a",
        "docs/what?.md",
        'docs/"quoted".txt',
        "a<b>.txt",
        "pipe|name",
        "star*.py",
        "back\\slash.txt",
        "src/CON.py",
        "aux",
        "trailing.",
        "trailing /x",
        "ctrl\x01char",
    ],
)
def test_invalid_windows_paths(path):
    assert check_paths.windows_path_problems(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/vidgrab/core/models.py",
        "docs/screenshot.png",
        "Βίντεο/ά.txt",
        "console.py",
        ".github/x",
    ],
)
def test_valid_windows_paths(path):
    assert check_paths.windows_path_problems(path) == []


def test_main_exit_codes(capsys):
    assert check_paths.main(["ok/path.txt"]) == 0
    assert check_paths.main(["C:/bad"]) == 1
    assert "C:/bad" in capsys.readouterr().out


def test_all_tracked_paths_are_valid_on_windows():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    bad = {
        p: probs
        for p in check_paths.tracked_paths()
        if (probs := check_paths.windows_path_problems(p))
    }
    assert bad == {}
