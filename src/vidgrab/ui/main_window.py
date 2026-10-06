"""Main window: URL input, preview, options, and the download queue."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import strings
from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import UserError
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import (
    MP3_BITRATES,
    AudioFormat,
    DownloadRequest,
    Quality,
    VideoContainer,
    VideoInfo,
    format_duration,
)
from vidgrab.core.options import YdlFactory, default_ydl_factory
from vidgrab.core.settings import Settings, save_settings
from vidgrab.ui.controller import DownloadController
from vidgrab.ui.dialogs import SettingsDialog
from vidgrab.ui.labels import (
    AUDIO_FORMAT_LABELS,
    AUDIO_FORMAT_ORDER,
    CONTAINER_LABELS,
    CONTAINER_ORDER,
    QUALITY_LABELS,
    QUALITY_ORDER,
    bitrate_label,
)
from vidgrab.ui.queue_widget import JobWidget
from vidgrab.ui.workers import MetadataWorker

log = logging.getLogger(__name__)

PREVIEW_THUMB = QSize(240, 135)


class ThumbnailLoader:
    """Fetches thumbnails asynchronously with an in-memory cache."""

    def __init__(self, parent: QWidget) -> None:
        self._nam = QNetworkAccessManager(parent)
        self._cache: dict[str, QPixmap] = {}

    def load(self, url: str | None, callback) -> None:
        if not url:
            return
        if url in self._cache:
            callback(self._cache[url])
            return
        reply = self._nam.get(QNetworkRequest(QUrl(url)))

        def done() -> None:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(reply.readAll()):
                    self._cache[url] = pixmap
                    callback(pixmap)
            else:
                log.info("Thumbnail fetch failed for %s: %s", url, reply.errorString())
            reply.deleteLater()

        reply.finished.connect(done)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        binaries: Binaries,
        settings_path: Path | None = None,
        log_file: Path | None = None,
        ydl_factory: YdlFactory = default_ydl_factory,
        load_thumbnails: bool = True,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.binaries = binaries
        self._settings_path = settings_path
        self._log_file = log_file
        self._ydl_factory = ydl_factory
        self._thumbs = ThumbnailLoader(self) if load_thumbnails else None
        self._metadata_worker: MetadataWorker | None = None  # the fetch whose result we want
        self._metadata_workers: set[MetadataWorker] = set()  # all still-running fetches
        self._current_info: VideoInfo | None = None
        self._job_items: dict[int, tuple[QListWidgetItem, JobWidget]] = {}

        self.controller = DownloadController(binaries, settings.max_concurrent, ydl_factory, self)
        self.controller.job_added.connect(self._on_job_added)
        self.controller.job_changed.connect(self._on_job_changed)
        self.controller.job_removed.connect(self._on_job_removed)

        self.setWindowTitle(strings.WINDOW_TITLE)
        self.resize(820, 680)
        self._build_ui()
        self._show_binary_warnings()

    # --- layout ------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.warning_banner = QLabel()
        self.warning_banner.setWordWrap(True)
        self.warning_banner.setStyleSheet(
            "background: #fff3cd; color: #664d03; padding: 6px; border-radius: 4px;"
        )
        self.warning_banner.hide()

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(strings.URL_PLACEHOLDER)
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.fetch_metadata)
        self.btn_paste = QPushButton(strings.BTN_PASTE)
        self.btn_paste.clicked.connect(self._paste_and_fetch)
        self.btn_fetch = QPushButton(strings.BTN_FETCH)
        self.btn_fetch.clicked.connect(self.fetch_metadata)
        url_row = QHBoxLayout()
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.btn_paste)
        url_row.addWidget(self.btn_fetch)

        self.preview_thumb = QLabel()
        self.preview_thumb.setFixedSize(PREVIEW_THUMB)
        self.preview_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_thumb.setStyleSheet("background: #202020; border-radius: 4px;")
        self.preview_title = QLabel(strings.LABEL_NO_PREVIEW)
        self.preview_title.setWordWrap(True)
        font = self.preview_title.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        font.setBold(True)
        self.preview_title.setFont(font)
        self.preview_meta = QLabel()
        self.preview_meta.setStyleSheet("color: gray;")
        self.preview_error = QLabel()
        self.preview_error.setWordWrap(True)
        self.preview_error.setStyleSheet("color: #c62828;")
        self.preview_error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.quality_combo = QComboBox()
        for q in QUALITY_ORDER:
            self.quality_combo.addItem(QUALITY_LABELS[q], q)
        self.quality_combo.setCurrentIndex(QUALITY_ORDER.index(self.settings.quality))
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)

        # Its items depend on the quality: MP4/MKV for video, MP3/Original for audio.
        self.format_combo = QComboBox()
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        self.bitrate_label = QLabel(strings.LABEL_BITRATE)
        self.bitrate_combo = QComboBox()
        for kbps in MP3_BITRATES:
            self.bitrate_combo.addItem(bitrate_label(kbps), kbps)
        self.bitrate_combo.setCurrentIndex(MP3_BITRATES.index(self.settings.mp3_bitrate))
        self.bitrate_combo.setToolTip(strings.TOOLTIP_BITRATE)
        self.bitrate_label.setToolTip(strings.TOOLTIP_BITRATE)
        self.bitrate_combo.currentIndexChanged.connect(self._on_bitrate_changed)
        self.btn_download = QPushButton(strings.BTN_DOWNLOAD)
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self.enqueue_current)
        options_row = QHBoxLayout()
        options_row.addWidget(QLabel(strings.LABEL_QUALITY))
        options_row.addWidget(self.quality_combo)
        options_row.addWidget(QLabel(strings.LABEL_FORMAT))
        options_row.addWidget(self.format_combo)
        options_row.addWidget(self.bitrate_label)
        options_row.addWidget(self.bitrate_combo)
        options_row.addStretch(1)
        options_row.addWidget(self.btn_download)

        preview_text = QVBoxLayout()
        preview_text.addWidget(self.preview_title)
        preview_text.addWidget(self.preview_meta)
        preview_text.addWidget(self.preview_error)
        preview_text.addStretch(1)
        preview_text.addLayout(options_row)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_thumb)
        preview_row.addLayout(preview_text, 1)

        self.dest_label = QLabel()
        self.dest_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._update_dest_label()
        btn_browse = QPushButton(strings.BTN_BROWSE)
        btn_browse.clicked.connect(self._choose_folder)
        btn_open_dest = QPushButton(strings.BTN_OPEN_FOLDER)
        btn_open_dest.clicked.connect(lambda: self._open_path(Path(self.settings.output_dir)))
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel(strings.LABEL_DESTINATION))
        dest_row.addWidget(self.dest_label, 1)
        dest_row.addWidget(btn_browse)
        dest_row.addWidget(btn_open_dest)

        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        btn_clear = QPushButton(strings.BTN_CLEAR_FINISHED)
        btn_clear.clicked.connect(self.controller.clear_finished)
        btn_settings = QPushButton(strings.BTN_SETTINGS)
        btn_settings.clicked.connect(self.open_settings)
        btn_logs = QPushButton(strings.BTN_OPEN_LOGS)
        btn_logs.clicked.connect(self._open_logs)
        btn_logs.setEnabled(self._log_file is not None)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(btn_clear)
        bottom_row.addStretch(1)
        bottom_row.addWidget(btn_logs)
        bottom_row.addWidget(btn_settings)

        queue_title = QLabel(strings.LABEL_QUEUE)
        queue_title.setStyleSheet("font-weight: bold;")

        root = QVBoxLayout()
        root.addWidget(self.warning_banner)
        root.addLayout(url_row)
        root.addLayout(preview_row)
        root.addLayout(dest_row)
        root.addWidget(queue_title)
        root.addWidget(self.queue_list, 1)
        root.addLayout(bottom_row)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        # Filled once the layout exists, so show/hide only ever touches parented widgets.
        self._fill_format_combo()

    def _show_binary_warnings(self) -> None:
        warnings = self.binaries.warnings()
        if warnings:
            self.warning_banner.setText("\n".join(warnings))
            self.warning_banner.show()

    # --- metadata ----------------------------------------------------------------------
    def _paste_and_fetch(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)
            self.fetch_metadata()

    def fetch_metadata(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        self._current_info = None
        self.btn_download.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.preview_error.clear()
        self.preview_meta.clear()
        self.preview_thumb.clear()
        self.preview_title.setText(strings.LABEL_FETCHING)

        worker = MetadataWorker(url, self.binaries, self.settings.cookies, self._ydl_factory, self)
        worker.succeeded.connect(lambda info, w=worker: self._on_metadata(w, info))
        worker.failed.connect(lambda err, w=worker: self._on_metadata_failed(w, err))
        worker.finished.connect(lambda w=worker: self._on_metadata_thread_finished(w))
        self._metadata_worker = worker
        self._metadata_workers.add(worker)
        worker.start()

    def _on_metadata(self, worker: MetadataWorker, info: VideoInfo) -> None:
        if worker is not self._metadata_worker:
            return  # superseded by a newer fetch
        self.btn_fetch.setEnabled(True)
        self._current_info = info
        self.preview_title.setText(info.title)
        meta = []
        if duration := format_duration(info.duration):
            meta.append(strings.LABEL_DURATION.format(duration=duration))
        if info.uploader:
            meta.append(strings.LABEL_UPLOADER.format(uploader=info.uploader))
        self.preview_meta.setText(" · ".join(meta))
        self.btn_download.setEnabled(True)
        if self._thumbs:
            self._thumbs.load(info.thumbnail_url, self._set_preview_thumb)

    def _on_metadata_thread_finished(self, worker: MetadataWorker) -> None:
        self._metadata_workers.discard(worker)
        if worker is self._metadata_worker:
            self._metadata_worker = None
        worker.deleteLater()

    def _set_preview_thumb(self, pixmap: QPixmap) -> None:
        self.preview_thumb.setPixmap(
            pixmap.scaled(
                PREVIEW_THUMB,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_metadata_failed(self, worker: MetadataWorker, error: UserError) -> None:
        if worker is not self._metadata_worker:
            return
        self.btn_fetch.setEnabled(True)
        self.preview_title.setText(strings.LABEL_NO_PREVIEW)
        self.preview_error.setText(error.message)
        self.preview_error.setToolTip(error.detail)

    # --- queue -------------------------------------------------------------------------
    def enqueue_current(self) -> DownloadJob | None:
        info = self._current_info
        if info is None:
            return None
        request = DownloadRequest(
            url=info.url,
            quality=self._selected_quality(),
            output_dir=Path(self.settings.output_dir),
            cookies=self.settings.cookies,
            title=info.title,
            container=self.settings.video_container,
            audio_format=self.settings.audio_format,
            mp3_bitrate=self.settings.mp3_bitrate,
        )
        job = self.controller.enqueue(request, info.thumbnail_url)
        self.statusBar().showMessage(strings.DOWNLOAD_ADDED.format(title=info.title), 4000)
        return job

    def _on_job_added(self, job: DownloadJob) -> None:
        widget = JobWidget(job)
        widget.cancel_requested.connect(self.controller.cancel)
        widget.retry_requested.connect(self.controller.retry)
        widget.remove_requested.connect(self.controller.remove)
        widget.upgrade_requested.connect(self.controller.retry_full_quality)
        widget.open_requested.connect(self._open_job)
        widget.details_requested.connect(self._show_job_details)
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.queue_list.addItem(item)
        self.queue_list.setItemWidget(item, widget)
        self._job_items[job.id] = (item, widget)
        if self._thumbs:
            self._thumbs.load(job.thumbnail_url, widget.set_thumbnail)

    def _on_job_changed(self, job: DownloadJob) -> None:
        entry = self._job_items.get(job.id)
        if entry:
            entry[1].update_job(job)

    def _on_job_removed(self, job_id: int) -> None:
        entry = self._job_items.pop(job_id, None)
        if entry:
            row = self.queue_list.row(entry[0])
            self.queue_list.takeItem(row)
            entry[1].deleteLater()

    def _open_job(self, job_id: int) -> None:
        job = self.controller.queue.get(job_id)
        target = job.output_path or job.request.output_dir
        self._open_path(target, select=job.output_path is not None)

    def _show_job_details(self, job_id: int) -> None:
        job = self.controller.queue.get(job_id)
        if job.error is None:
            return
        box = QMessageBox(
            QMessageBox.Icon.Warning, strings.DIALOG_ERROR_TITLE, job.error.message, parent=self
        )
        box.setDetailedText(f"{job.request.url}\n\n{job.error.detail}")
        box.exec()

    # --- settings ----------------------------------------------------------------------
    def _save_settings(self) -> None:
        try:
            save_settings(self.settings, self._settings_path)
        except OSError:
            log.exception("Could not save settings")

    def _selected_quality(self) -> Quality:
        # QComboBox hands StrEnum item data back as plain str; convert at the boundary.
        return Quality(self.quality_combo.currentData())

    def _on_quality_changed(self) -> None:
        self.settings = replace(self.settings, quality=self._selected_quality())
        self._fill_format_combo()
        self._save_settings()

    def _fill_format_combo(self) -> None:
        """Show the format choices for the current quality, preselecting the saved one."""
        combo = self.format_combo
        combo.blockSignals(True)
        combo.clear()
        if self._selected_quality().is_audio:
            for fmt in AUDIO_FORMAT_ORDER:
                combo.addItem(AUDIO_FORMAT_LABELS[fmt], fmt)
            combo.setCurrentIndex(AUDIO_FORMAT_ORDER.index(self.settings.audio_format))
            combo.setToolTip(strings.TOOLTIP_FORMAT_AUDIO)
        else:
            for container in CONTAINER_ORDER:
                combo.addItem(CONTAINER_LABELS[container], container)
            combo.setCurrentIndex(CONTAINER_ORDER.index(self.settings.video_container))
            combo.setToolTip(strings.TOOLTIP_FORMAT_VIDEO)
        combo.blockSignals(False)
        self._sync_bitrate_visibility()

    def _sync_bitrate_visibility(self) -> None:
        show = self._selected_quality().is_audio and self.settings.audio_format is AudioFormat.MP3
        self.bitrate_label.setVisible(show)
        self.bitrate_combo.setVisible(show)

    def _on_format_changed(self) -> None:
        data = self.format_combo.currentData()
        if data is None:
            return
        # QComboBox hands StrEnum item data back as plain str; convert at the boundary.
        if self._selected_quality().is_audio:
            self.settings = replace(self.settings, audio_format=AudioFormat(data))
        else:
            self.settings = replace(self.settings, video_container=VideoContainer(data))
        self._sync_bitrate_visibility()
        self._save_settings()

    def _on_bitrate_changed(self) -> None:
        self.settings = replace(self.settings, mp3_bitrate=int(self.bitrate_combo.currentData()))
        self._save_settings()

    def _update_dest_label(self) -> None:
        self.dest_label.setText(self.settings.output_dir)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, strings.DIALOG_CHOOSE_FOLDER, self.settings.output_dir
        )
        if folder:
            self.set_output_dir(folder)

    def set_output_dir(self, folder: str) -> None:
        self.settings = replace(self.settings, output_dir=str(Path(folder)))
        self._update_dest_label()
        self._save_settings()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.apply_settings(dialog.result_settings())

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.controller.set_max_concurrent(settings.max_concurrent)
        self._save_settings()

    # --- helpers -----------------------------------------------------------------------
    def _open_logs(self) -> None:
        if self._log_file:
            self._open_path(self._log_file.parent)

    def _open_path(self, path: Path, select: bool = False) -> None:
        if select and os.name == "nt" and path.exists():
            # Open Explorer with the file selected.
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
        target = path if path.is_dir() else path.parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            QMessageBox.warning(
                self, strings.DIALOG_ERROR_TITLE, strings.OPEN_FILE_FAILED.format(path=target)
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.has_active:
            answer = QMessageBox.question(
                self, strings.CONFIRM_EXIT_TITLE, strings.CONFIRM_EXIT_TEXT
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.controller.shutdown()
        # yt-dlp metadata calls cannot be interrupted; give them a moment, then let the
        # process exit (QThread objects are parented to this window).
        for worker in list(self._metadata_workers):
            worker.wait(2000)
        event.accept()
