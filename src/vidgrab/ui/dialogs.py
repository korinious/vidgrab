"""Settings dialog."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
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

from vidgrab import __version__, strings
from vidgrab.core import archive
from vidgrab.core.cookies import COOKIE_SOURCE_LABELS, COOKIE_SOURCES_ORDER
from vidgrab.core.models import CookieSource
from vidgrab.core.settings import MAX_CONCURRENT, MIN_CONCURRENT, Settings
from vidgrab.core.updates import CheckResult, CheckStatus
from vidgrab.ui.theme import ThemeMode
from vidgrab.ui.widgets import CheckBox, set_prop

THEME_ORDER = [ThemeMode.AUTO, ThemeMode.LIGHT, ThemeMode.DARK]
THEME_LABELS = {
    ThemeMode.AUTO: strings.THEME_AUTO,
    ThemeMode.LIGHT: strings.THEME_LIGHT,
    ThemeMode.DARK: strings.THEME_DARK,
}


class SettingsDialog(QDialog):
    check_requested = Signal()  # "Έλεγχος τώρα"; the window runs the check

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        theme: ThemeMode = ThemeMode.AUTO,
        versions: dict[str, str | None] | None = None,
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

        # Updates: automatic check, "Έλεγχος τώρα" with the result inline, versions.
        self.auto_update_check = CheckBox(strings.OPTION_AUTO_UPDATE_CHECK)
        self.auto_update_check.setChecked(settings.auto_update_check)
        self.btn_check_now = QPushButton(strings.BTN_CHECK_NOW)
        self.btn_check_now.setAccessibleName(strings.BTN_CHECK_NOW)
        self.btn_check_now.clicked.connect(self.check_requested)
        self.check_result = QLabel()
        self.check_result.setProperty("tone", "muted")
        self.check_result.setWordWrap(True)
        updates_row = QHBoxLayout()
        updates_row.setContentsMargins(0, 0, 0, 0)
        updates_row.addWidget(self.auto_update_check)
        updates_row.addStretch(1)
        updates_row.addWidget(self.btn_check_now)
        updates_hint = QLabel(strings.AUTO_UPDATE_CHECK_HINT)
        updates_hint.setWordWrap(True)
        updates_hint.setProperty("tone", "muted")
        self.versions_label = QLabel()
        self.versions_label.setProperty("tone", "muted")
        self.versions_label.setWordWrap(True)
        self.set_versions(versions or {})

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
        form.addRow(strings.LABEL_UPDATES, updates_row)
        form.addRow("", self.check_result)
        form.addRow("", updates_hint)
        form.addRow(strings.LABEL_VERSIONS, self.versions_label)
        form.addRow(buttons)
        self.check_result.hide()

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
            auto_update_check=self.auto_update_check.isChecked(),
        )

    def result_theme(self) -> ThemeMode:
        # QComboBox hands StrEnum item data back as plain str; convert at the boundary.
        return ThemeMode(self.theme_combo.currentData())

    # --- updates ----------------------------------------------------------------------
    def set_versions(self, versions: dict[str, str | None]) -> None:
        def show(name: str) -> str:
            return versions.get(name) or strings.UNKNOWN_VALUE

        self.versions_label.setText(
            strings.VERSIONS_LINE.format(
                vidgrab=__version__, ytdlp=show("yt-dlp"), ffmpeg=show("ffmpeg"), deno=show("deno")
            )
        )

    def show_check_running(self) -> None:
        self.btn_check_now.setEnabled(False)
        self._set_check_result(strings.CHECK_RUNNING, "muted")

    def show_check_result(self, result: CheckResult) -> None:
        self.btn_check_now.setEnabled(True)
        if result.status is CheckStatus.AVAILABLE and result.update is not None:
            text = strings.CHECK_AVAILABLE.format(version=result.update.version)
            self._set_check_result(text, "strong")
        elif result.status is CheckStatus.UP_TO_DATE:
            self._set_check_result(strings.CHECK_UP_TO_DATE, "success")
        else:
            self._set_check_result(strings.CHECK_FAILED, "error")

    def _set_check_result(self, text: str, tone: str) -> None:
        self.check_result.setText(text)
        set_prop(self.check_result, "tone", tone)
        self.check_result.show()

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
