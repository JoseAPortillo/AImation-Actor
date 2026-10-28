"""Tests for the recent-files list (FR-CAP-09).

Pure domain logic: the File menu keeps the last five video files the animator
opened, most recent first; re-opening a known path moves it to the top instead
of duplicating it; anything beyond the fifth falls off. Comparison follows
``os.path.normcase``, so on Windows a path reopened under a different case is
the same file.
"""

from __future__ import annotations

import os

from aimation_actor.core.recent_files import push_recent


def test_the_first_opened_path_lands_at_the_top() -> None:
    assert push_recent((), "D:\\clips\\walk.mp4") == ("D:\\clips\\walk.mp4",)


def test_reopening_a_known_path_moves_it_to_the_top_without_duplicating() -> None:
    paths = ("D:\\clips\\a.mp4", "D:\\clips\\b.mp4", "D:\\clips\\c.mp4")

    result = push_recent(paths, "D:\\clips\\b.mp4")

    assert result == ("D:\\clips\\b.mp4", "D:\\clips\\a.mp4", "D:\\clips\\c.mp4")


def test_only_the_five_most_recent_paths_are_kept() -> None:
    paths = tuple(f"C:\\v{i}.mp4" for i in range(5))

    result = push_recent(paths, "C:\\new.mp4")

    assert result == ("C:\\new.mp4", "C:\\v0.mp4", "C:\\v1.mp4", "C:\\v2.mp4", "C:\\v3.mp4")


def test_the_limit_is_clamped_so_preseeded_lists_cannot_exceed_it() -> None:
    result = push_recent(("x.mp4", "y.mp4"), "z.mp4", limit=2)

    assert result == ("z.mp4", "x.mp4")


def test_paths_are_compared_by_their_normalized_form_but_kept_verbatim() -> None:
    known = ("D:\\Clips\\Walk.MP4",)

    result = push_recent(known, "d:\\clips\\walk.mp4")

    assert result == ("d:\\clips\\walk.mp4",)
    assert os.path.normcase(result[0]) == os.path.normcase(known[0])
