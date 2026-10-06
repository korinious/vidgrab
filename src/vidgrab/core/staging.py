"""Per-job staging directories and the final move into the destination folder.

Every job downloads, merges and post-processes inside its own folder under
``%LOCALAPPDATA%\\VidGrab\\tmp`` (outside OneDrive and other synced folders). Only the
finished file is moved to the destination, with retries for transient Windows locks
(antivirus, OneDrive, the search indexer) and a " (2)", " (3)" suffix instead of ever
overwriting an existing file.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import platformdirs

from vidgrab import APP_NAME
from vidgrab.core.errors import ErrorKind, UserError, is_lock_error
from vidgrab.core.winlock import lock_holders

log = logging.getLogger(__name__)

TMP_DIR_ENV = "VIDGRAB_TMP_DIR"  # override (tests, portable setups)
OWNER_FILE = "owner.pid"
# Waits between attempts of the final move: ~9.75 s in total before giving up.
MOVE_BACKOFF_S: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 2.0, 2.0, 2.0)
_ERROR_NOT_SAME_DEVICE = 17  # Windows: os.replace across drives


def default_tmp_root() -> Path:
    if env := os.environ.get(TMP_DIR_ENV):
        return Path(env)
    return platformdirs.user_data_path(APP_NAME, appauthor=False, roaming=False) / "tmp"


@contextmanager
def staging_dir(root: Path | None = None, job_id: int | None = None) -> Iterator[Path]:
    """Create a private folder for one job; always removed afterwards (success, error, cancel)."""
    root = root or default_tmp_root()
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"job{job_id}-" if job_id is not None else "job-"
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    (path / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    log.info("Staging in %s", path)
    try:
        yield path
    finally:
        _remove_tree(path)


def _remove_tree(path: Path) -> None:
    def onerror(func, p, exc):
        log.warning("Could not remove %s: %s", p, exc)

    shutil.rmtree(path, onexc=onerror)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def cleanup_orphans(root: Path | None = None) -> list[Path]:
    """Remove staging folders left by crashed or killed runs. Returns what was removed.

    Folders whose owner process is still alive (another VidGrab window) are kept.
    """
    root = root or default_tmp_root()
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            pid = int((child / OWNER_FILE).read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pid = -1
        if _pid_alive(pid):
            continue
        _remove_tree(child)
        removed.append(child)
    if removed:
        log.info("Removed %d orphaned staging folder(s) from %s", len(removed), root)
    return removed


def reserve_destination(dest_dir: Path, name: str) -> Path:
    """Create and return a new, empty file ``dest_dir/name`` or ``name (2)``, ``(3)``, ...

    The empty file is created exclusively, so two jobs finishing at the same moment can
    never pick the same name. The caller replaces it with the real content.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = dest_dir / (name if n == 1 else f"{stem} ({n}){suffix}")
        try:
            with open(candidate, "xb"):
                return candidate
        except FileExistsError:
            n += 1


def _replace_across_volumes(src: Path, dest: Path, replace: Callable[[Path, Path], None]) -> None:
    try:
        replace(src, dest)
    except OSError as exc:
        cross_device = exc.errno == errno.EXDEV or (
            getattr(exc, "winerror", None) == _ERROR_NOT_SAME_DEVICE
        )
        if not cross_device:
            raise
        # Different drive: copy next to the destination, then swap in atomically.
        partial = dest.with_name(dest.name + ".vgpart")
        try:
            shutil.copy2(src, partial)
            replace(partial, dest)
        finally:
            partial.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            src.unlink()  # the staging folder is removed afterwards anyway


def _default_replace(src: Path, dst: Path) -> None:
    os.replace(src, dst)  # module-level so tests can simulate Windows locks


def move_to_destination(
    src: Path,
    dest_dir: Path,
    *,
    replace: Callable[[Path, Path], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    backoff: Sequence[float] = MOVE_BACKOFF_S,
) -> Path:
    """Move the finished file into ``dest_dir`` without overwriting anything.

    Retries with backoff while another process holds the file (WinError 32/33). If it
    never frees up, logs who holds it (Windows Restart Manager) and raises FILE_LOCKED.
    """
    replace = replace or _default_replace
    dest = reserve_destination(dest_dir, src.name)
    attempts = len(backoff) + 1
    for attempt in range(1, attempts + 1):
        try:
            _replace_across_volumes(src, dest, replace)
            if dest.name != src.name:
                log.info("%s already existed; saved as %s", src.name, dest.name)
            return dest
        except OSError as exc:
            if not is_lock_error(exc):
                dest.unlink(missing_ok=True)
                raise
            if attempt == attempts:
                held_by = ", ".join(lock_holders(src) + lock_holders(dest)) or "unknown"
                log.error(
                    "Giving up moving %s -> %s after %d attempts: %s; held by: %s",
                    src,
                    dest,
                    attempts,
                    exc,
                    held_by,
                )
                dest.unlink(missing_ok=True)
                raise UserError(
                    ErrorKind.FILE_LOCKED, detail=f"{exc} (held by: {held_by})"
                ) from exc
            delay = backoff[attempt - 1]
            log.warning(
                "File locked moving %s (attempt %d/%d): %s; retrying in %.2fs",
                src.name,
                attempt,
                attempts,
                exc,
                delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")


def _rename_with_retries(
    src: Path,
    dest: Path,
    *,
    replace: Callable[[Path, Path], None],
    sleep: Callable[[float], None],
    backoff: Sequence[float],
) -> None:
    """Rename within one folder, retrying while another process holds the file."""
    attempts = len(backoff) + 1
    for attempt in range(1, attempts + 1):
        try:
            replace(src, dest)
            return
        except OSError as exc:
            if not is_lock_error(exc) or attempt == attempts:
                raise
            log.warning(
                "File locked renaming %s (attempt %d/%d): %s", src.name, attempt, attempts, exc
            )
            sleep(backoff[attempt - 1])


def replace_with_upgrade(
    new: Path,
    old: Path,
    *,
    replace: Callable[[Path, Path], None] | None = None,
    trash: Callable[[Path], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    backoff: Sequence[float] = MOVE_BACKOFF_S,
) -> Path:
    """Put the better download ``new`` where ``old`` is; ``old`` goes to the Recycle Bin.

    Safe order: (1) move ``new`` into the folder under a free name, so it can never be
    lost; (2) send ``old`` to the Recycle Bin; (3) rename ``new`` to ``old``'s name.
    If (2) or (3) fails, both files are kept and the new one keeps its " (2)" name.
    Returns where the new file ended up.
    """
    from vidgrab.core.trash import move_to_trash

    replace = replace or _default_replace
    trash = trash or move_to_trash
    # Same name as before; only the extension follows the new file if it ever differs.
    target = old if old.suffix.lower() == new.suffix.lower() else old.with_suffix(new.suffix)

    placed = move_to_destination(
        new.rename(new.with_name(target.name)) if new.name != target.name else new,
        old.parent,
        replace=replace,
        sleep=sleep,
        backoff=backoff,
    )
    if old.exists() and old != placed:
        try:
            trash(old)
        except OSError as exc:
            log.warning("Could not move %s to the Recycle Bin (%s); keeping both", old, exc)
            return placed
    if placed == target:
        # Either the old file was already gone, or only the extension changed.
        return placed
    if target.exists():
        log.warning("%s still exists; keeping the new file as %s", target, placed.name)
        return placed
    try:
        _rename_with_retries(placed, target, replace=replace, sleep=sleep, backoff=backoff)
    except OSError as exc:
        log.warning("Could not rename %s to %s (%s); keeping it as is", placed, target, exc)
        return placed
    log.info("Replaced %s with a higher-resolution download", target)
    return target
