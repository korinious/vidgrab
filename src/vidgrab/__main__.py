"""Entry point: ``python -m vidgrab`` / ``VidGrab.exe``.

``--self-check`` verifies bundled tools without starting the GUI (used by CI).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _ensure_std_streams() -> None:
    # A --windowed PyInstaller build has no console, so sys.stdout/stderr are None.
    # Some libraries (yt-dlp included) expect real file objects.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _self_check(report: Path | None) -> int:
    from vidgrab import __version__
    from vidgrab.core.binaries import self_check

    ok, lines = self_check()
    text = "\n".join([f"VidGrab {__version__} self-check", *lines, "PASS" if ok else "FAIL"])
    print(text)
    if report is not None:
        report.write_text(text + "\n", encoding="utf-8")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    parser = argparse.ArgumentParser(prog="VidGrab")
    parser.add_argument("--self-check", action="store_true", help="check bundled tools and exit")
    parser.add_argument("--report", type=Path, help="also write the self-check report here")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.self_check:
        return _self_check(args.report)

    from vidgrab.ui.app import run_gui

    return run_gui([sys.argv[0], *qt_args])


if __name__ == "__main__":
    sys.exit(main())
