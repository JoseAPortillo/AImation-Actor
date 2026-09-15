"""Unit tests for the shared media-root allowlist resolver (decision D3).

The resolver is the single security boundary for every media file access
(SDD §4.3): frame serving, uploads, and ``FrameExtractorNode``. Disallowed
paths must be rejected before any file is opened or read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aimation_actor_core.shared.media_security import MediaPathError, resolve_media_path

DISALLOWED_PATHS = [
    pytest.param(str(Path(".").resolve() / "outside.avi"), id="absolute"),
    pytest.param("../outside.avi", id="dotdot-traversal"),
    pytest.param("sub/../../outside.avi", id="nested-escape"),
]


class TestResolveMediaPath:
    """Behavior of the shared ``resolve_media_path`` allowlist resolver."""

    @pytest.mark.parametrize("bad", DISALLOWED_PATHS)
    def test_disallowed_path_rejected(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(MediaPathError):
            resolve_media_path(tmp_path, bad)

    @pytest.mark.parametrize("bad", DISALLOWED_PATHS)
    def test_disallowed_path_rejected_before_metadata_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        """Never opens: disallowed paths never reach exists()/is_file()."""

        def _explode(self: Path) -> bool:  # pragma: no cover
            raise AssertionError("metadata check ran for a disallowed path")

        monkeypatch.setattr(Path, "exists", _explode)
        monkeypatch.setattr(Path, "is_file", _explode)
        with pytest.raises(MediaPathError):
            resolve_media_path(tmp_path, bad)

    def test_missing_file_rejected_when_must_exist(self, tmp_path: Path) -> None:
        with pytest.raises(MediaPathError):
            resolve_media_path(tmp_path, "does-not-exist.avi")

    def test_directory_rejected_as_non_file(self, tmp_path: Path) -> None:
        (tmp_path / "subdir").mkdir()
        with pytest.raises(MediaPathError):
            resolve_media_path(tmp_path, "subdir")

    def test_must_exist_false_allows_nonexisting_relative_path(self, tmp_path: Path) -> None:
        target = tmp_path / "uploads" / "pending.avi"
        resolved = resolve_media_path(tmp_path, "uploads/pending.avi", must_exist=False)
        assert resolved == target.resolve()

    def test_must_exist_false_still_rejects_disallowed_paths(self, tmp_path: Path) -> None:
        with pytest.raises(MediaPathError):
            resolve_media_path(tmp_path, "../escape.avi", must_exist=False)

    def test_valid_existing_file_resolves_under_root(self, tmp_path: Path) -> None:
        target = tmp_path / "clip.avi"
        target.write_bytes(b"fake-video")
        resolved = resolve_media_path(tmp_path, "clip.avi")
        assert resolved == target.resolve()
        assert resolved.is_file()
