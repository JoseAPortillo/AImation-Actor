"""Capture discovery for the transposition tool.

Deliberately free of ``bpy``: the repository's pytest run imports this module by
path and covers it without Blender. The extension package imports it normally.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

__all__ = [
    "CAPTURE_SUFFIX",
    "capture_names",
    "capture_names_in",
    "capture_path",
    "resolve_capture",
]

#: Only the application's binary FBX exports belong in the capture list.
CAPTURE_SUFFIX = ".fbx"


def capture_names(names: Iterable[str]) -> tuple[str, ...]:
    """The capture file names among ``names``, case-insensitively sorted.

    Sorting is casefolded so a listbox never interleaves ``Take_01.fbx`` with
    ``take_02.fbx`` differently depending on the filesystem's case handling.
    """
    return tuple(
        sorted(
            (name for name in names if Path(name).suffix.lower() == CAPTURE_SUFFIX),
            key=str.casefold,
        )
    )


def capture_names_in(directory: str | Path | None) -> tuple[str, ...]:
    """Every capture file name in ``directory``.

    A missing, empty, or unreadable folder is an empty list, never an error:
    the panel must render before any capture exists (S9).
    """
    if not directory:
        return ()
    try:
        entries = tuple(Path(directory).iterdir())
    except OSError:
        return ()
    return capture_names(entry.name for entry in entries if entry.is_file())


def capture_path(directory: str | Path | None, name: str) -> Path | None:
    """The full path of one capture, or ``None`` without a folder."""
    if not directory or not name:
        return None
    return Path(directory) / name


def resolve_capture(
    directory: str | Path | None, name: str, explicit_path: str = ""
) -> Path | None:
    """The file a capture-list row means.

    Rows added by ``Import Capture`` remember the exact file the animator
    picked, which may live outside the configured capture folder; folder rows
    resolve against ``directory``. An explicit path never falls back to the
    folder rule: if that file is gone the row means nothing, and the load
    fails with a named reason like any other missing capture (S9).
    """
    if explicit_path:
        return Path(explicit_path)
    return capture_path(directory, name)
