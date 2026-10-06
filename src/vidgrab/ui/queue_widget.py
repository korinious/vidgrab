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
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import strings
from vidgrab.core.jobqueue import DownloadJob
from vidgrab.core.models import JobStatus
from vidgrab.ui.labels import job_status_text, lower_resolution_chip, request_format_text

THUMB_SIZE = (96, 54)


class JobWidget(QWidget):
    cancel_requested = Signal(int)
    retry_requested = Signal(int)
    remove_requested = Signal(int)
    upgrade_requested = Signal(int)
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

        self.quality = QLabel(request_format_text(job.request))
        self.quality.setStyleSheet("color: gray;")

        # Amber chip, e.g. "1080p αντί 2160p", when the saved video is below what was asked.
        self.resolution_chip = QLabel()
        self.resolution_chip.setStyleSheet(
            "background: #ffe8b0; color: #7a4a00; border: 1px solid #f0b429;"
            " border-radius: 8px; padding: 1px 6px;"
        )
        self.resolution_chip.hide()

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
        # Icon button next to the amber chip: download again, keep only if better.
        self.btn_upgrade = QToolButton()
        self.btn_upgrade.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_upgrade.setToolTip(strings.BTN_RETRY_FULL_QUALITY)
        self.btn_upgrade.setAccessibleName(strings.BTN_RETRY_FULL_QUALITY)
        self.btn_upgrade.setAutoRaise(True)
        self.btn_upgrade.clicked.connect(lambda: self.upgrade_requested.emit(self.job_id))
        self.btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.job_id))
        self.btn_retry.clicked.connect(lambda: self.retry_requested.emit(self.job_id))
        self.btn_open.clicked.connect(lambda: self.open_requested.emit(self.job_id))
        self.btn_details.clicked.connect(lambda: self.details_requested.emit(self.job_id))
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self.job_id))

        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.resolution_chip)
        header.addWidget(self.btn_upgrade)
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

        chip = lower_resolution_chip(job)
        self.resolution_chip.setVisible(chip is not None)
        if chip is not None:
            self.resolution_chip.setText(chip[0])
            self.resolution_chip.setToolTip(chip[1])

        self.btn_upgrade.setVisible(job.can_upgrade)
        self.btn_cancel.setVisible(job.can_cancel)
        self.btn_retry.setVisible(job.can_retry)
        self.btn_open.setVisible(status is JobStatus.COMPLETED)
        self.btn_details.setVisible(status is JobStatus.FAILED and job.error is not None)
        self.btn_remove.setVisible(status.is_finished)
