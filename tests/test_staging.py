import errno
import os
import subprocess
import sys
import threading

import pytest

from vidgrab.core import staging
from vidgrab.core.errors import ErrorKind, UserError, classify, is_lock_error
from vidgrab.core.staging import (
    OWNER_FILE,
    cleanup_orphans,
    default_tmp_root,
    move_to_destination,
    reserve_destination,
    staging_dir,
)
from vidgrab.core.winlock import lock_holders


def winerror32() -> PermissionError:
    """What Windows raises when antivirus/OneDrive holds the file (simulated on any OS)."""
    exc = PermissionError(
        13, "The process cannot access the file because it is being used by another process"
    )
    exc.winerror = 32
    return exc


class FlakyReplace:
    """os.replace that fails with WinError 32 the first `failures` times."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def __call__(self, src, dst):
        self.calls += 1
        if self.calls <= self.failures:
            raise winerror32()
        os.replace(src, dst)


@pytest.fixture
def src(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    f = stage / "Title [abc].mp4"
    f.write_bytes(b"video")
    return f


# --- staging folders -------------------------------------------------------------------


def test_default_root_honours_env(staging_root):
    assert default_tmp_root() == staging_root


def test_default_root_is_local_app_data(monkeypatch):
    monkeypatch.delenv(staging.TMP_DIR_ENV)
    root = default_tmp_root()
    assert root.name == "tmp" and root.parent.name == "VidGrab"
    assert "OneDrive" not in str(root)


def test_staging_dir_is_private_and_removed(staging_root):
    with staging_dir(job_id=7) as a, staging_dir(job_id=7) as b:
        assert a != b  # same job id twice (e.g. two windows) still never shares a folder
        assert a.parent == staging_root and a.name.startswith("job7-")
        assert (a / OWNER_FILE).read_text() == str(os.getpid())
        (a / "x.part").write_bytes(b"x")
    assert not a.exists() and not b.exists()


def test_staging_dir_removed_on_error(staging_root):
    with pytest.raises(RuntimeError), staging_dir() as stage:
        (stage / "x.part").write_bytes(b"x")
        raise RuntimeError("boom")
    assert list(staging_root.iterdir()) == []


def test_cleanup_orphans(staging_root):
    staging_root.mkdir()
    dead = staging_root / "job1-dead"
    dead.mkdir()
    (dead / OWNER_FILE).write_text("999999999")  # no such process
    (dead / "a.part").write_bytes(b"x")
    unowned = staging_root / "job2-nomarker"
    unowned.mkdir()
    alive = staging_root / "job3-alive"
    alive.mkdir()
    (alive / OWNER_FILE).write_text(str(os.getpid()))  # e.g. another open VidGrab window
    stray_file = staging_root / "note.txt"
    stray_file.write_text("x")

    removed = cleanup_orphans()

    assert sorted(p.name for p in removed) == ["job1-dead", "job2-nomarker"]
    assert alive.exists() and stray_file.exists()
    assert not dead.exists() and not unowned.exists()


def test_cleanup_orphans_without_root(tmp_path):
    assert cleanup_orphans(tmp_path / "missing") == []


def test_owner_of_a_finished_process_is_dead():
    proc = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert staging._pid_alive(int(proc.stdout)) is False
    assert staging._pid_alive(os.getpid()) is True


# --- destination names -----------------------------------------------------------------


def test_reserve_destination_never_overwrites(tmp_path):
    (tmp_path / "v.mp4").write_bytes(b"old")
    (tmp_path / "v (2).mp4").write_bytes(b"old2")
    assert reserve_destination(tmp_path, "v.mp4") == tmp_path / "v (3).mp4"
    assert (tmp_path / "v.mp4").read_bytes() == b"old"


def test_reserve_destination_is_exclusive_under_concurrency(tmp_path):
    names, barrier = [], threading.Barrier(8)

    def worker():
        barrier.wait()
        names.append(reserve_destination(tmp_path, "v.mp4").name)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(names) == sorted(["v.mp4"] + [f"v ({i}).mp4" for i in range(2, 9)])


# --- final move ------------------------------------------------------------------------


def test_move_simple(tmp_path, src):
    dest = move_to_destination(src, tmp_path / "Downloads")
    assert dest == tmp_path / "Downloads" / "Title [abc].mp4"
    assert dest.read_bytes() == b"video" and not src.exists()


def test_move_keeps_existing_file(tmp_path, src):
    out = tmp_path / "Downloads"
    out.mkdir()
    (out / "Title [abc].mp4").write_bytes(b"older download")
    dest = move_to_destination(src, out)
    assert dest.name == "Title [abc] (2).mp4"
    assert (out / "Title [abc].mp4").read_bytes() == b"older download"


def test_winerror32_passes_after_two_attempts(tmp_path, src, caplog):
    replace, sleeps = FlakyReplace(failures=2), []
    dest = move_to_destination(src, tmp_path / "out", replace=replace, sleep=sleeps.append)
    assert dest.read_bytes() == b"video"
    assert replace.calls == 3
    assert sleeps == list(staging.MOVE_BACKOFF_S[:2])
    assert caplog.text.count("File locked moving") == 2


def test_winerror32_never_clears_gives_file_locked(tmp_path, src, caplog):
    replace, sleeps = FlakyReplace(failures=10**6), []
    with pytest.raises(UserError) as ei:
        move_to_destination(src, tmp_path / "out", replace=replace, sleep=sleeps.append)
    err = ei.value
    assert err.kind is ErrorKind.FILE_LOCKED
    assert "antivirus" in err.message and "OneDrive" in err.message
    assert "held by" in err.detail
    assert replace.calls == len(staging.MOVE_BACKOFF_S) + 1
    assert 9 <= sum(sleeps) <= 11  # gives up after ~10 s of waiting
    assert list((tmp_path / "out").iterdir()) == []  # reserved name released
    assert src.exists()  # nothing lost; the staging folder is cleaned by the caller
    assert "Giving up moving" in caplog.text


def test_other_errors_are_not_retried(tmp_path, src):
    def broken(a, b):
        raise PermissionError(13, "Access is denied")  # no winerror 32: not a lock

    sleeps = []
    with pytest.raises(PermissionError):
        move_to_destination(src, tmp_path / "out", replace=broken, sleep=sleeps.append)
    assert sleeps == []
    assert list((tmp_path / "out").iterdir()) == []


def test_move_across_drives_copies(tmp_path, src):
    calls = []

    def replace(a, b):
        calls.append((a, b))
        if a == src:  # first try: a plain rename across drives fails
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        os.replace(a, b)

    dest = move_to_destination(src, tmp_path / "out", replace=replace)
    assert dest.read_bytes() == b"video"
    assert not src.exists()
    assert not list((tmp_path / "out").glob("*.vgpart"))


# --- error mapping ---------------------------------------------------------------------


def test_lock_errors_are_classified():
    assert is_lock_error(winerror32())
    assert not is_lock_error(PermissionError(13, "denied"))
    assert classify(winerror32()).kind is ErrorKind.FILE_LOCKED


def test_lock_holders_is_empty_off_windows(src):
    if os.name == "nt":
        pytest.skip("Windows has a real implementation")
    assert lock_holders(src) == []


@pytest.mark.skipif(os.name != "nt", reason="real sharing violations exist only on Windows")
def test_real_windows_lock_is_reported_with_holder(tmp_path, src, caplog):
    # An open Python handle has no FILE_SHARE_DELETE, so renaming the file fails with
    # WinError 32 exactly like an antivirus scan would.
    with open(src, "rb"):
        holders = lock_holders(src)
        assert any(f"pid {os.getpid()}" in h for h in holders), holders
        with pytest.raises(UserError) as ei:
            move_to_destination(src, tmp_path / "out", sleep=lambda s: None)
    assert ei.value.kind is ErrorKind.FILE_LOCKED
    assert f"pid {os.getpid()}" in ei.value.detail
    assert f"pid {os.getpid()}" in caplog.text


# --- replacing a file with a better download ----------------------------------------------

from vidgrab.core.staging import replace_with_upgrade  # noqa: E402


@pytest.fixture
def old_and_new(tmp_path):
    out = tmp_path / "Downloads"
    out.mkdir()
    old = out / "Title [abc].mp4"
    old.write_bytes(b"old 1080p")
    stage = tmp_path / "stage2"
    stage.mkdir()
    new = stage / "Title [abc].mp4"
    new.write_bytes(b"new 2160p")
    return old, new


def test_upgrade_replaces_same_name_and_bins_old(old_and_new, recycle_bin):
    old, new = old_and_new
    final = replace_with_upgrade(new, old)
    assert final == old  # same name, no " (2)"
    assert old.read_bytes() == b"new 2160p"
    assert recycle_bin == [(old, b"old 1080p")]  # old one went to the bin, not deleted
    assert sorted(p.name for p in old.parent.iterdir()) == ["Title [abc].mp4"]


def test_upgrade_when_old_file_is_gone(old_and_new, recycle_bin):
    old, new = old_and_new
    old.unlink()
    assert replace_with_upgrade(new, old) == old
    assert old.read_bytes() == b"new 2160p"
    assert recycle_bin == []


def test_upgrade_keeps_both_if_recycle_bin_fails(old_and_new):
    old, new = old_and_new

    def broken_trash(path):
        raise OSError("Recycle Bin not available on this drive")

    final = replace_with_upgrade(new, old, trash=broken_trash)
    assert final.name == "Title [abc] (2).mp4"
    assert old.read_bytes() == b"old 1080p"  # nothing lost
    assert final.read_bytes() == b"new 2160p"


def test_upgrade_rename_retries_while_locked(old_and_new, recycle_bin):
    old, new = old_and_new
    calls = []

    def replace(a, b):
        calls.append((a.name, b.name))
        if b == old and sum(1 for _, dst in calls if dst == old.name) <= 2:
            raise winerror32()
        os.replace(a, b)

    final = replace_with_upgrade(new, old, replace=replace, sleep=lambda s: None)
    assert final == old and old.read_bytes() == b"new 2160p"


def test_upgrade_with_different_extension(tmp_path, recycle_bin):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "v.mkv"
    old.write_bytes(b"old")
    new = tmp_path / "v.mp4"
    new.write_bytes(b"new")
    final = replace_with_upgrade(new, old)
    assert final == out / "v.mp4"
    assert [p.name for p, _ in recycle_bin] == ["v.mkv"]


@pytest.mark.skipif(os.name != "nt", reason="exercise the real Recycle Bin on Windows CI only")
def test_real_send2trash_on_windows(tmp_path):
    # The autouse fake is bypassed here on purpose: this checks the real backend (the
    # ctypes SHFileOperation one, since pywin32 is not a dependency) actually works.
    from send2trash import send2trash

    f = tmp_path / "vidgrab-recycle-bin-test.txt"
    f.write_text("delete me")
    send2trash(str(f))
    assert not f.exists()
