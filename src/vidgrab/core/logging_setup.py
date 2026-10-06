"""File logging (``%LOCALAPPDATA%\\VidGrab\\logs\\vidgrab.log``) and a yt-dlp logger bridge."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

from vidgrab import APP_NAME, __version__

LOG_FILE_NAME = "vidgrab.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5
_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
_HANDLER_MARK = "_vidgrab_handler"


def default_log_dir() -> Path:
    return platformdirs.user_data_path(APP_NAME, appauthor=False, roaming=False) / "logs"


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """Configure the root logger. Safe to call more than once. Returns the log file path."""
    log_dir = log_dir or default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [file_handler]
    # --windowed builds have no console: sys.stderr is None there.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger(__name__).info(
        "%s %s starting (Python %s, frozen=%s)",
        APP_NAME,
        __version__,
        sys.version.split()[0],
        getattr(sys, "frozen", False),
    )
    return log_file


class YtDlpLogger:
    """Object passed as yt-dlp's ``logger`` param; forwards into the logging module."""

    def __init__(self, name: str = "vidgrab.ytdlp") -> None:
        self._log = logging.getLogger(name)

    def debug(self, msg: str) -> None:
        # yt-dlp sends both debug and plain info messages through debug().
        if msg.startswith("[debug] "):
            self._log.debug(msg)
        else:
            self._log.info(msg)

    def info(self, msg: str) -> None:
        self._log.info(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)
