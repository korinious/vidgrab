"""Compare the locked yt-dlp / yt-dlp-ejs versions of two uv.lock files.

Used by ``.github/workflows/update-ytdlp.yml``: a PR is opened only when one of these
versions changes. ``uv lock`` can also rewrite the file for other reasons (e.g. a newer uv
bumps ``revision``), which is not an update.

    python scripts/ytdlp_lock_versions.py OLD_LOCK NEW_LOCK

Prints ``changed=true|false``, ``ytdlp_old=...`` style lines and a title such as
"Update yt-dlp 2026.08.19 → 2026.10.01", and appends the same lines (UTF-8) to the file in
``$GITHUB_OUTPUT`` when it is set, so PowerShell never re-encodes them. Standard library only.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

PACKAGES = {"yt-dlp": "ytdlp", "yt-dlp-ejs": "ejs"}


def locked_versions(text: str) -> dict[str, str]:
    """{package: version} for the packages in PACKAGES ("" if a package is not locked)."""
    found = {p["name"]: p.get("version", "") for p in tomllib.loads(text).get("package", [])}
    return {name: found.get(name, "") for name in PACKAGES}


def shown(version: str) -> str:
    """The version as yt-dlp itself writes it: uv.lock has "2026.8.19", yt-dlp "2026.08.19"."""
    parts = version.split(".")
    if len(parts) >= 3 and len(parts[0]) == 4 and all(p.isdigit() for p in parts):
        parts[1:3] = [p.zfill(2) for p in parts[1:3]]
    return ".".join(parts) or "-"


def change(old: str, new: str) -> str:
    return f"{shown(old)} → {shown(new)}" if old != new else f"{shown(new)} (unchanged)"


def title(old: dict[str, str], new: dict[str, str]) -> str:
    parts = [
        f"{name} {change(old[name], new[name])}" for name in PACKAGES if old[name] != new[name]
    ]
    return "Update " + ", ".join(parts) if parts else ""


def outputs(old_text: str, new_text: str) -> list[str]:
    old, new = locked_versions(old_text), locked_versions(new_text)
    lines = [f"changed={'true' if old != new else 'false'}"]
    for name, key in PACKAGES.items():
        lines += [
            f"{key}_old={shown(old[name])}",
            f"{key}_new={shown(new[name])}",
            f"{key}_change={change(old[name], new[name])}",
        ]
    lines.append(f"title={title(old, new)}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    old_text, new_text = (Path(p).read_text(encoding="utf-8") for p in argv)
    lines = outputs(old_text, new_text)
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
