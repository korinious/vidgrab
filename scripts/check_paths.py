"""Fail if any tracked path cannot be checked out on Windows.

Run from the repo root: ``python scripts/check_paths.py`` (CI does this on Linux before the
Windows jobs, because a bad path makes the Windows checkout itself fail).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# The rules live in the app (core/filenames.py, standard library only), so file names the
# app creates and paths in this repo are checked the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vidgrab.core.filenames import windows_path_problems


def tracked_paths() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode(
        "utf-8", "surrogateescape"
    )
    return [p for p in out.split("\0") if p]


def main(argv: list[str] | None = None) -> int:
    paths = argv if argv else tracked_paths()
    failures = {p: probs for p in paths if (probs := windows_path_problems(p))}
    for path, problems in failures.items():
        print(f"{path}: {'; '.join(problems)}")
    if failures:
        print(f"{len(failures)} path(s) cannot be checked out on Windows.")
        return 1
    print(f"OK: {len(paths)} paths are valid on Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
