"""List selection screen: choose which videos of a playlist or multi-video post to download.

It replaces the preview card (no new window). The selection lives in a model
(``SelectionView._selected``, ``._names``), not in the cards, so "Επιλογή όλων" also covers
cards that have not been created yet: lists over ``BATCH_THRESHOLD`` items are built in
batches of ``BATCH_SIZE`` as the user scrolls, and thumbnails load only for cards on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vidgrab import strings
from vidgrab.core.filenames import numbered_name, sanitize_filename
from vidgrab.core.models import EntryState, Listing, ListingEntry, format_duration
from vidgrab.core.settings import Settings
from vidgrab.ui.format_options import FormatOptions
from vidgrab.ui.labels import platform_name
from vidgrab.ui.thumbnails import ThumbnailLoader
from vidgrab.ui.widgets import (
    Banner,
    CheckBox,
    IconButton,
    Thumbnail,
    TwoLineLabel,
    chip,
    label,
    set_prop,
    text_button,
)

BATCH_THRESHOLD = 100  # lists longer than this are built in batches
BATCH_SIZE = 60
WARN_AT = 25  # selected downloads from which the amber "may get blocked" banner shows
WIDE_GRID_PX = 760  # below this the grid has 2 columns, otherwise 3
GRID_SPACING = 12

_STATE_CHIPS = {
    EntryState.PRIVATE: strings.CHIP_PRIVATE,
    EntryState.UNAVAILABLE: strings.CHIP_UNAVAILABLE,
}


def video_count_text(n: int) -> str:
    return strings.LIST_VIDEO_COUNT_ONE if n == 1 else strings.LIST_VIDEO_COUNT_MANY.format(n=n)


def download_button_text(n: int) -> str:
    return strings.BTN_DOWNLOAD_N_ONE if n == 1 else strings.BTN_DOWNLOAD_N_MANY.format(n=n)


@dataclass(frozen=True)
class SelectedItem:
    entry: ListingEntry
    filename: str  # sanitised, numbered if asked: "03 - Title"


class EntryCard(QFrame):
    """One video of the list: 16:9 thumbnail, check box, two-line title, rename."""

    toggled = Signal(int)  # index into the listing entries
    renamed = Signal(int, str)  # index, new (raw) title
    navigate = Signal(int, int, int)  # index, dx, dy (arrow keys)

    def __init__(
        self,
        index: int,
        entry: ListingEntry,
        *,
        selected: bool,
        downloaded: bool,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self.entry = entry
        self.setProperty("role", "entry")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(strings.ENTRY_CARD_NAME.format(position=entry.position, title=title))
        self._editing = False

        self.thumb = Thumbnail(16, 9)
        self.thumb.set_duration(format_duration(entry.duration))
        self.check = CheckBox(parent=self.thumb)
        self.check.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the card itself takes focus
        self.check.setAccessibleName(title)
        self.check.move(4, 4)
        self.check.resize(self.check.sizeHint())
        self.check.clicked.connect(lambda: self.toggled.emit(self.index))

        self.title = TwoLineLabel(title)
        self.title.setProperty("role", "job-title")
        self.editor = QLineEdit()
        self.editor.setAccessibleName(strings.RENAME_FIELD_NAME)
        self.editor.setToolTip(strings.RENAME_HINT)
        self.editor.installEventFilter(self)
        self.title_stack = QStackedWidget()
        self.title_stack.addWidget(self.title)
        self.title_stack.addWidget(self.editor)
        self.title_stack.setFixedHeight(self.title.height())

        self.btn_rename = IconButton("pencil", f"{strings.BTN_RENAME} (F2)", "muted")
        self.btn_rename.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # F2 on the card
        self.btn_rename.clicked.connect(self.start_rename)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.state_chip = chip(_STATE_CHIPS.get(entry.state, ""))
        self.downloaded_chip = chip(strings.CHIP_ALREADY_DOWNLOADED, tone="success")
        self.chips.addWidget(self.state_chip)
        self.chips.addWidget(self.downloaded_chip)
        self.chips.addStretch(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addWidget(self.title_stack, 1)
        title_row.addWidget(self.btn_rename, 0, Qt.AlignmentFlag.AlignTop)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addWidget(self.thumb)
        root.addLayout(title_row)
        root.addLayout(self.chips)

        # Only now that they have a parent: setVisible(True) on a parentless widget would
        # open it as a separate top-level window.
        self.state_chip.setVisible(entry.state in _STATE_CHIPS)
        self.downloaded_chip.setVisible(downloaded and entry.available)
        if not entry.available:
            self.setEnabled(False)  # dims the thumbnail, no check box, not focusable
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_rename.hide()
        self.set_selected(selected)

    # --- state -------------------------------------------------------------------------
    def set_card_width(self, width: int) -> None:
        self.setFixedWidth(width)
        inner = width - 16
        self.thumb.setFixedSize(inner, round(inner * 9 / 16))
        self.thumb.set_duration(format_duration(self.entry.duration))

    def set_selected(self, selected: bool) -> None:
        self.check.setChecked(selected)
        set_prop(self, "selected", bool(selected))

    def set_title(self, title: str) -> None:
        self.title.setText(title)
        self.check.setAccessibleName(title)
        self.setAccessibleName(
            strings.ENTRY_CARD_NAME.format(position=self.entry.position, title=title)
        )

    # --- rename ------------------------------------------------------------------------
    def start_rename(self) -> None:
        if not self.entry.available:
            return
        self.editor.setText(self.title.text())
        self._editing = True
        self.title_stack.setCurrentWidget(self.editor)
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self.editor.selectAll()

    def _finish_rename(self, save: bool) -> None:
        if not self._editing:
            return
        # Cleared first: hiding the editor moves focus, and that FocusOut must not save.
        self._editing = False
        if save:
            # Shown already as it will be saved: Windows-safe.
            name = sanitize_filename(self.editor.text(), fallback=self.entry.title)
            self.renamed.emit(self.index, name)
        self.title_stack.setCurrentWidget(self.title)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    @property
    def editing(self) -> bool:
        return self._editing

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.editor:
            if event.type() == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Escape:
                event.accept()  # Esc cancels the rename, not the whole screen
                return True
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._finish_rename(save=True)
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self._finish_rename(save=False)
                    return True
            if event.type() == QEvent.Type.FocusOut and self.editing:
                self._finish_rename(save=True)
        return super().eventFilter(obj, event)

    # --- input -------------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self.entry.available and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if not self.editing:
                self.toggled.emit(self.index)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggled.emit(self.index)
        elif key == Qt.Key.Key_F2:
            self.start_rename()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            dx = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(key, 0)
            dy = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(key, 0)
            self.navigate.emit(self.index, dx, dy)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class SelectionView(QFrame):
    """Header, toolbar and grid of a list. Emits the chosen items; never downloads itself."""

    back_requested = Signal()
    download_requested = Signal(object)  # list[SelectedItem]
    format_changed = Signal()  # FormatOptions changed: the window updates the settings
    list_options_changed = Signal()  # one of the three check boxes changed

    def __init__(
        self,
        settings: Settings,
        thumbs: ThumbnailLoader | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setAccessibleName(strings.SELECTION_VIEW_NAME)
        self._thumbs = thumbs
        self.listing: Listing | None = None
        self._downloaded: set[str] = set()
        self._selected: set[int] = set()
        self._names: dict[int, str] = {}
        self._cards: list[EntryCard] = []
        self._columns = 3
        self._requested_thumbs: set[int] = set()

        # --- header ----------------------------------------------------------------------
        self.btn_back = text_button(strings.BTN_BACK, None, "arrow-left")
        self.btn_back.setToolTip(f"{strings.BTN_BACK} (Esc)")
        self.btn_back.clicked.connect(self.back_requested)
        self.list_title = label("", role="title")
        self.list_title.setWordWrap(True)
        self.platform_chip = chip()
        self.count_chip = chip()
        self.duration_chip = chip()
        meta = QHBoxLayout()
        meta.setSpacing(6)
        for c in (self.platform_chip, self.count_chip, self.duration_chip):
            meta.addWidget(c)
        meta.addStretch(1)
        title_col = QVBoxLayout()
        title_col.setSpacing(6)
        title_col.addWidget(self.list_title)
        title_col.addLayout(meta)
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self.btn_back, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(title_col, 1)

        # --- toolbar ---------------------------------------------------------------------
        self.btn_all = text_button(strings.BTN_SELECT_ALL)
        self.btn_all.setToolTip(f"{strings.BTN_SELECT_ALL} (Ctrl+A)")
        self.btn_all.clicked.connect(self.select_all)
        self.btn_none = text_button(strings.BTN_SELECT_NONE)
        self.btn_none.clicked.connect(self.select_none)
        self.selected_label = label(tone="muted")
        self.btn_download = text_button("", "primary", "download", "on_accent")
        self.btn_download.setMinimumHeight(44)
        self.btn_download.clicked.connect(self._emit_download)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.btn_all)
        top.addWidget(self.btn_none)
        top.addSpacing(6)
        top.addWidget(self.selected_label)
        top.addStretch(1)
        top.addWidget(self.btn_download)

        self.options = FormatOptions(settings, compact=True)
        self.options.changed.connect(self.format_changed)

        self.chk_subfolder = CheckBox(strings.OPTION_SUBFOLDER)
        self.chk_numbering = CheckBox(strings.OPTION_NUMBERING)
        self.chk_skip = CheckBox(strings.OPTION_SKIP_DOWNLOADED)
        self.chk_skip.setToolTip(strings.OPTION_SKIP_DOWNLOADED_TOOLTIP)
        for box in (self.chk_subfolder, self.chk_numbering, self.chk_skip):
            box.toggled.connect(lambda *_: self.list_options_changed.emit())
        self.chk_skip.toggled.connect(self._on_skip_toggled)
        checks = QHBoxLayout()
        checks.setSpacing(18)
        checks.addWidget(self.chk_subfolder)
        checks.addWidget(self.chk_numbering)
        checks.addWidget(self.chk_skip)
        checks.addStretch(1)

        self.warning = Banner()
        self.warning.hide()

        # --- grid ------------------------------------------------------------------------
        self.grid_host = QWidget()
        self.grid_host.setObjectName("EntryGrid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(GRID_SPACING)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("EntryScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.grid_host)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(60)
        self._thumb_timer.timeout.connect(self._load_visible_thumbnails)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addLayout(header)
        root.addLayout(top)
        root.addWidget(self.options)
        root.addLayout(checks)
        root.addWidget(self.warning)
        root.addWidget(self.scroll, 1)

        shortcut_all = QShortcut(QKeySequence(QKeySequence.StandardKey.SelectAll), self)
        shortcut_all.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_all.activated.connect(self.select_all)
        shortcut_back = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut_back.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_back.activated.connect(self.back_requested)

        self.apply_settings(settings)

    # --- public API --------------------------------------------------------------------
    def apply_settings(self, settings: Settings) -> None:
        """Show the saved choices (format, list options) without emitting change signals."""
        self.options.set_from(settings)
        for box, value in (
            (self.chk_subfolder, settings.list_subfolder),
            (self.chk_numbering, settings.list_numbering),
            (self.chk_skip, settings.skip_downloaded),
        ):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)

    def list_settings(self, settings: Settings) -> Settings:
        return replace(
            self.options.apply_to(settings),
            list_subfolder=self.chk_subfolder.isChecked(),
            list_numbering=self.chk_numbering.isChecked(),
            skip_downloaded=self.chk_skip.isChecked(),
        )

    def set_listing(self, listing: Listing, downloaded: set[str]) -> None:
        self.listing = listing
        self._downloaded = set(downloaded)
        self._names = {}
        self._requested_thumbs = set()
        self.list_title.setText(listing.title)
        name = platform_name(listing.extractor)
        self.platform_chip.setText(name)
        self.platform_chip.setVisible(bool(name))
        available = len(listing.available_entries)
        self.count_chip.setText(video_count_text(available))
        duration = format_duration(listing.total_duration)
        self.duration_chip.setText(duration or "")
        self.duration_chip.setVisible(bool(duration))
        self._selected = self._default_selection()
        self._rebuild_cards()
        self._update_counts()
        self.scroll.verticalScrollBar().setValue(0)
        self._thumb_timer.start()

    @property
    def entries(self) -> tuple[ListingEntry, ...]:
        return self.listing.entries if self.listing else ()

    @property
    def cards(self) -> list[EntryCard]:
        return list(self._cards)

    @property
    def selected_indexes(self) -> list[int]:
        return sorted(self._selected)

    def is_downloaded(self, index: int) -> bool:
        key = self.entries[index].archive_key
        return bool(key) and key in self._downloaded

    def skipped_count(self) -> int:
        """Already-downloaded entries left out because of "Παράλειψη…"."""
        if not self.chk_skip.isChecked():
            return 0
        return sum(
            1
            for i, e in enumerate(self.entries)
            if e.available and self.is_downloaded(i) and i not in self._selected
        )

    def selected_items(self) -> list[SelectedItem]:
        total = max((e.position for e in self.entries), default=0)
        items = []
        for index in self.selected_indexes:
            entry = self.entries[index]
            name = sanitize_filename(self._names.get(index, entry.title), fallback=entry.id)
            if self.chk_numbering.isChecked():
                name = numbered_name(entry.position, total, name)
            items.append(SelectedItem(entry, name))
        return items

    def select_all(self) -> None:
        self._selected = {i for i, e in enumerate(self.entries) if e.available}
        self._sync_cards()

    def select_none(self) -> None:
        self._selected = set()
        self._sync_cards()

    def toggle(self, index: int) -> None:
        if not self.entries[index].available:
            return
        self._selected ^= {index}
        self._sync_cards()

    def rename(self, index: int, title: str) -> None:
        self._names[index] = title
        if index < len(self._cards):
            self._cards[index].set_title(title)

    def ensure_card(self, index: int) -> EntryCard | None:
        """Create batches up to ``index`` (keyboard navigation past the loaded cards)."""
        while index >= len(self._cards) and len(self._cards) < len(self.entries):
            self._add_batch()
        return self._cards[index] if index < len(self._cards) else None

    # --- internals ---------------------------------------------------------------------
    def _default_selection(self) -> set[int]:
        skip = self.chk_skip.isChecked()
        return {
            i
            for i, e in enumerate(self.entries)
            if e.available and not (skip and self.is_downloaded(i))
        }

    def _on_skip_toggled(self, skip: bool) -> None:
        downloaded = {
            i for i, e in enumerate(self.entries) if e.available and self.is_downloaded(i)
        }
        if skip:
            self._selected -= downloaded
        else:
            self._selected |= downloaded
        self._sync_cards()

    def _rebuild_cards(self) -> None:
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = []
        first = BATCH_SIZE if len(self.entries) > BATCH_THRESHOLD else len(self.entries)
        self._add_cards(first)

    def _add_batch(self) -> None:
        self._add_cards(BATCH_SIZE)

    def _add_cards(self, count: int) -> None:
        start = len(self._cards)
        width = self._card_width()
        for index in range(start, min(start + count, len(self.entries))):
            entry = self.entries[index]
            card = EntryCard(
                index,
                entry,
                selected=index in self._selected,
                downloaded=self.is_downloaded(index),
                title=self._names.get(index, entry.title),
                # Parented at once: a disabled card must never exist as a top-level window.
                parent=self.grid_host,
            )
            card.toggled.connect(self.toggle)
            card.renamed.connect(self.rename)
            card.navigate.connect(self._navigate)
            card.set_card_width(width)
            self._cards.append(card)
            self.grid.addWidget(card, index // self._columns, index % self._columns)
        self._thumb_timer.start()

    def _card_width(self) -> int:
        available = self.scroll.viewport().width() - 4
        self._columns = 3 if available >= WIDE_GRID_PX else 2
        return max(140, (available - GRID_SPACING * (self._columns - 1)) // self._columns)

    def _relayout(self) -> None:
        columns_before = self._columns
        width = self._card_width()
        if columns_before != self._columns:
            for card in self._cards:
                self.grid.removeWidget(card)
            for card in self._cards:
                self.grid.addWidget(card, card.index // self._columns, card.index % self._columns)
        for card in self._cards:
            card.set_card_width(width)
        self._thumb_timer.start()

    def _sync_cards(self) -> None:
        for card in self._cards:
            card.set_selected(card.index in self._selected)
        self._update_counts()

    def _update_counts(self) -> None:
        n = len(self._selected)
        total = len([e for e in self.entries if e.available])
        self.selected_label.setText(strings.LIST_SELECTED_COUNT.format(selected=n, total=total))
        self.btn_download.setText(download_button_text(n))
        self.btn_download.setAccessibleName(download_button_text(n))
        self.btn_download.setEnabled(n > 0)
        if n >= WARN_AT:
            name = platform_name(self.listing.extractor if self.listing else None)
            platform = (
                strings.LIST_PLATFORM_ARTICLE.format(name=name)
                if name
                else strings.LIST_PLATFORM_FALLBACK
            )
            self.warning.setText(strings.LIST_MANY_DOWNLOADS_WARNING.format(n=n, platform=platform))
        self.warning.setVisible(n >= WARN_AT)

    def _navigate(self, index: int, dx: int, dy: int) -> None:
        target = index + dx + dy * self._columns
        if not 0 <= target < len(self.entries):
            return
        # Skip disabled (private/unavailable) cards in the direction of travel.
        step = (1 if target > index else -1) * (self._columns if dy else 1)
        while 0 <= target < len(self.entries) and not self.entries[target].available:
            target += step
        if not 0 <= target < len(self.entries):
            return
        card = self.ensure_card(target)
        if card is not None:
            card.setFocus(Qt.FocusReason.TabFocusReason)
            self.scroll.ensureWidgetVisible(card, 0, 24)

    def _emit_download(self) -> None:
        items = self.selected_items()
        if items:
            self.download_requested.emit(items)

    def _on_scrolled(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        if len(self._cards) < len(self.entries) and value >= bar.maximum() - 400:
            self._add_batch()
        self._thumb_timer.start()

    def _load_visible_thumbnails(self) -> None:
        if self._thumbs is None:
            return
        viewport = self.scroll.viewport()
        visible = QRect(0, 0, viewport.width(), viewport.height()).adjusted(0, -200, 0, 400)
        for card in self._cards:
            if card.index in self._requested_thumbs or not card.entry.thumbnail_url:
                continue
            top_left = card.mapTo(viewport, card.rect().topLeft())
            if visible.intersects(QRect(top_left, card.size())):
                self._requested_thumbs.add(card.index)
                self._thumbs.load(card.entry.thumbnail_url, card.thumb.setPixmap)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._relayout()
        return super().eventFilter(obj, event)
