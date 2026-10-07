"""Thumbnail downloads for the preview, the queue cards and the list selection grid."""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

log = logging.getLogger(__name__)

PixmapCallback = Callable[[QPixmap], None]


class ThumbnailLoader:
    """Fetches thumbnails asynchronously, at most ``max_parallel`` at a time, with a cache.

    The selection grid asks only for the cards that are on screen, so a 500-video playlist
    does not start 500 requests at once.
    """

    def __init__(self, parent: QObject, max_parallel: int = 6) -> None:
        self._nam = QNetworkAccessManager(parent)
        self._cache: dict[str, QPixmap] = {}
        self._waiting: deque[tuple[str, PixmapCallback]] = deque()
        self._in_flight = 0
        self._max_parallel = max(1, max_parallel)

    def load(self, url: str | None, callback: PixmapCallback) -> None:
        if not url:
            return
        if url in self._cache:
            callback(self._cache[url])
            return
        self._waiting.append((url, callback))
        self._start_next()

    def _start_next(self) -> None:
        while self._waiting and self._in_flight < self._max_parallel:
            url, callback = self._waiting.popleft()
            if url in self._cache:
                callback(self._cache[url])
                continue
            self._in_flight += 1
            reply = self._nam.get(QNetworkRequest(QUrl(url)))
            reply.finished.connect(lambda r=reply, u=url, c=callback: self._done(r, u, c))

    def _done(self, reply: QNetworkReply, url: str, callback: PixmapCallback) -> None:
        self._in_flight -= 1
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._cache[url] = pixmap
                # RuntimeError: the card was closed while the image was loading.
                with contextlib.suppress(RuntimeError):
                    callback(pixmap)
        else:
            log.info("Thumbnail fetch failed for %s: %s", url, reply.errorString())
        reply.deleteLater()
        self._start_next()
