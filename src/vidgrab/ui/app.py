"""Application bootstrap."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtWidgets import QApplication

from vidgrab import APP_NAME, __version__
from vidgrab.core.binaries import find_binaries, log_component_versions
from vidgrab.core.logging_setup import setup_logging
from vidgrab.core.settings import default_settings_path, load_settings
from vidgrab.core.staging import cleanup_orphans
from vidgrab.ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _log_uncaught(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def run_gui(argv: list[str] | None = None) -> int:
    log_file = setup_logging()
    sys.excepthook = _log_uncaught
    log_component_versions()
    try:
        cleanup_orphans()  # staging folders left by a crash or a killed process
    except OSError:
        log.exception("Could not clean up old staging folders")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    settings_path = default_settings_path()
    window = MainWindow(
        settings=load_settings(settings_path),
        binaries=find_binaries(),
        settings_path=settings_path,
        log_file=log_file,
    )
    window.show()
    code = app.exec()
    log.info("%s exiting with code %d", APP_NAME, code)
    return code
