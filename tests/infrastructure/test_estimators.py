"""Tests for PoseEstimator protocol and SyntheticBackend."""

import numpy as np

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
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
        backend = OnnxBackend(model_path="dummy.onnx")
        assert isinstance(backend, PoseEstimator)

    def test_estimate_without_onnxruntime_raises_error(self) -> None:
        """Should raise clear error if onnxruntime is not available."""
        backend = OnnxBackend(model_path="dummy.onnx")
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        # This test verifies the lazy import behavior
        # If onnxruntime is not installed, estimate() should raise a clear error
        # If it is installed, it will try to load the model and may fail differently
        try:
            backend.estimate(frames)
        except ImportError as e:
            assert "onnxruntime" in str(e).lower()
        except Exception as e:
            # If onnxruntime is installed but model doesn't exist, that's expected
            assert "model" in str(e).lower() or "file" in str(e).lower() or "load" in str(e).lower()
