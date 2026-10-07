"""One card in the download queue."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from vidgrab import strings
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import JobStatus, Quality
from vidgrab.ui.labels import (
    completed_status_text,
    job_chip_text,
    job_status_text,
    lower_resolution_chip,
)
from vidgrab.ui.theme import tabular
from vidgrab.ui.widgets import (
    ElidedLabel,
    IconButton,
    IconLabel,
    Thumbnail,
    chip,
    set_prop,
    text_button,
)

THUMB_SIZE = (96, 54)

# Status icon and text tone per job state.
_STATUS_STYLE: dict[JobStatus, tuple[str, str]] = {
    JobStatus.QUEUED: ("clock", "muted"),
    JobStatus.DOWNLOADING: ("download", "muted"),
    JobStatus.POSTPROCESSING: ("refresh-cw", "muted"),
    JobStatus.CANCELLING: ("x", "muted"),
    JobStatus.COMPLETED: ("circle-check", "success"),
    JobStatus.FAILED: ("circle-alert", "error"),
    JobStatus.CANCELLED: ("x", "muted"),
}


class JobWidget(QFrame):
    cancel_requested = Signal(int)
    retry_requested = Signal(int)
    remove_requested = Signal(int)
    open_requested = Signal(int)  # show in folder
    open_file_requested = Signal(int)
    details_requested = Signal(int)
    upgrade_requested = Signal(int)

    def __init__(self, job: DownloadJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.job_id = job.id
        self._size_bytes: int | None = None

        self.thumb = Thumbnail(*THUMB_SIZE)
        self.thumb.set_audio(Quality(job.request.quality).is_audio)

        self.title = ElidedLabel(job.request.title or job.request.url)
        self.title.setProperty("role", "job-title")
        self.quality = chip(job_chip_text(job))  # e.g. "2160p · MP4"
        self.resolution_chip = chip(tone="warning")  # e.g. "1080p αντί 2160p"
        self.resolution_chip.hide()

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setAccessibleName(strings.STATUS_DOWNLOADING)

        self.status_icon = IconLabel("clock", "muted", 16)
        self.status = QLabel()
        self.status.setProperty("tone", "muted")
        self.status.setFont(tabular(self.status.font()))  # numbers don't jitter
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        def emit(signal):
            return lambda: signal.emit(self.job_id)

        self.btn_upgrade = text_button(
            strings.BTN_RETRY_FULL_QUALITY, "warning", "refresh-cw", "warning"
        )
        self.btn_upgrade.setToolTip(strings.BTN_RETRY_FULL_QUALITY)
        self.btn_retry = text_button(strings.BTN_RETRY, None, "rotate-ccw")
        self.btn_details = IconButton("info", strings.BTN_DETAILS)
        self.btn_open = IconButton("external-link", strings.BTN_OPEN_FILE)
        self.btn_show = IconButton("folder-open", strings.BTN_SHOW_IN_FOLDER)
        self.btn_cancel = IconButton("x", strings.BTN_CANCEL)
        self.btn_remove = IconButton("trash-2", strings.BTN_REMOVE, "muted")
        self.btn_upgrade.clicked.connect(emit(self.upgrade_requested))
        self.btn_retry.clicked.connect(emit(self.retry_requested))
        self.btn_details.clicked.connect(emit(self.details_requested))
        self.btn_open.clicked.connect(emit(self.open_file_requested))
        self.btn_show.clicked.connect(emit(self.open_requested))
        self.btn_cancel.clicked.connect(emit(self.cancel_requested))
        self.btn_remove.clicked.connect(emit(self.remove_requested))

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.title, 1)
        top.addWidget(self.resolution_chip)
        top.addWidget(self.quality)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.status, 1)
        for button in (
            self.btn_upgrade,
            self.btn_retry,
            self.btn_details,
            self.btn_open,
            self.btn_show,
            self.btn_cancel,
            self.btn_remove,
        ):
            bottom.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        text_col.addLayout(top)
        text_col.addWidget(self.progress)
        text_col.addLayout(bottom)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 10, 10)
        root.setSpacing(12)
        root.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(text_col, 1)

        self.update_job(job)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb.setPixmap(pixmap)

    def update_job(self, job: DownloadJob) -> None:
        status = job.status
        icon_name, tone = _STATUS_STYLE[status]
        self.status_icon.set_icon(icon_name, tone)
        set_prop(self.status, "tone", tone)

        if status is JobStatus.COMPLETED:
            if job.output_path is not None and self._size_bytes is None:
                with contextlib.suppress(OSError):
                    self._size_bytes = job.output_path.stat().st_size
            self.status.setText(completed_status_text(job, self._size_bytes))
            self.status.setToolTip(str(job.output_path or ""))
        else:
            self._size_bytes = None
            self.status.setText(job_status_text(job))
            if job.error:
                self.status.setToolTip(f"{job.error.message}\n\n{job.error.detail}".strip())
            else:
                self.status.setToolTip("")

        self.quality.setText(job_chip_text(job))
        chip_info = lower_resolution_chip(job)
        self.resolution_chip.setVisible(chip_info is not None)
        if chip_info is not None:
            self.resolution_chip.setText(chip_info[0])
            self.resolution_chip.setToolTip(chip_info[1])

        frac = job.progress.overall_fraction if job.progress else None
        running = status in (JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING)
        if status is JobStatus.COMPLETED:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
        elif running and frac is None:
            self.progress.setRange(0, 0)  # busy indicator
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int((frac or 0) * 100))
        self.progress.setVisible(status in (JobStatus.QUEUED, JobStatus.CANCELLING) or running)

        self.btn_upgrade.setVisible(job.can_upgrade)
        self.btn_retry.setVisible(job.can_retry)
        self.btn_details.setVisible(status is JobStatus.FAILED and job.error is not None)
        self.btn_open.setVisible(status is JobStatus.COMPLETED and job.output_path is not None)
        self.btn_show.setVisible(status is JobStatus.COMPLETED)
        self.btn_cancel.setVisible(job.can_cancel)
        self.btn_remove.setVisible(status.is_finished)
