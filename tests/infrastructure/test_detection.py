"""Tests for SingleFramePoseDetectorImpl — unit tests for detection (Phase A)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from aimation_actor_core.domain.animation.pose_detection import SingleFramePose
from aimation_actor_core.infrastructure.ai_models.detection import (
    DetectionError,
    PoseDetectionUnavailableError,
    SingleFramePoseDetectorImpl,
)
from aimation_actor_core.infrastructure.ai_models.estimators import (
    OnnxBackend,
    SyntheticBackend,
)
from aimation_actor_core.shared.media_security import MediaPathError


def _make_video(path: Path, n_frames: int = 3) -> None:
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
def synthetic_detector(media_root: Path) -> SingleFramePoseDetectorImpl:
    return SingleFramePoseDetectorImpl(media_root, SyntheticBackend())


@pytest.fixture()
def onnx_detector(media_root: Path) -> SingleFramePoseDetectorImpl:
    return SingleFramePoseDetectorImpl(media_root, OnnxBackend("dummy.onnx"))


class TestDetect:
    def test_returns_keypoints_and_confidence(
        self, synthetic_detector: SingleFramePoseDetectorImpl, media_root: Path
    ) -> None:
        _make_video(media_root / "clip.avi")
        result = asyncio.run(synthetic_detector.detect("clip.avi", 1))
        assert isinstance(result, SingleFramePose)
        assert len(result.keypoints) == 17
        assert result.confidence == pytest.approx(0.95)

    def test_synthetic_keypoints_match_expected(
        self, synthetic_detector: SingleFramePoseDetectorImpl, media_root: Path
    ) -> None:
        _make_video(media_root / "clip.avi")
        result = asyncio.run(synthetic_detector.detect("clip.avi", 1))
        labels = [kp.label for kp in result.keypoints]
        assert labels == [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle",
        ]

    def test_deterministic_across_calls(
        self, synthetic_detector: SingleFramePoseDetectorImpl, media_root: Path
    ) -> None:
        _make_video(media_root / "clip.avi")
        r1 = asyncio.run(synthetic_detector.detect("clip.avi", 1))
        r2 = asyncio.run(synthetic_detector.detect("clip.avi", 1))
        assert r1 == r2

    def test_traversal_rejected(
        self, synthetic_detector: SingleFramePoseDetectorImpl
    ) -> None:
        with pytest.raises(MediaPathError):
            asyncio.run(synthetic_detector.detect("../clip.avi", 1))

    def test_missing_video_raises(
        self, synthetic_detector: SingleFramePoseDetectorImpl
    ) -> None:
        with pytest.raises(MediaPathError):
            asyncio.run(synthetic_detector.detect("nonexistent.avi", 1))

    def test_onnx_backend_raises_unavailable(
        self, onnx_detector: SingleFramePoseDetectorImpl, media_root: Path
    ) -> None:
        _make_video(media_root / "clip.avi")
        with pytest.raises(PoseDetectionUnavailableError):
            asyncio.run(onnx_detector.detect("clip.avi", 1))
