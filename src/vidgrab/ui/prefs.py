"""UI-only preferences (theme), stored next to settings.json as ui.json.

Kept out of ``core.settings`` on purpose: the core knows nothing about presentation.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vidgrab.core.settings import default_settings_path
from vidgrab.ui.theme import ThemeMode

log = logging.getLogger(__name__)


def prefs_path_for(settings_path: Path | None) -> Path:
    return (settings_path or default_settings_path()).with_name("ui.json")


@dataclass
class UiPrefs:
    theme: ThemeMode = ThemeMode.AUTO


def load_prefs(path: Path) -> UiPrefs:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return UiPrefs()
    except (OSError, ValueError):
        log.warning("Could not read %s; using default UI preferences", path)
        return UiPrefs()
    prefs = UiPrefs()
    try:
        prefs.theme = ThemeMode(data.get("theme", prefs.theme))
    except (ValueError, AttributeError):
        log.warning("Unknown theme in %s", path)
    return prefs


def save_prefs(prefs: UiPrefs, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ui-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"theme": prefs.theme.value}, fh)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
