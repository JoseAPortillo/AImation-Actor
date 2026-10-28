"""Tests for the File menu's recent videos (FR-CAP-09).

The window records every clip whose media actually loaded (a corrupt file
never becomes "recent"), keeps the five most recent through an injected store,
and offers each entry under File ▸ Recent Files to reopen it. The production
store is QSettings; these tests inject a plain fake so no user settings are
touched.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.adapters.gui.recent_files import QSettingsRecentFilesStore
from aimation_actor.core.models import CapturedFrame


class _FakeSource(QObject):
    """A headless video source: records opens, never decodes anything."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None: ...

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        return None


class _MemoryStore:
    def __init__(self, paths: tuple[str, ...] = ()) -> None:
        self.paths = paths

    def load(self) -> tuple[str, ...]:
        return self.paths

    def save(self, paths) -> None:
        self.paths = tuple(paths)


def _window(qtbot, store: _MemoryStore) -> tuple[MainWindow, _FakeSource]:
    source = _FakeSource()
    window = MainWindow(source=source, recents=store)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    return window, source


def _open_and_load(window: MainWindow, source: _FakeSource, path: str) -> None:
    window.controller.open_video(path)
    source.media_loaded.emit(24.0, 1000)


def _recent_texts(window: MainWindow) -> list[str]:
    # The text as the animator sees it: QAction has no displayText in PySide6,
    # so resolve the escaped mnemonics the same way Qt's display does.
    return [
        action.text().replace("&&", "&")
        for action in window._recent_menu.actions()
        if not action.isSeparator()
    ]


def test_the_menu_starts_with_the_seeded_list_most_recent_first(qtbot) -> None:
    store = _MemoryStore(("D:\\clips\\newer.mp4", "D:\\clips\\older.mp4"))
    window, _ = _window(qtbot, store)

    assert _recent_texts(window) == ["D:\\clips\\newer.mp4", "D:\\clips\\older.mp4"]


def test_an_empty_list_keeps_the_menu_honest_with_a_disabled_placeholder(qtbot) -> None:
    window, _ = _window(qtbot, _MemoryStore())

    (placeholder,) = _recent_texts(window)
    assert "no recent" in placeholder.lower()
    assert not window._recent_menu.actions()[0].isEnabled()


def test_a_loaded_clip_is_recorded_and_moves_to_the_top(qtbot) -> None:
    store = _MemoryStore(("b.mp4", "a.mp4"))
    window, source = _window(qtbot, store)

    _open_and_load(window, source, "a.mp4")

    assert store.paths == ("a.mp4", "b.mp4")
    assert _recent_texts(window) == ["a.mp4", "b.mp4"]


def test_a_clip_that_never_loaded_stays_out_of_the_list(qtbot) -> None:
    store = _MemoryStore()
    window, source = _window(qtbot, store)

    window.controller.open_video("broken.mp4")  # no media_loaded: the open failed

    assert store.paths == ()
    assert _recent_texts(window) != ["broken.mp4"]


def test_selecting_a_recent_entry_reopens_that_clip(qtbot) -> None:
    store = _MemoryStore(("D:\\clips\\walk.mp4",))
    window, source = _window(qtbot, store)

    window._recent_menu.actions()[0].trigger()

    assert source.opened == ["D:\\clips\\walk.mp4"]


def test_the_list_never_grows_past_five_entries(qtbot) -> None:
    store = _MemoryStore(tuple(f"c{i}.mp4" for i in range(5)))
    window, source = _window(qtbot, store)

    _open_and_load(window, source, "new.mp4")

    assert store.paths == ("new.mp4", "c0.mp4", "c1.mp4", "c2.mp4", "c3.mp4")


def test_paths_are_stored_verbatim_with_ampersands_escaped_for_display(qtbot) -> None:
    store = _MemoryStore()
    window, source = _window(qtbot, store)

    _open_and_load(window, source, "D:\\clips\\rock & roll.mp4")

    assert store.paths == ("D:\\clips\\rock & roll.mp4",)
    assert _recent_texts(window) == ["D:\\clips\\rock & roll.mp4"]


def test_the_qsettings_store_round_trips_paths(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "recents.ini"), QSettings.Format.IniFormat)
    store = QSettingsRecentFilesStore(settings)

    store.save(("a.mp4", "b.mp4"))

    assert store.load() == ("a.mp4", "b.mp4")
    assert store.load() is not None


def test_the_qsettings_store_survives_a_reopen(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    ini = str(tmp_path / "recents.ini")
    QSettingsRecentFilesStore(QSettings(ini, QSettings.Format.IniFormat)).save(("x.mov",))

    reopened = QSettingsRecentFilesStore(QSettings(ini, QSettings.Format.IniFormat))

    assert reopened.load() == ("x.mov",)


def test_the_menu_shows_the_store_verbatim_at_startup(qtbot) -> None:
    # A fresh window reflects whatever the store holds, in order, one action
    # per path: the menu is a view of the store, never a second source.
    store = _MemoryStore(("D:\\a.mp4", "D:\\b.mov"))
    window, _ = _window(qtbot, store)

    assert _recent_texts(window) == ["D:\\a.mp4", "D:\\b.mov"]
