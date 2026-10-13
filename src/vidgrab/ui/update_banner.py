"""Update banner under the header and the "Τι νέο" (release notes) dialog.

The banner is a neutral surface with an accent icon, never a popup. Its states:
available ("Διαθέσιμη η VidGrab 0.4.1": Λήψη, Τι νέο, Παράλειψη, X), downloading
(progress + Ακύρωση), done ("Η νέα έκδοση κατέβηκε": Άνοιγμα φακέλου + instructions)
and failed (error row + Επανάληψη). The logic lives in ``core/updates.py``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__, strings
from vidgrab.core.errors import UserError
from vidgrab.core.updates import UpdateInfo
from vidgrab.ui.labels import format_bytes
from vidgrab.ui.widgets import ErrorRow, IconButton, IconLabel, label, text_button


class BannerState(StrEnum):
    HIDDEN = "hidden"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


class UpdateBanner(QFrame):
    download_requested = Signal()
    notes_requested = Signal()
    skip_requested = Signal()
    dismissed = Signal()
    cancel_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "update-banner")
        self.setAccessibleName(strings.UPDATE_BANNER_NAME)
        self.update_info: UpdateInfo | None = None
        self.downloaded: Path | None = None
        self.state = BannerState.HIDDEN

        self.icon = IconLabel("circle-arrow-down", "accent", 20)
        self.title = label(role="banner-title")
        self.hint = label(tone="muted")
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setProperty("role", "slim")
        self.error = ErrorRow()

        self.btn_download = text_button(
            strings.BTN_UPDATE_DOWNLOAD, "accent", "download", "on_accent"
        )
        self.btn_notes = text_button(strings.BTN_UPDATE_NOTES, "inline")
        self.btn_skip = text_button(strings.BTN_UPDATE_SKIP, "link", None, "link")
        self.btn_cancel = text_button(strings.BTN_CANCEL, "inline")
        self.btn_retry = text_button(strings.BTN_RETRY, "inline", "rotate-ccw")
        self.btn_open_folder = text_button(
            strings.BTN_OPEN_FOLDER, "accent", "folder-open", "on_accent"
        )
        self.btn_close = IconButton("x", strings.BTN_UPDATE_DISMISS, "muted")

        self.btn_download.clicked.connect(self.download_requested)
        self.btn_retry.clicked.connect(self.download_requested)
        self.btn_notes.clicked.connect(self.notes_requested)
        self.btn_skip.clicked.connect(self.skip_requested)
        self.btn_cancel.clicked.connect(self.cancel_requested)
        self.btn_open_folder.clicked.connect(self.open_folder_requested)
        self.btn_close.clicked.connect(self._close)

        # One row, so it costs little height on 1366x768: icon, text, buttons, X.
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        text.addWidget(self.title)
        second = QHBoxLayout()  # "39 MB από 93 MB  ━━━━━──────"
        second.setSpacing(10)
        second.addWidget(self.hint)
        second.addWidget(self.progress, 1)
        text.addLayout(second)
        text.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.icon)
        row.addSpacing(4)
        row.addLayout(text, 1)
        for button in (
            self.btn_download,
            self.btn_open_folder,
            self.btn_retry,
            self.btn_notes,
            self.btn_skip,
            self.btn_cancel,
            self.btn_close,
        ):
            row.addWidget(button)

        column = QVBoxLayout(self)
        column.setContentsMargins(14, 0, 0, 0)  # the 44px buttons give the height
        column.setSpacing(6)
        column.addLayout(row)
        column.addWidget(self.error)
        self.error.setContentsMargins(0, 0, 0, 0)
        self._apply_state()

    # --- states ------------------------------------------------------------------------
    def show_available(self, update: UpdateInfo) -> None:
        self.update_info = update
        self.downloaded = None
        self.title.setText(strings.UPDATE_AVAILABLE.format(version=update.version))
        self.hint.setText(strings.UPDATE_AVAILABLE_HINT.format(current=__version__))
        self._set_state(BannerState.AVAILABLE)

    def show_downloading(self) -> None:
        assert self.update_info is not None
        self.title.setText(strings.UPDATE_DOWNLOADING.format(version=self.update_info.version))
        self.hint.setText("")
        self.progress.setRange(0, 0)  # busy until the first progress report
        self._set_state(BannerState.DOWNLOADING)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, round(done * 1000 / total)))
            self.hint.setText(
                strings.UPDATE_PROGRESS.format(done=format_bytes(done), total=format_bytes(total))
            )
        else:
            self.progress.setRange(0, 0)
            self.hint.setText(strings.UPDATE_PROGRESS_UNKNOWN.format(done=format_bytes(done)))
        self.hint.setVisible(True)

    def show_done(self, path: Path) -> None:
        self.downloaded = path
        self.title.setText(strings.UPDATE_DOWNLOADED)
        self.hint.setText(strings.UPDATE_DOWNLOADED_HINT.format(name=path.name))
        self._set_state(BannerState.DONE)

    def show_failed(self, error: UserError) -> None:
        self.title.setText(strings.UPDATE_DOWNLOAD_FAILED)
        self.hint.setText("")
        self.error.setText(error.message)
        self.error.setToolTip(error.detail)
        self._set_state(BannerState.FAILED)

    def back_to_available(self) -> None:
        """After a cancel: offer the update again."""
        if self.update_info is not None:
            self.show_available(self.update_info)

    def hide_banner(self) -> None:
        self._set_state(BannerState.HIDDEN)

    def _close(self) -> None:
        self.hide_banner()
        self.dismissed.emit()

    def _set_state(self, state: BannerState) -> None:
        self.state = state
        self._apply_state()

    def _apply_state(self) -> None:
        s = self.state
        visible = {
            self.btn_download: s is BannerState.AVAILABLE,
            self.btn_notes: s in (BannerState.AVAILABLE, BannerState.FAILED),
            self.btn_skip: s is BannerState.AVAILABLE,
            self.btn_cancel: s is BannerState.DOWNLOADING,
            self.btn_retry: s is BannerState.FAILED,
            self.btn_open_folder: s is BannerState.DONE,
            self.btn_close: s is not BannerState.DOWNLOADING,
            self.progress: s is BannerState.DOWNLOADING,
            self.hint: bool(self.hint.text()),
        }
        if s is not BannerState.FAILED:
            self.error.clear()
        icon = {BannerState.DONE: "circle-check", BannerState.FAILED: "circle-alert"}
        tone = {BannerState.DONE: "success", BannerState.FAILED: "error"}
        self.icon.set_icon(icon.get(s, "circle-arrow-down"), tone.get(s, "accent"))
        # Children first (they have a parent), then the banner itself.
        for widget, show in visible.items():
            widget.setVisible(show)
        self.setVisible(s is not BannerState.HIDDEN)


class NotesBrowser(QTextBrowser):
    """Release notes as Markdown. Never loads anything from the network (no remote
    images); links open in the browser, and only http(s) links."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReleaseNotes")
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._open_link)

    def set_notes(self, markdown: str) -> None:
        """Markdown, with headings and list indents scaled to the app's type scale
        (Qt's defaults are far larger than the rest of the UI)."""
        doc = self.document()
        doc.setIndentWidth(18)
        doc.setDocumentMargin(6)
        self.setMarkdown(markdown)
        base = self.font().pointSizeF()
        block = doc.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level:
                cursor = QTextCursor(block)
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
                )
                char = QTextCharFormat()
                # Markdown headings use a size adjustment (h1 = +3 steps); undo it.
                char.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
                char.setFontPointSize(base * (1.3 if level <= 2 else 1.1))
                char.setFontWeight(QFont.Weight.DemiBold)
                cursor.mergeCharFormat(char)
                spacing = QTextBlockFormat()
                spacing.setTopMargin(10)
                spacing.setBottomMargin(4)
                cursor.mergeBlockFormat(spacing)
            block = block.next()

    def loadResource(self, kind: int, url: QUrl):
        return None  # images and style sheets referenced by the notes are not fetched

    @staticmethod
    def _open_link(url: QUrl) -> None:
        if url.scheme().lower() in ("http", "https"):
            QDesktopServices.openUrl(url)


class ReleaseNotesDialog(QDialog):
    def __init__(self, update: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.NOTES_TITLE.format(version=update.version))
        self.setMinimumSize(520, 420)
        self.resize(640, 560)
        self._page = update.page_url

        title = label(strings.NOTES_TITLE.format(version=update.version), role="h2")
        self.browser = NotesBrowser()
        notes = update.notes.strip()
        self.browser.set_notes(notes or strings.NOTES_EMPTY)

        self.btn_page = text_button(strings.BTN_NOTES_ON_GITHUB, "link", "external-link", "link")
        self.btn_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._page)))
        self.btn_close = text_button(strings.BTN_CLOSE)
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setDefault(True)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_page)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_close)

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 16)
        column.setSpacing(12)
        column.addWidget(title)
        column.addWidget(self.browser, 1)
        column.addLayout(bottom)
