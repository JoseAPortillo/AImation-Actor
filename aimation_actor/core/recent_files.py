"""The recent-videos list (FR-CAP-09): pure domain rules, no Qt.

The File menu shows the last five video files the animator opened, most
recent first. Re-opening a known path moves it to the top instead of adding a
duplicate; the list never grows past its limit. Paths are *compared* by
``os.path.normcase`` — on Windows the same file reopened under a different
case is not a new entry — while the *displayed* string stays exactly what the
animator opened. Standard library only, like the rest of ``core``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

__all__ = ["RECENT_FILES_LIMIT", "push_recent"]

#: How many recent videos the File menu keeps.
RECENT_FILES_LIMIT = 5


def push_recent(
    paths: Sequence[str], path: str, *, limit: int = RECENT_FILES_LIMIT
) -> tuple[str, ...]:
    """``paths`` with ``path`` recorded as most recent, deduped and capped.

    ``path`` lands at the front; any earlier entry naming the same file (by
    ``os.path.normcase``) is dropped, and anything past ``limit`` falls off
    the tail.
    """
    if limit <= 0:
        return ()
    fresh = os.path.normcase(path)
    kept = [existing for existing in paths if os.path.normcase(existing) != fresh]
    return (path, *kept)[:limit]
