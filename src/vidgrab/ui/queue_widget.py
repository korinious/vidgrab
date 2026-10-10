"""One card in the download queue."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import strings
from vidgrab.core.jobqueue import DownloadJob, GroupProgress, JobGroup
from vidgrab.core.models import JobStatus, Quality
from vidgrab.ui.labels import (
    completed_status_text,
    job_chip_text,
    job_status_text,
    lower_resolution_chip,
    platform_name,
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
    trash_file_requested = Signal(int)  # move the finished file to the Recycle Bin

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
        self.btn_remove = IconButton("x", strings.BTN_REMOVE, "muted")  # list only, not the file
        # File actions that need a confirmation live in a menu ("⋯" and right click).
        self.menu = QMenu(self)
        self.action_remove = self.menu.addAction(strings.BTN_REMOVE)
        self.action_remove.triggered.connect(emit(self.remove_requested))
        self.action_trash = self.menu.addAction(strings.MENU_TRASH_FILE)
        self.action_trash.triggered.connect(emit(self.trash_file_requested))
        self.btn_more = IconButton("ellipsis", strings.BTN_MORE_ACTIONS)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_more.setMenu(self.menu)
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
            self.btn_more,
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
            elif job.cooldown_s:
                self.status.setToolTip(strings.TOOLTIP_COOLDOWN)
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
        has_file = status is JobStatus.COMPLETED and job.output_path is not None
        self.action_trash.setVisible(has_file)
        self.action_remove.setVisible(status.is_finished)
        self.btn_more.setVisible(has_file)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if any(action.isVisible() for action in self.menu.actions()):
            self.menu.exec(event.globalPos())


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


class GroupHeader(QFrame):
    """Header card of a list in the queue: title, "7/12" + slim bar, bulk actions."""

    cancel_all_requested = Signal(int)  # group id
    retry_failed_requested = Signal(int)
    expanded_changed = Signal(int, bool)

    def __init__(self, group: JobGroup, expanded: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("role", "group")
        self.group_id = group.id
        self._expanded = expanded

        self.btn_toggle = IconButton("chevron-down", strings.BTN_COLLAPSE)
        self.btn_toggle.clicked.connect(lambda: self.set_expanded(not self._expanded, emit=True))
        self.title = ElidedLabel(group.title)
        self.title.setProperty("role", "job-title")
        self.platform = chip(platform_name(group.platform))
        self.skipped = chip(
            plural(group.skipped, strings.GROUP_SKIPPED_ONE, strings.GROUP_SKIPPED_MANY),
            tone="success",
        )
        self.failed = chip(tone="error")

        self.count = QLabel()
        self.count.setProperty("tone", "muted")
        self.count.setFont(tabular(self.count.font()))
        self.progress = QProgressBar()
        self.progress.setProperty("role", "slim")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setRange(0, 1000)

        self.btn_retry_failed = text_button(strings.BTN_RETRY_FAILED, None, "rotate-ccw")
        self.btn_retry_failed.clicked.connect(
            lambda: self.retry_failed_requested.emit(self.group_id)
        )
        self.btn_cancel_all = text_button(strings.BTN_CANCEL_ALL, None, "x")
        self.btn_cancel_all.clicked.connect(lambda: self.cancel_all_requested.emit(self.group_id))

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.btn_toggle)
        top.addWidget(self.title, 1)
        top.addWidget(self.failed)
        top.addWidget(self.skipped)
        top.addWidget(self.platform)
        top.addWidget(self.count)
        top.addWidget(self.btn_retry_failed)
        top.addWidget(self.btn_cancel_all)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 12, 10)
        root.setSpacing(6)
        root.addLayout(top)
        bar = QHBoxLayout()
        bar.setContentsMargins(50, 0, 0, 0)  # under the title, not the chevron
        bar.addWidget(self.progress)
        root.addLayout(bar)
        # Visibility only once parented (a shown parentless widget becomes a window).
        self.platform.setVisible(bool(platform_name(group.platform)))
        self.skipped.setVisible(group.skipped > 0)
        self.failed.hide()
        self.set_expanded(expanded)

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, emit: bool = False) -> None:
        self._expanded = expanded
        label_text = strings.BTN_COLLAPSE if expanded else strings.BTN_EXPAND
        self.btn_toggle.set_icon_name("chevron-down" if expanded else "chevron-right")
        self.btn_toggle.setToolTip(label_text)
        self.btn_toggle.setAccessibleName(label_text)
        if emit:
            self.expanded_changed.emit(self.group_id, expanded)

    def update_group(self, group: JobGroup, progress: GroupProgress) -> None:
        self.title.setText(group.title)
        self.count.setText(strings.GROUP_PROGRESS.format(done=progress.done, total=progress.total))
        self.count.setAccessibleName(self.count.text())
        self.progress.setValue(round(progress.fraction * 1000))
        self.failed.setText(
            plural(progress.failed, strings.GROUP_FAILED_ONE, strings.GROUP_FAILED_MANY)
        )
        self.failed.setVisible(progress.failed > 0)
        self.btn_retry_failed.setVisible(progress.failed > 0)
        self.btn_cancel_all.setVisible(progress.active > 0)
