"""Fail if any tracked path cannot be checked out on Windows.

Run from the repo root: ``python scripts/check_paths.py`` (CI does this on Linux before the
Windows jobs, because a bad path makes the Windows checkout itself fail).
"""

from __future__ import annotations

import re
import subprocess
import sys

INVALID_CHARS = set('<>:"|?*\\')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip
_CONTROL = re.compile(r"[\x00-\x1f]")


def windows_path_problems(path: str) -> list[str]:
    """Return the reasons ``path`` (a git path with '/' separators) is invalid on Windows."""
    problems: list[str] = []
    for part in path.split("/"):
        bad = sorted(INVALID_CHARS.intersection(part))
        if bad:
            problems.append(f"{part!r} contains {' '.join(bad)}")
        if _CONTROL.search(part):
            problems.append(f"{part!r} contains a control character")
        if part.split(".")[0].upper() in RESERVED_NAMES:
            problems.append(f"{part!r} is a reserved device name")
        if part.endswith((".", " ")):
            problems.append(f"{part!r} ends with a dot or space")
    return problems


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
