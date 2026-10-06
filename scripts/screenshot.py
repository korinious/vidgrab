"""Render the main window headless with fake data and save a PNG (for docs/screenshot.png).

    uv run python scripts/screenshot.py docs/screenshot.png

Everything the demo writes (settings, "downloaded" files) goes to a temporary directory;
only the PNG is written to the given path.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtWidgets import QApplication  # noqa: E402
from yt_dlp.utils import DownloadError  # noqa: E402

from conftest import FakeYdlFactory  # noqa: E402
from vidgrab.core.binaries import Binaries  # noqa: E402
from vidgrab.core.models import JobStatus, Quality  # noqa: E402
from vidgrab.core.settings import Settings  # noqa: E402
from vidgrab.ui.main_window import MainWindow  # noqa: E402


def main(out_png: Path) -> None:
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="vidgrab-demo-") as tmp:
        tmp_dir = Path(tmp)
        fake = FakeYdlFactory()
        fake.scenario.info["title"] = "Πώς δουλεύει το FFmpeg — πλήρης οδηγός"
        win = MainWindow(
            Settings(output_dir=str(tmp_dir / "Downloads")),
            # deno left out on purpose to show the warning banner
            Binaries(ffmpeg=tmp_dir / "ffmpeg", ffprobe=tmp_dir / "ffprobe"),
            settings_path=tmp_dir / "settings.json",
            ydl_factory=fake,
            load_thumbnails=False,
        )
        win.resize(860, 700)
        win.show()

        def pump(condition, timeout=5.0):
            end = time.monotonic() + timeout
            while time.monotonic() < end and not condition():
                app.processEvents()
                time.sleep(0.01)

        win.url_edit.setText("https://youtu.be/abc123")
        win.fetch_metadata()
        pump(win.btn_fetch.isEnabled)

        fake.scenario.final_name = "done.mp4"
        done = win.enqueue_current()
        pump(lambda: done.status is JobStatus.COMPLETED)

        fake.scenario.final_name = None
        fake.scenario.error = DownloadError(
            "ERROR: [instagram] x: Requested content is not available, "
            "rate-limit reached or login required"
        )
        fake.scenario.progress_events = [{"status": "downloading", "create": "a"}]
        failed = win.enqueue_current()
        pump(lambda: failed.status is JobStatus.FAILED)

        fake.scenario.error = None
        gate = threading.Event()
        info = {"requested_formats": [{}, {}]}
        event = {
            "status": "downloading",
            "create": "v.f137.mp4",
            "downloaded_bytes": 42_000_000,
            "total_bytes": 100_000_000,
            "speed": 3_500_000,
            "eta": 17,
            "info_dict": info,
        }
        fake.scenario.progress_events = [event, event]
        fake.scenario.between_events = lambda i: gate.wait(10) if i == 1 else None
        win.quality_combo.setCurrentIndex(win.quality_combo.findData(Quality.P1080))
        running = win.enqueue_current()
        pump(lambda: running.progress is not None)
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)

        out_png.parent.mkdir(parents=True, exist_ok=True)
        win.grab().save(str(out_png))
        gate.set()
        win.controller.shutdown()
    print(f"saved {out_png}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshot.png"))
