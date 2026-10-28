"""The recent-videos store behind the File menu (FR-CAP-09).

The window's rule lives in ``core.recent_files`` (pure); this module is only
where those paths persist between sessions. ``RecentFilesStore`` is the seam
the window talks to — tests inject a plain fake — while the production
implementation uses ``QSettings``, the same place every desktop app keeps its
user state. The store holds verbatim path strings; it never rewrites,
reorders, or caps them (that is the domain's job).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from PySide6.QtCore import QSettings

__all__ = ["QSettingsRecentFilesStore", "RecentFilesStore"]

_SETTINGS_KEY = "recentFiles"


class RecentFilesStore(Protocol):
    """Where the recent-videos paths persist: load them back, save them."""

    def load(self) -> tuple[str, ...]: ...

    def save(self, paths: Sequence[str]) -> None: ...


class QSettingsRecentFilesStore:
    """The production store: the user's own settings, per application."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    def load(self) -> tuple[str, ...]:
        value = self._settings.value(_SETTINGS_KEY)
        if value is None:
            return ()
        if isinstance(value, str):
            # QSettings collapses a one-item list to a bare string.
            return (value,)
        return tuple(str(item) for item in value)

    def save(self, paths: Sequence[str]) -> None:
        self._settings.setValue(_SETTINGS_KEY, list(paths))
