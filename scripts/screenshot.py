"""Render the main window headless with fake data, in the dark and the light theme.

    uv run python scripts/screenshot.py docs        # docs/screenshot-dark.png + -light.png

The queue shows the same four states in both: completed below the requested resolution
(amber chip + "Ξανά σε πλήρη ποιότητα"), failed with HTTP 403, downloading, and an MP3
waiting its turn. Everything the demo writes (settings, "downloaded" files, staging) goes
to a temporary directory; only the PNGs are written to the given folder.
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

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from yt_dlp.utils import DownloadError  # noqa: E402

from conftest import FakeYdlFactory  # noqa: E402
from vidgrab.core import downloader  # noqa: E402
from vidgrab.core.binaries import Binaries, component_versions  # noqa: E402
from vidgrab.core.models import AudioFormat, JobStatus, Quality, VideoContainer  # noqa: E402
from vidgrab.core.settings import Settings  # noqa: E402
from vidgrab.ui.main_window import MainWindow  # noqa: E402
from vidgrab.ui.theme import ThemeMode  # noqa: E402

# The versions pinned in .github/workflows/build.yml.
FFMPEG_VERSION = "8.0"
DENO_VERSION = "2.9.6"


def fake_thumbnail(top: str, bottom: str, accent: str) -> QPixmap:
    """A generated 16:9 'video frame' (no real thumbnails, no network)."""
    pixmap = QPixmap(480, 270)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(480, 270))
    gradient.setColorAt(0, QColor(top))
    gradient.setColorAt(1, QColor(bottom))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(QRectF(300, 40, 150, 150))
    painter.setBrush(QColor(255, 255, 255, 40))
    painter.drawRoundedRect(QRectF(40, 170, 220, 22), 8, 8)
    painter.drawRoundedRect(QRectF(40, 205, 150, 22), 8, 8)
    painter.end()
    return pixmap


def pump(app: QApplication, condition, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and not condition():
        app.processEvents()
        time.sleep(0.01)


def settle(app: QApplication) -> None:
    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)


def render(app: QApplication, mode: ThemeMode, out_png: Path, tmp_dir: Path) -> None:
    fake = FakeYdlFactory()
    fake.scenario.info.update(
        title="Πώς δουλεύει το FFmpeg — πλήρης οδηγός",
        uploader="Κανάλι Τεχνολογίας",
        duration=1394,
    )
    win = MainWindow(
        Settings(output_dir=str(tmp_dir / "Downloads"), max_concurrent=1),
        Binaries(ffmpeg=tmp_dir / "ffmpeg", ffprobe=tmp_dir / "ffprobe", deno=tmp_dir / "deno"),
        settings_path=tmp_dir / "settings.json",
        ydl_factory=fake,
        load_thumbnails=False,
    )
    win.set_theme(mode)
    win.set_versions(
        {
            "yt-dlp": component_versions().get("yt-dlp"),
            "ffmpeg": FFMPEG_VERSION,
            "deno": DENO_VERSION,
        }
    )
    win.resize(1180, 980)
    win.show()

    def choose(combo, value):
        combo.setCurrentIndex(combo.findData(value))

    thumbs = [
        fake_thumbnail("#1E293B", "#0F172A", "#DC2626"),
        fake_thumbnail("#3F3F46", "#18181B", "#F59E0B"),
        fake_thumbnail("#14532D", "#052E16", "#86EFAC"),
    ]

    def enqueue(title: str, thumb: QPixmap | None, error: Exception | None = None):
        fake.scenario.info["title"] = title
        win.url_edit.setText("https://www.youtube.com/watch?v=abc123")
        win.fetch_metadata()
        pump(app, win.btn_fetch.isEnabled)
        fake.scenario.error = error  # only the download fails, not the preview
        job = win.enqueue_current()
        if thumb is not None:
            win._job_items[job.id][1].set_thumbnail(thumb)
        return job

    uhd = {"format_id": "401", "height": 2160, "vcodec": "av01", "ext": "mp4"}
    fhd = {"format_id": "137", "height": 1080, "vcodec": "avc1", "ext": "mp4"}
    audio = {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"}

    # 1. Completed, but YouTube delivered 1080p of a 4K video: amber chip + upgrade button.
    choose(win.quality_combo, Quality.BEST)
    choose(win.format_combo, VideoContainer.MP4)
    fake.scenario.info.update(formats=[uhd, fhd, audio], requested_formats=[fhd, audio])
    fake.scenario.final_name = "done.mp4"
    done = enqueue("Ταξίδι στην Κρήτη — 4K drone", thumbs[0])
    pump(app, lambda: done.status is JobStatus.COMPLETED)
    fake.scenario.info.pop("requested_formats")
    os.truncate(done.output_path, 812 * 1024 * 1024)  # sparse; shows a realistic size
    widget = win._job_items[done.id][1]
    widget._size_bytes = None
    widget.update_job(done)

    # 2. Failed with HTTP 403 (after the automatic retries).
    fake.scenario.final_name = None
    forbidden = DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    failed = enqueue("Συναυλία στο Ηρώδειο (ζωντανά)", thumbs[1], forbidden)
    pump(app, lambda: failed.status is JobStatus.FAILED)
    fake.scenario.error = None

    # 3. Downloading, held at 42 % until the screenshot is taken.
    gate = threading.Event()
    event = {
        "status": "downloading",
        "create": "v.f401.mp4",
        "downloaded_bytes": 1_310_000_000,
        "total_bytes": 3_120_000_000,
        "speed": 18_400_000,
        "eta": 98,
        "info_dict": {"requested_formats": [{}, {}]},
    }
    fake.scenario.progress_events = [event, event]
    fake.scenario.between_events = lambda i: gate.wait(20) if i == 1 else None
    running = enqueue("Πώς δουλεύει το FFmpeg — πλήρης οδηγός", thumbs[2])
    pump(app, lambda: running.progress is not None)

    # 4. MP3 192 kbps waiting (max 1 concurrent download); this also leaves the preview
    #    showing the audio choices.
    choose(win.quality_combo, Quality.AUDIO)
    choose(win.format_combo, AudioFormat.MP3)
    choose(win.bitrate_combo, 192)
    enqueue("Podcast: Ιστορίες της Αθήνας, επ. 12", None)

    # Preview card for the last link, with a generated thumbnail.
    win.preview_thumb.setPixmap(thumbs[0])
    win.url_edit.setText("https://www.youtube.com/watch?v=abc123")
    win.url_edit.setFocus()
    win.clipboard_hint.hide()
    settle(app)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(out_png))
    gate.set()
    win.controller.shutdown()
    win.hide()  # close() would ask to confirm cancelling the queued MP3
    win.deleteLater()
    settle(app)
    print(f"saved {out_png}")


def main(out_dir: Path) -> None:
    app = QApplication([])
    # No real waiting between the 403 retries.
    downloader.DEFAULT_POLICY = downloader.RetryPolicy(
        forbidden_delays=(0, 0), move_backoff=(0, 0, 0), sleep=lambda s: None
    )
    with tempfile.TemporaryDirectory(prefix="vidgrab-demo-") as tmp:
        tmp_dir = Path(tmp)
        os.environ["VIDGRAB_TMP_DIR"] = str(tmp_dir / "staging")  # not the real app data
        os.environ["APPDATA"] = str(tmp_dir / "appdata")
        for mode in (ThemeMode.DARK, ThemeMode.LIGHT):
            work = tmp_dir / mode.value
            work.mkdir()
            render(app, mode, out_dir / f"screenshot-{mode.value}.png", work)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs"))
