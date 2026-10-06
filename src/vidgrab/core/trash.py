"""Send files to the Recycle Bin instead of deleting them."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _send2trash(path: str) -> None:
    # Module-level indirection so tests never touch the real Recycle Bin / XDG trash.
    from send2trash import send2trash

    send2trash(path)


def move_to_trash(path: Path) -> None:
    """Move ``path`` to the Recycle Bin. Raises OSError if that is not possible."""
    _send2trash(str(path))
    log.info("Moved to the Recycle Bin: %s", path)
