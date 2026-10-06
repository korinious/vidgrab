import logging

from vidgrab.core.logging_setup import LOG_FILE_NAME, YtDlpLogger, setup_logging


def _vidgrab_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, "_vidgrab_handler", False)]


def test_setup_logging_writes_file_and_is_idempotent(tmp_path):
    try:
        log_file = setup_logging(tmp_path)
        setup_logging(tmp_path)
        assert log_file == tmp_path / LOG_FILE_NAME
        assert len([h for h in _vidgrab_handlers() if hasattr(h, "baseFilename")]) == 1

        logging.getLogger("vidgrab.test").info("hello αβγ")
        YtDlpLogger().warning("from yt-dlp")
        for h in _vidgrab_handlers():
            h.flush()
        text = log_file.read_text(encoding="utf-8")
        assert "hello αβγ" in text
        assert "from yt-dlp" in text
        assert "starting" in text
    finally:
        for h in _vidgrab_handlers():
            logging.getLogger().removeHandler(h)
            h.close()


def test_ytdlp_logger_levels(caplog):
    logger = YtDlpLogger()
    with caplog.at_level(logging.DEBUG, logger="vidgrab.ytdlp"):
        logger.debug("[debug] internals")
        logger.debug("[youtube] Extracting URL")
        logger.error("ERROR: bad")
    levels = [(r.levelno, r.message) for r in caplog.records]
    assert (logging.DEBUG, "[debug] internals") in levels
    assert (logging.INFO, "[youtube] Extracting URL") in levels
    assert (logging.ERROR, "ERROR: bad") in levels
