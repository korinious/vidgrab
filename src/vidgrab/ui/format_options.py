"""Quality / format / bitrate pickers, used by the preview card and the list selection screen.

Both instances show the same saved choices: when one changes, the window updates the
settings and re-syncs the other with ``set_from()``.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from vidgrab import strings
from vidgrab.core.models import MP3_BITRATES, AudioFormat, Quality, VideoContainer
from vidgrab.core.settings import Settings
from vidgrab.ui.labels import (
    AUDIO_FORMAT_LABELS,
    AUDIO_FORMAT_ORDER,
    CONTAINER_LABELS,
    CONTAINER_ORDER,
    QUALITY_LABELS,
    QUALITY_ORDER,
    bitrate_label,
)
from vidgrab.ui.widgets import SegmentedControl, label

OPTION_LABEL_WIDTH = 72  # the option rows line up


def option_label(text: str) -> QLabel:
    widget = label(text, tone="muted")
    widget.setMinimumWidth(OPTION_LABEL_WIDTH)
    return widget


class FormatOptions(QWidget):
    changed = Signal()  # the user picked something; read it with apply_to()

    def __init__(
        self, settings: Settings, parent: QWidget | None = None, *, compact: bool = False
    ) -> None:
        super().__init__(parent)
        self._settings = settings

        self.quality_combo = SegmentedControl(strings.QUALITY_SEGMENT_NAME)
        for q in QUALITY_ORDER:
            self.quality_combo.addItem(QUALITY_LABELS[q], q)
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)

        # Its items depend on the quality: MP4/MKV for video, MP3/Original for audio.
        self.format_combo = SegmentedControl(strings.FORMAT_SEGMENT_NAME)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)

        self.bitrate_label = option_label(strings.LABEL_BITRATE)
        self.bitrate_combo = SegmentedControl(strings.BITRATE_SEGMENT_NAME)
        for kbps in MP3_BITRATES:
            self.bitrate_combo.addItem(bitrate_label(kbps), kbps)
        self.bitrate_combo.setToolTip(strings.TOOLTIP_BITRATE)
        self.bitrate_label.setToolTip(strings.TOOLTIP_BITRATE)
        self.bitrate_combo.currentIndexChanged.connect(self._on_bitrate_changed)

        rows = QVBoxLayout(self)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        pairs = [
            (option_label(strings.LABEL_QUALITY), self.quality_combo),
            (option_label(strings.LABEL_FORMAT), self.format_combo),
            (self.bitrate_label, self.bitrate_combo),
        ]
        # compact (list toolbar): quality and format share a row; bitrate below.
        groups = [pairs[:2], pairs[2:]] if compact else [[p] for p in pairs]
        for group in groups:
            row = QHBoxLayout()
            row.setSpacing(10)
            for i, (name_label, widget) in enumerate(group):
                if i:
                    row.addSpacing(14)
                if compact:
                    name_label.setMinimumWidth(0)
                row.addWidget(name_label)
                row.addWidget(widget)
            row.addStretch(1)
            rows.addLayout(row)
        self.set_from(settings)

    # --- state -------------------------------------------------------------------------
    def quality(self) -> Quality:
        # Item data may come back as plain str (StrEnum); convert at the boundary.
        return Quality(self.quality_combo.currentData())

    def set_from(self, settings: Settings) -> None:
        """Show ``settings`` without emitting ``changed``."""
        self._settings = settings
        for combo in (self.quality_combo, self.bitrate_combo):
            combo.blockSignals(True)
        self.quality_combo.setCurrentIndex(QUALITY_ORDER.index(settings.quality))
        self.bitrate_combo.setCurrentIndex(MP3_BITRATES.index(settings.mp3_bitrate))
        for combo in (self.quality_combo, self.bitrate_combo):
            combo.blockSignals(False)
        self._fill_format_combo()

    def apply_to(self, settings: Settings) -> Settings:
        """``settings`` with the choices shown here."""
        quality = self.quality()
        data = self.format_combo.currentData()
        settings = replace(
            settings, quality=quality, mp3_bitrate=int(self.bitrate_combo.currentData())
        )
        if data is not None:
            if quality.is_audio:
                settings = replace(settings, audio_format=AudioFormat(data))
            else:
                settings = replace(settings, video_container=VideoContainer(data))
        return settings

    # --- internals ---------------------------------------------------------------------
    def _fill_format_combo(self) -> None:
        """Show the format choices for the current quality, preselecting the saved one."""
        combo = self.format_combo
        combo.blockSignals(True)
        combo.clear()
        if self.quality().is_audio:
            for fmt in AUDIO_FORMAT_ORDER:
                combo.addItem(AUDIO_FORMAT_LABELS[fmt], fmt)
            combo.setCurrentIndex(AUDIO_FORMAT_ORDER.index(self._settings.audio_format))
            combo.setToolTip(strings.TOOLTIP_FORMAT_AUDIO)
        else:
            for container in CONTAINER_ORDER:
                combo.addItem(CONTAINER_LABELS[container], container)
            combo.setCurrentIndex(CONTAINER_ORDER.index(self._settings.video_container))
            combo.setToolTip(strings.TOOLTIP_FORMAT_VIDEO)
        combo.blockSignals(False)
        self._sync_bitrate_visibility()

    def _sync_bitrate_visibility(self) -> None:
        data = self.format_combo.currentData()
        show = self.quality().is_audio and data is not None and AudioFormat(data) is AudioFormat.MP3
        self.bitrate_label.setVisible(show)
        self.bitrate_combo.setVisible(show)

    def _on_quality_changed(self) -> None:
        self._settings = replace(self._settings, quality=self.quality())
        self._fill_format_combo()
        self.changed.emit()

    def _on_format_changed(self) -> None:
        self._settings = self.apply_to(self._settings)
        self._sync_bitrate_visibility()
        self.changed.emit()

    def _on_bitrate_changed(self) -> None:
        self._settings = self.apply_to(self._settings)
        self.changed.emit()
