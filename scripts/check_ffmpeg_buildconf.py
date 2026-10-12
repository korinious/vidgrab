"""Check that THIRD-PARTY-NOTICES.md lists the configure flags of the bundled FFmpeg.

    python scripts/check_ffmpeg_buildconf.py THIRD-PARTY-NOTICES.md FFMPEG-BUILDCONF.txt

The second file is the output of ``ffmpeg -hide_banner -buildconf`` (build.yml writes it).
Fails when the flags differ, e.g. after FFmpeg was bumped without updating the notices.
Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FLAG = re.compile(r"--[a-z0-9][\w-]*(?:=\S+)?", re.I)


def configure_flags(text: str) -> list[str]:
    """The flags after the first "configuration:" line."""
    _, found, rest = text.partition("configuration:")
    if not found:
        return []
    return FLAG.findall(rest.split("```", 1)[0])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    notices, buildconf = (
        configure_flags(Path(p).read_text(encoding="utf-8-sig", errors="replace")) for p in argv
    )
    if not buildconf:
        print(f"No configuration found in {argv[1]}", file=sys.stderr)
        return 1
    if notices != buildconf:
        print(f"{argv[0]} does not match the bundled FFmpeg ({argv[1]}):", file=sys.stderr)
        for flag in sorted(set(buildconf) - set(notices)):
            print(f"  missing in the notices: {flag}", file=sys.stderr)
        for flag in sorted(set(notices) - set(buildconf)):
            print(f"  not in the build:       {flag}", file=sys.stderr)
        if set(notices) == set(buildconf):
            print("  (same flags, different order)", file=sys.stderr)
        return 1
    print(f"OK: {len(buildconf)} FFmpeg configure flags match {argv[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
