"""Tests for PoseEstimator protocol, SyntheticBackend, and OnnxBackend."""

from __future__ import annotations

import builtins
import importlib.util
import tempfile
from pathlib import Path

import numpy as np
import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
from aimation_actor_core.infrastructure.ai_models.estimators import (
    COCO17_LABELS,
    OnnxBackend,
    PoseEstimator,
    SyntheticBackend,
)

_NUM_KEYPOINTS: int = 17


# ---------------------------------------------------------------------------
# SyntheticBackend
# ---------------------------------------------------------------------------


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
        frames: list[np.ndarray] = []

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


# ---------------------------------------------------------------------------
# OnnxBackend — unit tests (no real model needed)
# ---------------------------------------------------------------------------


def _build_trivial_onnx(path: Path) -> None:
    """Build a minimal ONNX model for testing.

    The model accepts [1, 3, 256, 192] float32 and returns two outputs
    ``simcc_x`` [1, 17, 384] and ``simcc_y`` [1, 17, 512] — matching
    RTMPose-S SimCC layout.  The conv weights are random; the model exists
    solely to exercise the preprocessing → session → decode path.
    """
    try:
        import onnx
        from onnx import TensorProto, helper
    except ImportError:
        pytest.skip("onnx python package not installed; cannot build fake model")

    input_tensor = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 256, 192])
    out_x = helper.make_tensor_value_info("simcc_x", TensorProto.FLOAT, [1, 17, 384])
    out_y = helper.make_tensor_value_info("simcc_y", TensorProto.FLOAT, [1, 17, 512])

    # A trivial Conv that maps 3→17 channels (spatial dims preserved with
    # padding) followed by Reshape to produce the SimCC shapes.
    # Conv: 3→17, kernel 1×1, padding 0 → output [1,17,256,192]
    w_init = helper.make_tensor(
        "conv_w", TensorProto.FLOAT, [17, 3, 1, 1], np.random.randn(17, 3, 1, 1).tolist()
    )
    b_init = helper.make_tensor("conv_b", TensorProto.FLOAT, [17], np.zeros(17).tolist())
    conv_node = helper.make_node("Conv", ["input", "conv_w", "conv_b"], ["conv_out"])

    # Reshape conv_out [1,17,256,192] → [1,17,384] for simcc_x
    shape_x = helper.make_tensor("shape_x", TensorProto.INT64, [3], [1, 17, 384])
    reshape_x = helper.make_node("Reshape", ["conv_out", "shape_x"], ["simcc_x"])

    # Reshape conv_out [1,17,256,192] → [1,17,512] for simcc_y
    shape_y = helper.make_tensor("shape_y", TensorProto.INT64, [3], [1, 17, 512])
    reshape_y = helper.make_node("Reshape", ["conv_out", "shape_y"], ["simcc_y"])

    graph = helper.make_graph(
        [conv_node, reshape_x, reshape_y],
        "trivial_pose",
        [input_tensor],
        [out_x, out_y],
        initializer=[w_init, b_init, shape_x, shape_y],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


class TestOnnxBackend:
    """Test OnnxBackend implementation."""

    def test_implements_protocol(self) -> None:
        """Should implement PoseEstimator protocol."""
        backend = OnnxBackend(model_path="dummy.onnx")
        assert isinstance(backend, PoseEstimator)

    def test_estimate_without_onnxruntime_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should raise a clear ImportError when onnxruntime is unavailable.

        The lazy onnxruntime import is deterministically forced to fail by
        patching ``__import__``, so this test never passes vacuously and does
        not depend on whether onnxruntime happens to be installed.
        """
        backend = OnnxBackend(model_path="dummy.onnx")
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

    def test_missing_model_raises_file_not_found(self) -> None:
        """Should raise FileNotFoundError with install hint when model is absent."""
        backend = OnnxBackend(model_path="/nonexistent/path/model.onnx")
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        with pytest.raises(FileNotFoundError) as exc_info:
            backend.estimate(frames)

        assert "aimation-models install" in str(exc_info.value).lower()

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    @pytest.mark.skipif(
        importlib.util.find_spec("onnx") is None,
        reason="onnx python package not installed",
    )
    def test_estimate_with_fake_model(self, tmp_path: Path) -> None:
        """Should return correct structure from a trivial ONNX model.

        Uses a fake 1×3×256×192 → simcc_x[1,17,384] + simcc_y[1,17,512]
        model to exercise the full preprocess → infer → decode pipeline.
        """
        model_path = tmp_path / "fake_pose.onnx"
        _build_trivial_onnx(model_path)

        backend = OnnxBackend(model_path=model_path)
        frames = [
            np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8),
            np.random.randint(0, 255, (360, 480, 3), dtype=np.uint8),
        ]

        result = backend.estimate(frames)

        # One Keypoints2D per frame
        assert len(result) == 2
        for kp2d in result:
            assert isinstance(kp2d, Keypoints2D)
            assert len(kp2d.keypoints) == _NUM_KEYPOINTS

            for kp in kp2d.keypoints:
                assert kp.label in COCO17_LABELS
                assert 0.0 <= kp.x <= 1.0
                assert 0.0 <= kp.y <= 1.0
                assert 0.0 <= kp.confidence <= 1.0

        # Labels match COCO-17 order
        for k, expected_label in enumerate(COCO17_LABELS):
            assert result[0].keypoints[k].label == expected_label

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    @pytest.mark.skipif(
        importlib.util.find_spec("onnx") is None,
        reason="onnx python package not installed",
    )
    def test_estimate_empty_frames(self, tmp_path: Path) -> None:
        """Should return empty list when no frames are given."""
        model_path = tmp_path / "fake_pose.onnx"
        _build_trivial_onnx(model_path)

        backend = OnnxBackend(model_path=model_path)
        result = backend.estimate([])

        assert result == []

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    def test_from_registry_missing_manifest_raises(self) -> None:
        """from_registry should surface a missing manifest as an error."""
        from aimation_actor_core.infrastructure.models.registry import (
            ModelManifestError,
            ModelRegistry,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            registry = ModelRegistry(root=Path(tmp_dir))
            with pytest.raises(ModelManifestError):
                OnnxBackend.from_registry(registry)
