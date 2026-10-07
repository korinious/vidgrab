"""Write src/vidgrab/ui/assets/vidgrab.ico from the same drawing as the header logo.

    uv run python scripts/make_icon.py

Each size is drawn natively (not downscaled) and stored as a PNG entry, which every
Windows version since Vista reads. Re-run after changing ui/logo.py.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vidgrab.ui.icons import APP_ICON  # noqa: E402
from vidgrab.ui.logo import logo_image  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    logo_image(size).save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build_ico(sizes=SIZES) -> bytes:
    images = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in zip(sizes, images, strict=True):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        blobs += blob
    return header + entries + blobs


def main(out: Path = APP_ICON) -> None:
    _app = QGuiApplication([])
    out.write_bytes(build_ico())
    print(f"wrote {out} ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
