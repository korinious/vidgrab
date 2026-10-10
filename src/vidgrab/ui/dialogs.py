"""Settings dialog."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from vidgrab import strings
from vidgrab.core import archive
from vidgrab.core.cookies import COOKIE_SOURCE_LABELS, COOKIE_SOURCES_ORDER
from vidgrab.core.models import CookieSource
from vidgrab.core.settings import MAX_CONCURRENT, MIN_CONCURRENT, Settings
from vidgrab.ui.theme import ThemeMode

THEME_ORDER = [ThemeMode.AUTO, ThemeMode.LIGHT, ThemeMode.DARK]
THEME_LABELS = {
    ThemeMode.AUTO: strings.THEME_AUTO,
    ThemeMode.LIGHT: strings.THEME_LIGHT,
    ThemeMode.DARK: strings.THEME_DARK,
}


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        theme: ThemeMode = ThemeMode.AUTO,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.DIALOG_SETTINGS_TITLE)
        self.setMinimumWidth(480)
        self._settings = settings

        self.cookie_source = QComboBox()
        for source in COOKIE_SOURCES_ORDER:
            self.cookie_source.addItem(COOKIE_SOURCE_LABELS[source], source)
        self.cookie_source.setCurrentIndex(COOKIE_SOURCES_ORDER.index(settings.cookie_source))

        self.cookie_file = QLineEdit(settings.cookie_file or "")
        self.cookie_browse = QPushButton(strings.BTN_BROWSE)
        self.cookie_browse.clicked.connect(self._browse_cookie_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.cookie_file, 1)
        file_row.addWidget(self.cookie_browse)
        self.cookie_file_row = QWidget()
        self.cookie_file_row.setLayout(file_row)
        file_row.setContentsMargins(0, 0, 0, 0)

        hint = QLabel(strings.COOKIES_HINT)
        hint.setWordWrap(True)
        hint.setProperty("tone", "muted")

        self.theme_combo = QComboBox()
        for mode in THEME_ORDER:
            self.theme_combo.addItem(THEME_LABELS[mode], mode)
        self.theme_combo.setCurrentIndex(THEME_ORDER.index(ThemeMode(theme)))

        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(MIN_CONCURRENT, MAX_CONCURRENT)
        self.max_concurrent.setValue(settings.max_concurrent)

        # Download history ("Υπάρχει ήδη" in lists); cleared at once, after confirmation.
        self.history_count = QLabel()
        self.history_count.setProperty("tone", "muted")
        self.btn_clear_history = QPushButton(strings.BTN_CLEAR_HISTORY)
        self.btn_clear_history.setAccessibleName(strings.BTN_CLEAR_HISTORY)
        self.btn_clear_history.clicked.connect(self.clear_history)
        history_row = QHBoxLayout()
        history_row.setContentsMargins(0, 0, 0, 0)
        history_row.addWidget(self.history_count)
        history_row.addStretch(1)
        history_row.addWidget(self.btn_clear_history)
        history_hint = QLabel(strings.HISTORY_HINT)
        history_hint.setWordWrap(True)
        history_hint.setProperty("tone", "muted")
        self._update_history()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow(strings.LABEL_THEME, self.theme_combo)
        form.addRow(strings.LABEL_COOKIES, self.cookie_source)
        form.addRow(strings.LABEL_COOKIE_FILE, self.cookie_file_row)
        form.addRow("", hint)
        form.addRow(strings.LABEL_MAX_CONCURRENT, self.max_concurrent)
        form.addRow(strings.LABEL_HISTORY, history_row)
        form.addRow("", history_hint)
        form.addRow(buttons)

        self.cookie_source.currentIndexChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _selected_source(self) -> CookieSource:
        # QComboBox hands StrEnum item data back as plain str; convert at the boundary.
        return CookieSource(self.cookie_source.currentData())

    def _sync_enabled(self) -> None:
        self.cookie_file_row.setEnabled(self._selected_source() is CookieSource.FILE)

    def _browse_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            strings.DIALOG_CHOOSE_COOKIE_FILE,
            self.cookie_file.text(),
            strings.DIALOG_COOKIE_FILE_FILTER,
        )
        if path:
            self.cookie_file.setText(path)

    def result_settings(self) -> Settings:
        return replace(
            self._settings,
            cookie_source=self._selected_source(),
            cookie_file=self.cookie_file.text().strip() or None,
            max_concurrent=self.max_concurrent.value(),
        )

    def result_theme(self) -> ThemeMode:
        # QComboBox hands StrEnum item data back as plain str; convert at the boundary.
        return ThemeMode(self.theme_combo.currentData())

    # --- download history ------------------------------------------------------------
    def _update_history(self) -> None:
        count = archive.count()
        self.history_count.setText(history_count_text(count))
        self.btn_clear_history.setEnabled(count > 0)

    def clear_history(self) -> None:
        count = archive.count()
        if count and self._confirm_clear_history(count):
            archive.clear()
        self._update_history()

    def _confirm_clear_history(self, count: int) -> bool:
        answer = QMessageBox.question(
            self,
            strings.CONFIRM_CLEAR_HISTORY_TITLE,
            strings.CONFIRM_CLEAR_HISTORY_TEXT.format(count=history_count_text(count)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes


def history_count_text(count: int) -> str:
    return strings.HISTORY_COUNT_ONE if count == 1 else strings.HISTORY_COUNT_MANY.format(n=count)
