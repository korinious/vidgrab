"""Windows file-name rules, shared by ``sanitize_filename`` and ``scripts/check_paths.py``.

Standard library only: ``check_paths.py`` imports this module directly in CI, before any
dependencies are installed.
"""

from __future__ import annotations

import re
import unicodedata

INVALID_CHARS = frozenset('<>:"|?*\\/')
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Leaves room for " (2)", the extension and a numbering prefix inside MAX_PATH-ish limits.
MAX_STEM_CHARS = 150


def name_problems(part: str) -> list[str]:
    """Why one path component (a file or folder name) is invalid on Windows; [] if fine."""
    problems: list[str] = []
    bad = sorted(INVALID_CHARS.intersection(part) - {"/"})
    if bad:
        problems.append(f"{part!r} contains {' '.join(bad)}")
    if CONTROL_CHARS.search(part):
        problems.append(f"{part!r} contains a control character")
    if part.split(".")[0].strip().upper() in RESERVED_NAMES:
        problems.append(f"{part!r} is a reserved device name")
    if part.endswith((".", " ")):
        problems.append(f"{part!r} ends with a dot or space")
    return problems


def windows_path_problems(path: str) -> list[str]:
    """Why ``path`` (with '/' separators, as git prints it) is invalid on Windows."""
    return [problem for part in path.split("/") for problem in name_problems(part)]


def sanitize_filename(name: str, fallback: str = "video", max_chars: int = MAX_STEM_CHARS) -> str:
    """Turn any title into a file or folder name that is valid on Windows.

    Invalid characters become similar-looking safe ones or a space, whitespace is
    collapsed, trailing dots/spaces go, a reserved device name gets a "_" before any
    extension, and the result is cut to ``max_chars``. Never returns an empty string.
    """
    text = unicodedata.normalize("NFC", name or "")
    text = CONTROL_CHARS.sub(" ", text)
    text = text.replace(":", " -").replace('"', "'").replace("|", "-")
    text = text.replace("/", "-").replace("\\", "-")
    text = "".join(" " if c in INVALID_CHARS else c for c in text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:max_chars].rstrip(". ")
    text = text.lstrip(" ")
    if not text:
        text = fallback
    stem, dot, rest = text.partition(".")
    if stem.strip().upper() in RESERVED_NAMES:
        text = f"{stem}_{dot}{rest}"  # "CON" -> "CON_", "nul.txt" -> "nul_.txt"
    return text


def numbered_name(position: int, total: int, title: str) -> str:
    """'03 - Title' with as many digits as the list needs (01..48, 001..120)."""
    width = max(2, len(str(max(total, position))))
    return f"{position:0{width}d} - {title}"
