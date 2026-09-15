"""Tests for OpenCvFrameProvider — unit tests for frame serving (Phase A)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from aimation_actor_core.infrastructure.video.frame_provider import (
    FrameIndexOutOfRange,
    FrameProviderError,
    OpenCvFrameProvider,
)
from aimation_actor_core.shared.media_security import MediaPathError


def _make_video(path: Path, n_frames: int = 5) -> None:
    """Create a tiny synthetic MJPG video."""
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        25,
        (32, 32),
    )
    try:
        for i in range(n_frames):
            writer.write(np.full((32, 32, 3), i * 10, dtype=np.uint8))
    finally:
        writer.release()


@pytest.fixture()
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    root.mkdir()
    return root


@pytest.fixture()
def provider(media_root: Path) -> OpenCvFrameProvider:
    return OpenCvFrameProvider(media_root)


class TestGetFrameJpeg:
    def test_returns_jpeg_and_frame_count(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        jpeg, count = asyncio.run(provider.get_frame_jpeg("clip.avi", 1))
        assert isinstance(jpeg, bytes)
        assert len(jpeg) > 0
        assert count == 5
        # Verify valid JPEG
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        assert img.shape == (32, 32, 3)

    def test_first_frame_1based(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        jpeg, count = asyncio.run(provider.get_frame_jpeg("clip.avi", 1))
        assert count == 5
        assert len(jpeg) > 0

    def test_last_frame_1based(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        jpeg, count = asyncio.run(provider.get_frame_jpeg("clip.avi", 5))
        assert count == 5
        assert len(jpeg) > 0

    def test_out_of_range_raises(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        with pytest.raises(FrameIndexOutOfRange):
            asyncio.run(provider.get_frame_jpeg("clip.avi", 100))

    def test_zero_frame_raises(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        with pytest.raises(FrameIndexOutOfRange):
            asyncio.run(provider.get_frame_jpeg("clip.avi", 0))

    def test_traversal_rejected(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        with pytest.raises(MediaPathError):
            asyncio.run(provider.get_frame_jpeg("../clip.avi", 1))

    def test_with_resize_width(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        jpeg, _ = asyncio.run(provider.get_frame_jpeg("clip.avi", 1, width=16))
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        assert img.shape[1] == 16

    def test_different_frames_produce_different_jpegs(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        jpeg1, _ = asyncio.run(provider.get_frame_jpeg("clip.avi", 1))
        jpeg2, _ = asyncio.run(provider.get_frame_jpeg("clip.avi", 3))
        assert jpeg1 != jpeg2


class TestGetFrameCount:
    def test_returns_total_frames(self, provider: OpenCvFrameProvider, media_root: Path) -> None:
        _make_video(media_root / "clip.avi")
        count = asyncio.run(provider.get_frame_count("clip.avi"))
        assert count == 5

    def test_missing_video_raises(self, provider: OpenCvFrameProvider) -> None:
        with pytest.raises(MediaPathError):
            asyncio.run(provider.get_frame_count("nonexistent.avi"))
