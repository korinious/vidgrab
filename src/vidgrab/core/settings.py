"""Persistent user settings stored as JSON (``%APPDATA%\\VidGrab\\settings.json``)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import platformdirs

from vidgrab import APP_NAME
from vidgrab.core.models import CookieConfig, CookieSource, Quality

log = logging.getLogger(__name__)

MIN_CONCURRENT = 1
MAX_CONCURRENT = 5
DEFAULT_CONCURRENT = 2


def default_settings_path() -> Path:
    return platformdirs.user_config_path(APP_NAME, appauthor=False, roaming=True) / "settings.json"


def default_download_dir() -> Path:
    return platformdirs.user_downloads_path()


@dataclass
class Settings:
    output_dir: str = field(default_factory=lambda: str(default_download_dir()))
    quality: Quality = Quality.BEST
    cookie_source: CookieSource = CookieSource.NONE
    cookie_file: str | None = None
    max_concurrent: int = DEFAULT_CONCURRENT

    @property
    def cookies(self) -> CookieConfig:
        return CookieConfig(self.cookie_source, self.cookie_file)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["quality"] = self.quality.value
        data["cookie_source"] = self.cookie_source.value
        return data

    @classmethod
    def from_json(cls, data: Any) -> Settings:
        """Build settings from parsed JSON, falling back to defaults for bad fields."""
        s = cls()
        if not isinstance(data, dict):
            log.warning("Settings file does not contain an object; using defaults")
            return s
        if isinstance(data.get("output_dir"), str) and data["output_dir"].strip():
            s.output_dir = data["output_dir"]
        try:
            s.quality = Quality(data.get("quality", s.quality))
        except ValueError:
            log.warning("Unknown quality %r in settings; using default", data.get("quality"))
        try:
            s.cookie_source = CookieSource(data.get("cookie_source", s.cookie_source))
        except ValueError:
            log.warning("Unknown cookie source %r in settings", data.get("cookie_source"))
        if isinstance(data.get("cookie_file"), str) and data["cookie_file"]:
            s.cookie_file = data["cookie_file"]
        mc = data.get("max_concurrent")
        if isinstance(mc, int) and not isinstance(mc, bool):
            s.max_concurrent = max(MIN_CONCURRENT, min(MAX_CONCURRENT, mc))
        return s


def load_settings(path: Path | None = None) -> Settings:
    path = path or default_settings_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except OSError:
        log.exception("Could not read settings from %s; using defaults", path)
        return Settings()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Settings file %s is corrupt; using defaults", path)
        return Settings()
    return Settings.from_json(data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically (temp file + rename)."""
    path = path or default_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings.to_json(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
