"""Asynchronously load and cache App Store artwork for the desktop UI."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import (
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
    QNetworkAccessManager,
)


ArtworkCallback = Callable[[QPixmap | None], None]


class ArtworkLoader:
    """Share requests and a small on-disk cache across search result rows."""

    def __init__(self, parent=None) -> None:
        self.manager = QNetworkAccessManager(parent)
        self.cache = QNetworkDiskCache(self.manager)
        cache_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        self.cache.setCacheDirectory(f"{cache_root}/artwork")
        self.cache.setMaximumCacheSize(25 * 1024 * 1024)
        self.manager.setCache(self.cache)
        self._memory: dict[str, QPixmap] = {}
        self._waiting: dict[str, list[ArtworkCallback]] = {}

    def load(self, url: str, callback: ArtworkCallback) -> None:
        """Return cached artwork immediately or fetch it without blocking Qt."""

        if not url:
            callback(None)
            return
        if pixmap := self._memory.get(url):
            callback(pixmap)
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return

        self._waiting[url] = [callback]
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        reply = self.manager.get(request)
        reply.finished.connect(lambda: self._finished(url, reply))

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        pixmap = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            candidate = QPixmap()
            if candidate.loadFromData(reply.readAll()):
                pixmap = candidate
                self._memory[url] = candidate
        reply.deleteLater()
        for callback in self._waiting.pop(url, []):
            callback(pixmap)
