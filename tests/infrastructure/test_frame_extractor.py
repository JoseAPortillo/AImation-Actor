"""Unit + integration tests for FrameExtractorNode (video-source).

Covers the catalog schema, param validation, the media-root path allowlist
(security), and the real decode path over a video generated at test time
(no binary committed — reproducible via cv2.VideoWriter).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    NodeOutput,
)
from aimation_actor_core.domain.pipeline.schema import DataType
from aimation_actor_core.infrastructure.video.frame_extractor import (
    FrameExtractorNode,
    VideoPathError,
)

FRAME_SIZE = (32, 32)
FPS = 25
N_FRAMES = 8


def _make_video(path: Path, n_frames: int = N_FRAMES, fps: float = FPS) -> None:
    """Generate a synthetic MJPG .avi (the video-source test fixture)."""
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        FRAME_SIZE,
    )
    assert writer.isOpened(), "cv2.VideoWriter could not open; codec unsupported"
    try:
        for i in range(n_frames):
            frame = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), i * 10, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def _ctx() -> ExecutionContext:
    return ExecutionContext(trace_id="trace-1")


def _make_node(tmp_path: Path, media_root: Path | None = None) -> FrameExtractorNode:
    return FrameExtractorNode(media_root=media_root or tmp_path)


class TestSchema:
    def test_catalog_schema(self, tmp_path: Path) -> None:
        schema = _make_node(tmp_path).get_schema()
        assert schema.type == "video-source"
        assert schema.category.value == "source"
        assert schema.inputs == []
        assert {p.name for p in schema.outputs} == {"frames", "fps"}
        assert schema.params[0].name == "video_path"
        assert schema.params[0].data_type == DataType.VIDEO_PATH
        assert schema.params[0].required is True


class TestValidate:
    async def test_missing_video_path_invalid(self, tmp_path: Path) -> None:
        result = await _make_node(tmp_path).validate({})
        assert result.valid is False
        assert any("video_path" in e for e in result.errors)

    async def test_blank_video_path_invalid(self, tmp_path: Path) -> None:
        result = await _make_node(tmp_path).validate({"video_path": "  "})
        assert result.valid is False

    async def test_present_video_path_valid(self, tmp_path: Path) -> None:
        result = await _make_node(tmp_path).validate({"video_path": "clip.avi"})
        assert result.valid is True


class TestPathAllowlist:
    """SDD §4.3 — reject disallowed paths BEFORE any cv2.VideoCapture opens them."""

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        node = _make_node(tmp_path)
        with pytest.raises(VideoPathError):
            node._resolve_video_path(str(tmp_path / "clip.avi"))

    def test_traversal_escape_rejected(self, tmp_path: Path) -> None:
        node = _make_node(tmp_path)
        with pytest.raises(VideoPathError):
            node._resolve_video_path("../outside.avi")

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        node = _make_node(tmp_path)
        with pytest.raises(VideoPathError):
            node._resolve_video_path("does-not-exist.avi")

    def test_directory_rejected(self, tmp_path: Path) -> None:
        node = _make_node(tmp_path)
        with pytest.raises(VideoPathError):
            node._resolve_video_path("subdir")

    def test_allowed_relative_path_resolves(self, tmp_path: Path) -> None:
        _make_video(tmp_path / "clip.avi")
        node = _make_node(tmp_path)
        resolved = node._resolve_video_path("clip.avi")
        assert resolved == (tmp_path / "clip.avi").resolve()

    def test_reject_happens_before_videocapture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disallowed path never reaches cv2.VideoCapture (no read attempted)."""
        opened: list[str] = []

        def fake_capture(*args: object, **kwargs: object) -> object:  # pragma: no cover
            opened.append(str(args[0]))
            raise AssertionError("VideoCapture should not be reached for a disallowed path")

        monkeypatch.setattr(cv2, "VideoCapture", fake_capture)
        node = _make_node(tmp_path)
        with pytest.raises(VideoPathError):
            node._resolve_video_path("../escape.avi")
        assert opened == []


class TestDecode:
    async def test_decode_reports_fps_frame_count_slice_and_resize(self, tmp_path: Path) -> None:
        _make_video(tmp_path / "clip.avi")
        node = _make_node(tmp_path)
        out = await node.execute(
            {},
            {"video_path": "clip.avi", "start": 1, "end": 5, "resize": 16},
            _ctx(),
        )
        assert isinstance(out, NodeOutput)
        frames = out.values["frames"]
        assert len(frames) == 4  # [1, 5)
        assert out.values["fps"] == pytest.approx(FPS)
        # resize=16 -> 16x16
        assert frames[0].shape == (16, 16, 3)

    async def test_decode_full_video_without_bounds(self, tmp_path: Path) -> None:
        _make_video(tmp_path / "clip.avi")
        node = _make_node(tmp_path)
        out = await node.execute({}, {"video_path": "clip.avi"}, _ctx())
        assert len(out.values["frames"]) == N_FRAMES

    async def test_decode_media_root_is_separate_from_cwd(self, tmp_path: Path) -> None:
        # media_root need not be the cwd; resolution is rooted at media_root.
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        node = _make_node(tmp_path, media_root=media_root)
        out = await node.execute({}, {"video_path": "clip.avi"}, _ctx())
        assert len(out.values["frames"]) == N_FRAMES
