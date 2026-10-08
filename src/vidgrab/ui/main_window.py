"""Main window: header, URL field, preview card, download queue and footer."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QUrl
from PySide6.QtGui import (
    QActionGroup,
    QCloseEvent,
    QCursor,
    QDesktopServices,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vidgrab import __version__, strings
from vidgrab.core import archive
from vidgrab.core.binaries import Binaries
from vidgrab.core.errors import ErrorKind, UserError
from vidgrab.core.filenames import sanitize_filename
from vidgrab.core.jobqueue import DownloadJob, JobGroup
from vidgrab.core.models import (
    DownloadRequest,
    JobStatus,
    Listing,
    Quality,
    VideoInfo,
    format_duration,
)
from vidgrab.core.options import YdlFactory, default_ydl_factory
from vidgrab.core.settings import Settings, save_settings
from vidgrab.core.trash import move_to_trash
from vidgrab.ui.controller import DownloadController
from vidgrab.ui.dialogs import SettingsDialog
from vidgrab.ui.format_options import FormatOptions, option_label
from vidgrab.ui.labels import preview_meta_text, queue_counter_text
from vidgrab.ui.logo import LogoWidget
from vidgrab.ui.prefs import UiPrefs, load_prefs, prefs_path_for, save_prefs
from vidgrab.ui.queue_widget import GroupHeader, JobWidget
from vidgrab.ui.selection import SelectedItem, SelectionView
from vidgrab.ui.theme import CONTENT_MAX_WIDTH, URL_FIELD_HEIGHT, ThemeMode, theme_manager
from vidgrab.ui.thumbnails import ThumbnailLoader
from vidgrab.ui.widgets import (
    Banner,
    ElidedLabel,
    ErrorRow,
    IconButton,
    IconLabel,
    PageScroll,
    SegmentedControl,
    Thumbnail,
    card,
    chip,
    label,
    set_prop,
    text_button,
)
from vidgrab.ui.window_geometry import (
    SavedGeometry,
    initial_geometry,
    minimum_size,
    screen_showing,
)
from vidgrab.ui.workers import MetadataWorker, VersionsWorker

log = logging.getLogger(__name__)

PREVIEW_THUMB = (240, 135)  # 16:9
GROUP_COLLAPSE_OVER = 5  # list groups with more videos start collapsed in the queue
GROUP_INDENT = 28  # px: a list's jobs sit indented under its header card
SCOPE_VIDEO, SCOPE_LIST = "video", "list"
QUEUE_MIN_HEIGHT = 110  # about one card; small screens need the height elsewhere

# Fetch errors about the link itself; shown under the URL field, which turns red.
URL_ERROR_KINDS = frozenset(
    {ErrorKind.INVALID_URL, ErrorKind.UNSUPPORTED_URL, ErrorKind.EMPTY_LISTING}
)

THEME_LABELS = {
    ThemeMode.AUTO: strings.THEME_AUTO,
    ThemeMode.LIGHT: strings.THEME_LIGHT,
    ThemeMode.DARK: strings.THEME_DARK,
}
THEME_ICONS = {ThemeMode.AUTO: "sun-moon", ThemeMode.LIGHT: "sun", ThemeMode.DARK: "moon"}


def clipboard_url(text: str | None) -> str | None:
    """The clipboard text if it is a single valid http(s) URL, else None."""
    text = (text or "").strip()
    if not text or any(c.isspace() for c in text) or len(text) > 2048:
        return None
    url = QUrl(text, QUrl.ParsingMode.StrictMode)
    if url.isValid() and url.scheme().lower() in ("http", "https") and "." in url.host():
        return text
    return None


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        binaries: Binaries,
        settings_path: Path | None = None,
        log_file: Path | None = None,
        ydl_factory: YdlFactory = default_ydl_factory,
        load_thumbnails: bool = True,
        load_versions: bool | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.binaries = binaries
        self._settings_path = settings_path
        self._prefs_path = prefs_path_for(settings_path) if settings_path else None
        self.prefs = load_prefs(self._prefs_path) if self._prefs_path else UiPrefs()
        self._log_file = log_file
        self._ydl_factory = ydl_factory
        self._thumbs = ThumbnailLoader(self) if load_thumbnails else None
        self._metadata_worker: MetadataWorker | None = None  # the fetch whose result we want
        self._metadata_workers: set[MetadataWorker] = set()  # all still-running fetches
        self._versions_worker: VersionsWorker | None = None
        self._current_info: VideoInfo | None = None
        self._job_items: dict[int, tuple[QListWidgetItem, JobWidget]] = {}
        self._job_hosts: dict[int, QWidget] = {}  # what the list item shows (indent wrapper)
        self._group_items: dict[int, tuple[QListWidgetItem, GroupHeader]] = {}
        self._group_children: dict[int, list[int]] = {}
        self._next_group_expanded = True
        self._selecting = False  # the list selection screen is shown

        self.theme = theme_manager()
        self.theme.apply(self.prefs.theme)

        self.controller = DownloadController(binaries, settings.max_concurrent, ydl_factory, self)
        self.controller.job_added.connect(self._on_job_added)
        self.controller.job_changed.connect(self._on_job_changed)
        self.controller.job_removed.connect(self._on_job_removed)
        self.controller.group_added.connect(self._on_group_added)
        self.controller.group_removed.connect(self._on_group_removed)

        self.setWindowTitle(strings.WINDOW_TITLE)
        self._start_maximized = False
        self.place_on_screen()
        self._build_ui()
        self._show_binary_warnings()
        self._update_queue_view()
        if load_thumbnails if load_versions is None else load_versions:
            self._load_versions()

    # --- layout ------------------------------------------------------------------------
    def _build_ui(self) -> None:
        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX_WIDTH)
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 18, 24, 14)
        column.setSpacing(12)
        column.addLayout(self._build_header())

        self.warning_banner = Banner()
        self.warning_banner.hide()
        column.addWidget(self.warning_banner)

        column.addLayout(self._build_url_row())
        column.addWidget(self._build_preview_card())
        self.selection_view = SelectionView(self.settings, self._thumbs)
        self.selection_view.hide()
        self.selection_view.back_requested.connect(self.close_selection)
        self.selection_view.download_requested.connect(self.enqueue_selection)
        self.selection_view.format_changed.connect(self._on_selection_format_changed)
        self.selection_view.list_options_changed.connect(self._on_list_options_changed)
        column.addWidget(self.selection_view, 0)
        column.addLayout(self._build_queue_header())
        column.addWidget(self._build_queue(), 1)
        column.addLayout(self._build_footer())
        self._column = column

        root = QWidget()
        root.setObjectName("Root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        # The column grows up to CONTENT_MAX_WIDTH; the margins share what is left, so it
        # stays centred. (AlignHCenter would pin it to its size hint instead.)
        outer.addStretch(1)
        outer.addWidget(content, 1000)
        outer.addStretch(1)
        # Last resort for very short screens: the page scrolls instead of being squashed.
        # On 1366x768 and on 1920x1080 at 150 % everything fits and no scroll bar shows.
        self.page_scroll = PageScroll()
        self.page_scroll.setObjectName("PageScroll")
        self.page_scroll.setWidget(root)
        self.setCentralWidget(self.page_scroll)
        self.page = root

    def _build_header(self) -> QHBoxLayout:
        brand = label("VidGrab", role="brand")
        version = chip(strings.VERSION_CHIP.format(version=__version__))
        version.setAccessibleName(strings.VERSION_CHIP.format(version=__version__))

        self.btn_theme = IconButton(THEME_ICONS[self.theme.mode], strings.BTN_THEME)
        self.btn_theme.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_theme)
        group = QActionGroup(menu)
        self._theme_actions = {}
        for mode in ThemeMode:
            action = menu.addAction(THEME_LABELS[mode])
            action.setCheckable(True)
            action.setChecked(mode is self.theme.mode)
            action.triggered.connect(lambda _=False, m=mode: self.set_theme(m))
            group.addAction(action)
            self._theme_actions[mode] = action
        self.btn_theme.setMenu(menu)

        self.btn_settings = IconButton("settings", strings.BTN_SETTINGS)
        self.btn_settings.clicked.connect(self.open_settings)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(LogoWidget(30))
        row.addWidget(brand)
        row.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self.btn_theme)
        row.addWidget(self.btn_settings)
        return row

    def _build_url_row(self) -> QVBoxLayout:
        self.url_field = QFrame()
        self.url_field.setObjectName("UrlField")
        self.url_field.setFixedHeight(URL_FIELD_HEIGHT)

        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("UrlEdit")
        self.url_edit.setPlaceholderText(strings.URL_PLACEHOLDER)
        self.url_edit.setAccessibleName(strings.URL_FIELD_NAME)
        self.url_edit.returnPressed.connect(self.fetch_metadata)
        self.url_edit.textChanged.connect(lambda *_: self._sync_clipboard_hint())
        self.url_edit.textEdited.connect(lambda *_: self._set_url_error(None))
        self.url_edit.installEventFilter(self)

        # Analyse without downloading (Enter does the same); disabled while fetching.
        self.btn_fetch = IconButton("search", strings.BTN_FETCH_TOOLTIP, "muted")
        self.btn_fetch.clicked.connect(self.fetch_metadata)
        self.btn_paste = text_button(strings.BTN_PASTE, "inline", "clipboard-paste", "text")
        self.btn_paste.clicked.connect(self._paste_and_fetch)

        field = QHBoxLayout(self.url_field)
        field.setContentsMargins(14, 4, 4, 4)  # 4 + 44px buttons + 4 = 52
        field.setSpacing(8)
        field.addWidget(IconLabel("link", "muted", 18))
        field.addWidget(self.url_edit, 1)
        field.addWidget(self.btn_fetch)
        field.addWidget(self.btn_paste)

        self.btn_download = text_button(strings.BTN_DOWNLOAD, "primary", "download", "on_accent")
        self.btn_download.setFixedHeight(URL_FIELD_HEIGHT)
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self.enqueue_current)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.url_field, 1)
        row.addWidget(self.btn_download)

        # Shown on focus when the clipboard holds a link and the field is empty.
        self.clipboard_hint = text_button("", "link", "clipboard-paste", "link")
        self.clipboard_hint.setToolTip(strings.CLIPBOARD_SUGGESTION_TOOLTIP)
        self.clipboard_hint.clicked.connect(self._use_clipboard_suggestion)
        self.clipboard_hint.hide()
        self._clipboard_suggestion: str | None = None

        # Red border + message only for a link that is invalid or not supported.
        self.url_error = ErrorRow()

        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(row)
        box.addWidget(self.url_error)
        box.addWidget(self.clipboard_hint, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def _build_preview_card(self) -> QFrame:
        self.preview_card = card()
        self.preview_thumb = Thumbnail(*PREVIEW_THUMB)

        self.preview_title = label(strings.LABEL_NO_PREVIEW, role="title")
        self.preview_title.setWordWrap(True)
        self.preview_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_meta = label(tone="muted")
        self.preview_error = ErrorRow()

        # A video inside a list (watch?v=...&list=...): this video, or choose from the list.
        self.scope_combo = SegmentedControl(strings.SCOPE_SEGMENT_NAME)
        self.scope_combo.addItem(strings.SCOPE_THIS_VIDEO, SCOPE_VIDEO)
        self.scope_combo.addItem(strings.SCOPE_WHOLE_LIST, SCOPE_LIST)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.scope_combo.hide()

        self.preview_options = FormatOptions(self.settings)
        self.preview_options.changed.connect(self._on_preview_format_changed)
        # The names the rest of the window (and the tests) use.
        self.quality_combo = self.preview_options.quality_combo
        self.format_combo = self.preview_options.format_combo
        self.bitrate_combo = self.preview_options.bitrate_combo
        self.bitrate_label = self.preview_options.bitrate_label

        self.dest_label = ElidedLabel()
        self.dest_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._update_dest_label()
        self.btn_choose_folder = text_button(strings.BTN_BROWSE, None, "folder")
        self.btn_choose_folder.setToolTip(strings.BTN_CHANGE_FOLDER)
        self.btn_choose_folder.setAccessibleName(strings.BTN_CHANGE_FOLDER)
        self.btn_choose_folder.clicked.connect(self._choose_folder)
        self.btn_open_dest = IconButton("folder-open", strings.BTN_OPEN_FOLDER)
        self.btn_open_dest.clicked.connect(lambda: self._open_path(Path(self.settings.output_dir)))
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        dest_row.addWidget(option_label(strings.LABEL_DESTINATION))
        dest_row.addWidget(self.dest_label, 1)
        dest_row.addWidget(self.btn_choose_folder)
        dest_row.addWidget(self.btn_open_dest)

        details = QVBoxLayout()
        details.setSpacing(8)
        details.addWidget(self.preview_title)
        details.addWidget(self.preview_meta)
        details.addWidget(self.preview_error)
        details.addWidget(self.scope_combo, 0, Qt.AlignmentFlag.AlignLeft)
        details.addSpacing(4)
        details.addWidget(self.preview_options)
        details.addStretch(1)
        details.addLayout(dest_row)

        layout = QHBoxLayout(self.preview_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)
        layout.addWidget(self.preview_thumb, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(details, 1)
        return self.preview_card

    def _build_queue_header(self) -> QHBoxLayout:
        title = label(strings.LABEL_QUEUE.rstrip(":"), role="h2")
        self.queue_counter = label(tone="muted")
        self.btn_clear = text_button(strings.BTN_CLEAR_FINISHED, None, "list-x", "muted")
        self.btn_clear.clicked.connect(self.controller.clear_finished)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(title)
        row.addWidget(self.queue_counter)
        row.addStretch(1)
        row.addWidget(self.btn_clear)
        return row

    def _build_queue(self) -> QStackedWidget:
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("Queue")
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.queue_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the cards' buttons take focus
        self.queue_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.queue_list.setSpacing(4)
        self.queue_list.viewport().installEventFilter(self)

        self.empty_state = QFrame()
        self.empty_state.setProperty("role", "empty")
        empty = QVBoxLayout(self.empty_state)
        empty.setSpacing(6)
        empty.addStretch(1)
        empty.addWidget(IconLabel("inbox", "muted", 36), 0, Qt.AlignmentFlag.AlignHCenter)
        empty_title = label(strings.EMPTY_QUEUE_TITLE, role="h2")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(empty_title)
        empty_hint = label(strings.EMPTY_QUEUE_HINT, tone="muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty_hint.setWordWrap(True)
        empty.addWidget(empty_hint)
        empty.addStretch(2)

        self.queue_stack = QStackedWidget()
        self.queue_stack.addWidget(self.empty_state)
        self.queue_stack.addWidget(self.queue_list)
        self.queue_stack.setMinimumHeight(QUEUE_MIN_HEIGHT)
        return self.queue_stack

    def _build_footer(self) -> QHBoxLayout:
        self.versions_label = label(tone="muted")
        self.versions_label.setFont(self._small_font())
        self.btn_logs = text_button(strings.BTN_OPEN_LOGS, "link", "file-text", "link")
        self.btn_logs.clicked.connect(self._open_logs)
        self.btn_logs.setEnabled(self._log_file is not None)
        row = QHBoxLayout()
        row.addWidget(self.versions_label)
        row.addStretch(1)
        row.addWidget(self.btn_logs)
        return row

    def _small_font(self):
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        return font

    def _show_binary_warnings(self) -> None:
        warnings = self.binaries.warnings()
        if warnings:
            self.warning_banner.setText("\n".join(warnings))
            self.warning_banner.show()

    # --- window size and position ------------------------------------------------------
    def place_on_screen(
        self, screens: list[QRect] | None = None, opening: QRect | None = None
    ) -> None:
        """Saved size/position if still on a screen, else min(900, screen - 40) centred.

        ``screens`` (available areas of all screens) and ``opening`` (the screen to open
        on) default to the real ones; tests pass e.g. a 1366x768 laptop.
        """
        if screens is None:
            screens = [screen.availableGeometry() for screen in QGuiApplication.screens()]
        if opening is None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            opening = screen.availableGeometry()
        rect, self._start_maximized = initial_geometry(self.prefs.window, screens, opening)
        self.setMinimumSize(*minimum_size(screen_showing(rect, screens) or opening))
        self.setGeometry(rect)

    def show_initial(self) -> None:
        """Show as it was left: maximised or not."""
        if self._start_maximized:
            self.showMaximized()
        else:
            self.show()

    def _remember_geometry(self) -> None:
        maximized = self.isMaximized()
        rect = self.normalGeometry() if maximized else self.geometry()
        if rect.isEmpty():
            return
        self.prefs = replace(self.prefs, window=SavedGeometry.from_rect(rect, maximized))
        if self._prefs_path:
            try:
                save_prefs(self.prefs, self._prefs_path)
            except OSError:
                log.exception("Could not save UI preferences")

    # --- theme -------------------------------------------------------------------------
    def set_theme(self, mode: ThemeMode | str) -> None:
        mode = ThemeMode(mode)
        self.theme.apply(mode)
        self.btn_theme.set_icon_name(THEME_ICONS[mode])
        self._theme_actions[mode].setChecked(True)
        if self.prefs.theme is not mode:
            self.prefs = replace(self.prefs, theme=mode)
            if self._prefs_path:
                try:
                    save_prefs(self.prefs, self._prefs_path)
                except OSError:
                    log.exception("Could not save UI preferences")

    # --- versions footer -----------------------------------------------------------------
    def _load_versions(self) -> None:
        worker = VersionsWorker(self.binaries, self)
        worker.ready.connect(self.set_versions)
        worker.finished.connect(self._on_versions_finished)
        self._versions_worker = worker
        worker.start()

    def _on_versions_finished(self) -> None:
        worker, self._versions_worker = self._versions_worker, None
        if worker is not None:
            worker.deleteLater()

    def set_versions(self, versions: dict[str, str | None]) -> None:
        def show(name: str) -> str:
            return versions.get(name) or "—"

        self.versions_label.setText(
            strings.FOOTER_VERSIONS.format(
                ytdlp=show("yt-dlp"), ffmpeg=show("ffmpeg"), deno=show("deno")
            )
        )

    # --- event filter: URL field focus, queue width -------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        queue = getattr(self, "queue_list", None)  # filters can fire while building the UI
        if queue is not None and obj is queue.viewport() and event.type() == QEvent.Type.Resize:
            self._refit_items()
        elif obj is self.url_edit:
            if event.type() == QEvent.Type.FocusIn:
                set_prop(self.url_field, "focused", True)
                self._offer_clipboard_url()
            elif event.type() == QEvent.Type.FocusOut:
                set_prop(self.url_field, "focused", False)
        return super().eventFilter(obj, event)

    # --- clipboard suggestion ------------------------------------------------------------
    def _offer_clipboard_url(self) -> None:
        url = clipboard_url(QGuiApplication.clipboard().text())
        self._clipboard_suggestion = url
        if url:
            shown = url if len(url) <= 70 else url[:67] + "…"
            self.clipboard_hint.setText(strings.CLIPBOARD_SUGGESTION.format(url=shown))
        self._sync_clipboard_hint()

    def _sync_clipboard_hint(self) -> None:
        self.clipboard_hint.setVisible(
            bool(self._clipboard_suggestion) and not self.url_edit.text().strip()
        )

    def _use_clipboard_suggestion(self) -> None:
        if self._clipboard_suggestion:
            self.url_edit.setText(self._clipboard_suggestion)
            self.fetch_metadata()

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
        self.close_selection()
        self._current_info = None
        self.btn_download.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.preview_error.clear()
        self._set_url_error(None)
        self.preview_meta.clear()
        self.preview_thumb.clear()
        self._show_scope(None)
        self.preview_title.setText(strings.LABEL_FETCHING)
        self._start_metadata_worker(url)

    def _start_metadata_worker(self, url: str, listing: bool = False) -> None:
        worker = MetadataWorker(
            url, self.binaries, self.settings.cookies, self._ydl_factory, self, listing=listing
        )
        worker.succeeded.connect(lambda info, w=worker: self._on_metadata(w, info))
        worker.failed.connect(lambda err, w=worker: self._on_metadata_failed(w, err))
        worker.finished.connect(lambda w=worker: self._on_metadata_thread_finished(w))
        self._metadata_worker = worker
        self._metadata_workers.add(worker)
        worker.start()

    def _on_metadata(self, worker: MetadataWorker, info: VideoInfo | Listing) -> None:
        if worker is not self._metadata_worker:
            return  # superseded by a newer fetch
        self.btn_fetch.setEnabled(True)
        if isinstance(info, Listing):
            self.scope_combo.setEnabled(True)
            self.show_listing(info)
            return
        self._current_info = info
        self.preview_title.setText(info.title)
        self.preview_meta.setText(preview_meta_text(info))
        self.preview_thumb.set_duration(format_duration(info.duration))
        self._show_scope(info.list_url)
        self.btn_download.setEnabled(True)
        if self._thumbs:
            self._thumbs.load(info.thumbnail_url, self.preview_thumb.setPixmap)

    # --- lists -------------------------------------------------------------------------
    def _show_scope(self, list_url: str | None) -> None:
        """ "Μόνο αυτό το βίντεο / Όλη η λίστα" for a video inside a list."""
        self.scope_combo.blockSignals(True)
        self.scope_combo.setCurrentIndex(0)
        self.scope_combo.blockSignals(False)
        self.scope_combo.setEnabled(True)
        self.scope_combo.setVisible(bool(list_url))

    def _on_scope_changed(self) -> None:
        info = self._current_info
        if self.scope_combo.currentData() != SCOPE_LIST or info is None or not info.list_url:
            return
        self.scope_combo.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.preview_error.clear()
        self.preview_meta.setText(strings.LABEL_LOADING_LIST)
        self._start_metadata_worker(info.list_url, listing=True)

    def show_listing(self, listing: Listing) -> None:
        """Replace the preview card with the selection grid of ``listing``."""
        self.selection_view.apply_settings(self.settings)
        self.selection_view.set_listing(listing, archive.load_keys())
        self.preview_card.hide()
        self.selection_view.show()
        self.btn_download.setEnabled(False)  # the list has its own "Λήψη N videos"
        # The list gets the height; the queue shows only its header meanwhile.
        self._column.setStretchFactor(self.selection_view, 1)
        self._selecting = True
        self._update_queue_view()
        first = next((c for c in self.selection_view.cards if c.entry.available), None)
        if first is not None:
            first.setFocus(Qt.FocusReason.OtherFocusReason)

    def close_selection(self) -> None:
        """ "Πίσω": back to the preview card (the video, for a video inside a list)."""
        if not self.selection_view.isVisible() and self.preview_card.isVisible():
            return
        self.selection_view.hide()
        self._column.setStretchFactor(self.selection_view, 0)
        self._selecting = False
        self._update_queue_view()
        self.preview_card.show()
        info = self._current_info
        if info is not None:
            self.preview_meta.setText(preview_meta_text(info))
            self._show_scope(info.list_url)
            self.btn_download.setEnabled(True)
        else:
            self.preview_title.setText(strings.LABEL_NO_PREVIEW)
            self.preview_meta.clear()
            self.btn_download.setEnabled(False)

    def enqueue_selection(self, items: list[SelectedItem]) -> list[DownloadJob]:
        """Queue the chosen videos of the list on screen as one group."""
        listing = self.selection_view.listing
        if listing is None or not items:
            return []
        self.settings = self.selection_view.list_settings(self.settings)
        self._save_settings()
        s = self.settings
        output_dir = Path(s.output_dir)
        if s.list_subfolder:
            output_dir = output_dir / sanitize_filename(listing.title, fallback=listing.id)
        requests = [
            (
                DownloadRequest(
                    url=item.entry.url,
                    quality=s.quality,
                    output_dir=output_dir,
                    cookies=s.cookies,
                    title=item.filename,
                    container=s.video_container,
                    audio_format=s.audio_format,
                    mp3_bitrate=s.mp3_bitrate,
                    playlist_item=item.entry.playlist_item,
                    filename=item.filename,
                ),
                item.entry.thumbnail_url,
            )
            for item in items
        ]
        self._next_group_expanded = len(requests) <= GROUP_COLLAPSE_OVER
        _, jobs = self.controller.enqueue_group(
            listing.title,
            listing.extractor,
            requests,
            skipped=self.selection_view.skipped_count(),
        )
        self.close_selection()
        return jobs

    def _on_selection_format_changed(self) -> None:
        self.settings = self.selection_view.options.apply_to(self.settings)
        self.preview_options.set_from(self.settings)
        self._save_settings()

    def _on_list_options_changed(self) -> None:
        self.settings = self.selection_view.list_settings(self.settings)
        self._save_settings()

    def _on_metadata_thread_finished(self, worker: MetadataWorker) -> None:
        self._metadata_workers.discard(worker)
        if worker is self._metadata_worker:
            self._metadata_worker = None
        worker.deleteLater()

    def _on_metadata_failed(self, worker: MetadataWorker, error: UserError) -> None:
        if worker is not self._metadata_worker:
            return
        self.btn_fetch.setEnabled(True)
        if worker.listing and self._current_info is not None:
            # "Όλη η λίστα" failed: keep the video's preview and say why.
            self._show_scope(self._current_info.list_url)
            self.preview_meta.setText(preview_meta_text(self._current_info))
            self.btn_download.setEnabled(True)
            self.preview_error.setText(error.message)
            self.preview_error.setToolTip(error.detail)
            return
        self.preview_title.setText(strings.LABEL_NO_PREVIEW)
        if error.kind in URL_ERROR_KINDS:
            self._set_url_error(error)  # a problem with the link itself: show it at the field
        else:
            self.preview_error.setText(error.message)
            self.preview_error.setToolTip(error.detail)

    def _set_url_error(self, error: UserError | None) -> None:
        set_prop(self.url_field, "invalid", error is not None)
        if error is None:
            self.url_error.clear()
            self.url_edit.setAccessibleDescription("")
        else:
            self.url_error.setText(error.message)
            self.url_error.setToolTip(error.detail)
            self.url_edit.setAccessibleDescription(error.message)

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
            playlist_item=info.playlist_item,
        )
        return self.controller.enqueue(request, info.thumbnail_url)

    def _on_job_added(self, job: DownloadJob) -> None:
        widget = JobWidget(job)
        widget.cancel_requested.connect(self.controller.cancel)
        widget.retry_requested.connect(self.controller.retry)
        widget.remove_requested.connect(self.controller.remove)
        widget.trash_file_requested.connect(self.trash_job_file)
        widget.upgrade_requested.connect(self.controller.retry_full_quality)
        widget.open_requested.connect(self._open_job)
        widget.open_file_requested.connect(self._open_job_file)
        widget.details_requested.connect(self._show_job_details)
        host: QWidget = widget
        row = self.queue_list.count()
        group = self._group_items.get(job.group_id) if job.group_id is not None else None
        if group is not None:
            # Indented under the list's header card, after the list's other jobs.
            host = QWidget()
            indent = QHBoxLayout(host)
            indent.setContentsMargins(GROUP_INDENT, 0, 0, 0)
            indent.addWidget(widget)
            children = self._group_children.setdefault(job.group_id, [])
            last = self._job_items[children[-1]][0] if children else group[0]
            row = self.queue_list.row(last) + 1
            children.append(job.id)
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.queue_list.insertItem(row, item)
        self.queue_list.setItemWidget(item, host)
        self._job_items[job.id] = (item, widget)
        self._job_hosts[job.id] = host
        self._fit_item(item, host)
        if group is not None:
            item.setHidden(not group[1].expanded)
            self._update_group(job.group_id)
        if self._thumbs:
            self._thumbs.load(job.thumbnail_url, widget.set_thumbnail)
        self._update_queue_view()

    def _on_job_changed(self, job: DownloadJob) -> None:
        entry = self._job_items.get(job.id)
        if entry:
            item, widget = entry
            widget.update_job(job)
            self._fit_item(item, self._job_hosts[job.id])  # buttons and messages come and go
        if job.group_id is not None:
            self._update_group(job.group_id)
        self._update_queue_view()

    def _on_job_removed(self, job_id: int) -> None:
        entry = self._job_items.pop(job_id, None)
        host = self._job_hosts.pop(job_id, None)
        if entry:
            row = self.queue_list.row(entry[0])
            self.queue_list.takeItem(row)
            (host or entry[1]).deleteLater()
        for group_id, children in self._group_children.items():
            if job_id in children:
                children.remove(job_id)
                if group_id in self._group_items:
                    self._update_group(group_id)
                break
        self._update_queue_view()

    # --- list groups in the queue ------------------------------------------------------
    def _on_group_added(self, group: JobGroup) -> None:
        header = GroupHeader(group, expanded=self._next_group_expanded)
        self._next_group_expanded = True
        header.cancel_all_requested.connect(self.controller.cancel_group)
        header.retry_failed_requested.connect(self.controller.retry_failed)
        header.expanded_changed.connect(self._on_group_expanded)
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.queue_list.addItem(item)
        self.queue_list.setItemWidget(item, header)
        self._group_items[group.id] = (item, header)
        self._group_children[group.id] = []
        self._fit_item(item, header)
        self._update_group(group.id)

    def _on_group_removed(self, group_id: int) -> None:
        entry = self._group_items.pop(group_id, None)
        self._group_children.pop(group_id, None)
        if entry:
            self.queue_list.takeItem(self.queue_list.row(entry[0]))
            entry[1].deleteLater()
        self._update_queue_view()

    def _on_group_expanded(self, group_id: int, expanded: bool) -> None:
        for job_id in self._group_children.get(group_id, []):
            self._job_items[job_id][0].setHidden(not expanded)

    def _update_group(self, group_id: int) -> None:
        entry = self._group_items.get(group_id)
        if entry is None:
            return
        item, header = entry
        queue = self.controller.queue
        header.update_group(queue.group(group_id), queue.group_progress(group_id))
        self._fit_item(item, header)

    def group_header(self, group_id: int) -> GroupHeader:
        return self._group_items[group_id][1]

    def _fit_item(self, item: QListWidgetItem, widget: QWidget) -> None:
        width = self.queue_list.viewport().width() - 2 * self.queue_list.spacing()
        hint = widget.sizeHint()
        layout = widget.layout()
        if width > 0 and layout is not None and layout.hasHeightForWidth():
            hint.setHeight(
                max(widget.minimumSizeHint().height(), layout.totalHeightForWidth(width))
            )
        if item.sizeHint() != hint:
            item.setSizeHint(hint)

    def _refit_items(self) -> None:
        for job_id, (item, _) in self._job_items.items():
            self._fit_item(item, self._job_hosts[job_id])
        for item, header in self._group_items.values():
            self._fit_item(item, header)

    def _update_queue_view(self) -> None:
        jobs = self.controller.queue.jobs
        self.queue_counter.setText(queue_counter_text(jobs))
        self.queue_stack.setCurrentWidget(self.queue_list if jobs else self.empty_state)
        # While choosing from a list the queue shows only its header and counter: the
        # list gets the height (a 1366x768 laptop or 150 % scaling has little to spare).
        self.queue_stack.setVisible(not self._selecting)
        self.btn_clear.setEnabled(any(j.status.is_finished for j in jobs))

    def _open_job(self, job_id: int) -> None:
        job = self.controller.queue.get(job_id)
        target = job.output_path or job.request.output_dir
        self._open_path(target, select=job.output_path is not None)

    def _open_job_file(self, job_id: int) -> None:
        job = self.controller.queue.get(job_id)
        if job.output_path is None:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(job.output_path))):
            QMessageBox.warning(
                self,
                strings.DIALOG_ERROR_TITLE,
                strings.OPEN_FILE_FAILED.format(path=job.output_path),
            )

    def trash_job_file(self, job_id: int) -> None:
        """After confirmation, move a finished file to the Recycle Bin (never a permanent
        delete) and drop its card."""
        job = self.controller.queue.get(job_id)
        path = job.output_path
        if path is None or job.status is not JobStatus.COMPLETED:
            return
        if not path.exists():
            self.controller.remove(job_id)  # already gone (moved or deleted elsewhere)
            return
        if not self._confirm_trash(path):
            return
        try:
            move_to_trash(path)
        except OSError:
            log.exception("Could not move %s to the Recycle Bin", path)
            QMessageBox.warning(
                self, strings.DIALOG_ERROR_TITLE, strings.TRASH_FAILED.format(path=path)
            )
            return
        self.controller.remove(job_id)

    def _confirm_trash(self, path: Path) -> bool:
        answer = QMessageBox.question(
            self,
            strings.CONFIRM_TRASH_TITLE,
            strings.CONFIRM_TRASH_TEXT.format(name=path.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

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
        return self.preview_options.quality()

    def _on_preview_format_changed(self) -> None:
        self.settings = self.preview_options.apply_to(self.settings)
        self.selection_view.options.set_from(self.settings)
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
        dialog = SettingsDialog(self.settings, self, theme=self.theme.mode)
        if dialog.exec():
            self.apply_settings(dialog.result_settings())
            self.set_theme(dialog.result_theme())

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
        self._remember_geometry()
        self.controller.shutdown()
        # yt-dlp metadata calls cannot be interrupted; give them a moment, then let the
        # process exit (QThread objects are parented to this window).
        for worker in list(self._metadata_workers):
            worker.wait(2000)
        if self._versions_worker is not None:
            self._versions_worker.wait(2000)
        event.accept()
