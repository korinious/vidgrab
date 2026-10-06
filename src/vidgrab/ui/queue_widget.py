"""One row in the download queue."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vidgrab import strings
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import JobStatus
from vidgrab.ui.labels import QUALITY_LABELS, job_status_text

THUMB_SIZE = (96, 54)


class JobWidget(QWidget):
    cancel_requested = Signal(int)
    retry_requested = Signal(int)
    remove_requested = Signal(int)
    open_requested = Signal(int)
    details_requested = Signal(int)

    def __init__(self, job: DownloadJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job_id = job.id

        self.thumb = QLabel()
        self.thumb.setFixedSize(*THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #202020; border-radius: 3px;")

        self.title = QLabel(job.request.title or job.request.url)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)

        self.quality = QLabel(QUALITY_LABELS[job.request.quality])
        self.quality.setStyleSheet("color: gray;")

        self.status = QLabel()
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)

        self.btn_cancel = QPushButton(strings.BTN_CANCEL)
        self.btn_retry = QPushButton(strings.BTN_RETRY)
        self.btn_open = QPushButton(strings.BTN_OPEN_FOLDER)
        self.btn_details = QPushButton(strings.BTN_DETAILS)
        self.btn_remove = QPushButton(strings.BTN_REMOVE)
        self.btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.job_id))
        self.btn_retry.clicked.connect(lambda: self.retry_requested.emit(self.job_id))
        self.btn_open.clicked.connect(lambda: self.open_requested.emit(self.job_id))
        self.btn_details.clicked.connect(lambda: self.details_requested.emit(self.job_id))
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self.job_id))

        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.quality)

        text_col = QVBoxLayout()
        text_col.addLayout(header)
        text_col.addWidget(self.progress)
        text_col.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for btn in (
            self.btn_cancel,
            self.btn_retry,
            self.btn_open,
            self.btn_details,
            self.btn_remove,
        ):
            buttons.addWidget(btn)

        right = QVBoxLayout()
        right.addLayout(text_col)
        right.addLayout(buttons)

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(right, 1)

        self.update_job(job)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb.setPixmap(
            pixmap.scaled(
                *THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def update_job(self, job: DownloadJob) -> None:
        status = job.status
        self.status.setText(job_status_text(job))
        # The row may cut a long message short; the tooltip always has all of it.
        tooltip = f"{job.error.message}\n\n{job.error.detail}".strip() if job.error else ""
        self.status.setToolTip(tooltip)
        color = {JobStatus.FAILED: "#c62828", JobStatus.COMPLETED: "#2e7d32"}.get(status, "")
        self.status.setStyleSheet(f"color: {color};" if color else "")

        frac = job.progress.overall_fraction if job.progress else None
        if status is JobStatus.COMPLETED:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
        elif status in (JobStatus.DOWNLOADING, JobStatus.POSTPROCESSING) and frac is None:
            self.progress.setRange(0, 0)  # busy indicator
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int((frac or 0) * 100))

        self.btn_cancel.setVisible(job.can_cancel)
        self.btn_retry.setVisible(job.can_retry)
        self.btn_open.setVisible(status is JobStatus.COMPLETED)
        self.btn_details.setVisible(status is JobStatus.FAILED and job.error is not None)
        self.btn_remove.setVisible(status.is_finished)
