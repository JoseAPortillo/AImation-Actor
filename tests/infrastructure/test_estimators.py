"""Tests for PoseEstimator protocol and SyntheticBackend."""

import builtins
import importlib.util

import numpy as np
import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.pose_detection import SingleFramePose
from aimation_actor_core.infrastructure.ai_models.estimators import (
    OnnxBackend,
    PoseEstimator,
    SyntheticBackend,
)


class TestSyntheticBackend:
    """Test SyntheticBackend implementation."""

    def test_implements_protocol(self) -> None:
        """Should implement PoseEstimator protocol."""
        backend = SyntheticBackend()
        assert isinstance(backend, PoseEstimator)

    def test_estimate_returns_keypoints2d_list(self) -> None:
        """Should return list of Keypoints2D."""
        backend = SyntheticBackend()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(3)]

        result = backend.estimate(frames)

        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(kp, Keypoints2D) for kp in result)

    def test_estimate_frame_indices_match(self) -> None:
        """Should assign correct frame indices."""
        backend = SyntheticBackend()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(5)]

        result = backend.estimate(frames)

        for i, kp2d in enumerate(result):
            assert kp2d.frame_index == i

    def test_estimate_deterministic(self) -> None:
        """Should produce same output for same input (deterministic)."""
        backend = SyntheticBackend()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(2)]

        result1 = backend.estimate(frames)
        result2 = backend.estimate(frames)

        # Should have same structure
        assert len(result1) == len(result2)
        for kp1, kp2 in zip(result1, result2, strict=True):
            assert kp1.frame_index == kp2.frame_index
            assert len(kp1.keypoints) == len(kp2.keypoints)
            for k1, k2 in zip(kp1.keypoints, kp2.keypoints, strict=True):
                assert k1.label == k2.label
                assert k1.x == k2.x
                assert k1.y == k2.y
                assert k1.confidence == k2.confidence

    def test_estimate_keypoints_have_valid_structure(self) -> None:
        """Should produce keypoints with valid structure."""
        backend = SyntheticBackend()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        result = backend.estimate(frames)

        assert len(result) == 1
        kp2d = result[0]
        assert kp2d.frame_index == 0
        assert len(kp2d.keypoints) > 0

        # Each keypoint should have valid fields
        for kp in kp2d.keypoints:
            assert isinstance(kp.label, str)
            assert len(kp.label) > 0
            assert 0.0 <= kp.x <= 1.0
            assert 0.0 <= kp.y <= 1.0
            assert 0.0 <= kp.confidence <= 1.0

    def test_estimate_empty_frames(self) -> None:
        """Should handle empty frames list."""
        backend = SyntheticBackend()
        frames = []

        result = backend.estimate(frames)

        assert result == []

    def test_estimate_keypoints_are_json_serializable(self) -> None:
        """Should produce JSON-serializable keypoints."""
        backend = SyntheticBackend()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        result = backend.estimate(frames)

        # Should serialize without error
        json_str = result[0].model_dump_json()
        assert "frame_index" in json_str
        assert "keypoints" in json_str


class TestOnnxBackend:
    """Test OnnxBackend implementation."""

    def test_implements_protocol(self) -> None:
        """Should implement PoseEstimator protocol."""
        backend = OnnxBackend(model_dir="dummy.onnx")
        assert isinstance(backend, PoseEstimator)

    def test_estimate_without_onnxruntime_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should raise a clear ImportError when onnxruntime is unavailable.

        The lazy onnxruntime import is deterministically forced to fail by
        patching ``__import__``, so this test never passes vacuously and does
        not depend on whether onnxruntime happens to be installed.
        """
        backend = OnnxBackend(model_dir="dummy.onnx")
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        real_import = builtins.__import__

        def fake_import(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "onnxruntime" or name.startswith("onnxruntime."):
                raise ImportError("No module named 'onnxruntime'")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError) as exc_info:
            backend.estimate(frames)

        assert "onnxruntime" in str(exc_info.value).lower()

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    def test_estimate_with_missing_models_raises_file_not_found(self) -> None:
        """Should fail cleanly when the ONNX model directory has no models."""
        backend = OnnxBackend(model_dir="dummy.onnx")
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        with pytest.raises(FileNotFoundError):
            backend.estimate(frames)


class TestEstimateSingle:
    """estimate_single: factory output for the single-frame sync endpoint."""

    def test_synthetic_returns_single_frame_pose(self) -> None:
        backend = SyntheticBackend()
        result = backend.estimate_single(np.zeros((100, 100, 3), dtype=np.uint8))
        assert isinstance(result, SingleFramePose)

    def test_synthetic_emits_fixed_17_keypoints(self) -> None:
        backend = SyntheticBackend()
        result = backend.estimate_single(np.zeros((100, 100, 3), dtype=np.uint8))
        assert len(result.keypoints) == 17
        assert [kp.label for kp in result.keypoints] == SyntheticBackend.KEYPOINT_LABELS

    def test_synthetic_confidence_fixed_at_095_every_call(self) -> None:
        backend = SyntheticBackend()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        first = backend.estimate_single(frame)
        second = backend.estimate_single(frame)
        assert first.confidence == pytest.approx(0.95)
        assert second == first

    def test_synthetic_keypoints_normalized_and_in_range(self) -> None:
        backend = SyntheticBackend()
        result = backend.estimate_single(np.zeros((10, 10, 3), dtype=np.uint8))
        for kp in result.keypoints:
            assert isinstance(kp, Keypoint)
            assert 0.0 <= kp.x <= 1.0
            assert 0.0 <= kp.y <= 1.0
            assert 0.0 <= kp.confidence <= 1.0

    def test_synthetic_single_matches_batch_estimate_keypoints(self) -> None:
        backend = SyntheticBackend()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        single = backend.estimate_single(frame)
        batch = backend.estimate([frame])[0]
        assert [kp.model_dump() for kp in single.keypoints] == [
            kp.model_dump() for kp in batch.keypoints
        ]

    def test_onnx_estimate_single_stays_lazy(self) -> None:
        backend = OnnxBackend(model_dir="dummy.onnx")
        with pytest.raises(FileNotFoundError):
            backend.estimate_single(np.zeros((10, 10, 3), dtype=np.uint8))
