"""Tests for PoseEstimator protocol, SyntheticBackend, OnnxBackend, and TopDownOnnxBackend."""

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
    TopDownOnnxBackend,
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
    RTMPose-S SimCC layout.  Outputs are constant tensors routed through
    Identity nodes, so the model exercises the full preprocess → session →
    decode path without needing real weights.
    """
    try:
        import onnx
        from onnx import TensorProto, helper
    except ImportError:
        pytest.skip("onnx python package not installed; cannot build fake model")

    input_tensor = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 256, 192])
    out_x = helper.make_tensor_value_info("simcc_x", TensorProto.FLOAT, [1, 17, 384])
    out_y = helper.make_tensor_value_info("simcc_y", TensorProto.FLOAT, [1, 17, 512])

    # Constant tensors with the correct output shapes, routed through Identity.
    simcc_x_data = np.random.randn(1, 17, 384).astype(np.float32)
    simcc_x_init = helper.make_tensor(
        "simcc_x_data", TensorProto.FLOAT, [1, 17, 384], simcc_x_data.tolist()
    )
    id_x = helper.make_node("Identity", ["simcc_x_data"], ["simcc_x"])

    simcc_y_data = np.random.randn(1, 17, 512).astype(np.float32)
    simcc_y_init = helper.make_tensor(
        "simcc_y_data", TensorProto.FLOAT, [1, 17, 512], simcc_y_data.tolist()
    )
    id_y = helper.make_node("Identity", ["simcc_y_data"], ["simcc_y"])

    graph = helper.make_graph(
        [id_x, id_y],
        "trivial_pose",
        [input_tensor],
        [out_x, out_y],
        initializer=[simcc_x_init, simcc_y_init],
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


# ---------------------------------------------------------------------------
# TopDownOnnxBackend — unit tests (no real model needed)
# ---------------------------------------------------------------------------


class TestTopDownAffine:
    """Test TopDownAffine forward + inverse round-trip."""

    def test_compute_affine_output_shape(self) -> None:
        """Should produce a 2×3 affine matrix."""
        affine, scale, src_x, src_y = TopDownOnnxBackend._compute_affine(
            box_cx=200.0, box_cy=150.0, box_size=200.0
        )
        assert affine.shape == (2, 3)
        assert scale > 0
        assert isinstance(src_x, float)
        assert isinstance(src_y, float)

    def test_affine_maps_center_to_model_center(self) -> None:
        """The person centre should map to the model input centre."""
        cx, cy, size = 200.0, 150.0, 200.0
        affine, _, _, _ = TopDownOnnxBackend._compute_affine(cx, cy, size)
        # Apply forward affine to the person centre.
        pt = np.array([cx, cy, 1.0])
        model_pt = affine @ pt
        # Should be near (input_w/2, input_h/2) = (96, 128).
        assert abs(model_pt[0] - 96.0) < 0.01
        assert abs(model_pt[1] - 128.0) < 0.01

    def test_inverse_affine_round_trip(self) -> None:
        """Forward then inverse should recover the original point."""
        cx, cy, size = 300.0, 250.0, 150.0
        affine, _, _, _ = TopDownOnnxBackend._compute_affine(cx, cy, size)
        inv = TopDownOnnxBackend._inverse_affine(affine)

        # Pick an arbitrary point in source space.
        src_pt = np.array([280.0, 220.0])
        # Forward: source → model.
        src_h = np.array([src_pt[0], src_pt[1], 1.0])
        model_pt = affine @ src_h
        # Inverse: model → source.
        model_h = np.array([model_pt[0], model_pt[1], 1.0])
        recovered = inv @ model_h

        assert abs(recovered[0] - src_pt[0]) < 0.001
        assert abs(recovered[1] - src_pt[1]) < 0.001

    def test_warp_crop_output_shape(self) -> None:
        """Should produce (input_h, input_w, 3) uint8 crop."""
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        affine, _, _, _ = TopDownOnnxBackend._compute_affine(
            box_cx=320.0, box_cy=240.0, box_size=200.0
        )
        crop = TopDownOnnxBackend._warp_crop(frame, affine)
        assert crop.shape == (256, 192, 3)
        assert crop.dtype == np.uint8

    def test_affine_constants_match_mmpose(self) -> None:
        """Verify the mmpose pipeline.json constants are honoured."""
        # From pipeline.json: padding=1.25, image_size=[192, 256]
        # For a person with size=200px:
        #   scale = 200 × 1.25 / 200 = 1.25
        #   crop_w = 1.25 × 192 = 240
        #   crop_h = 1.25 × 256 = 320
        _, scale, src_x, src_y = TopDownOnnxBackend._compute_affine(
            box_cx=200.0, box_cy=150.0, box_size=200.0
        )
        assert scale == pytest.approx(1.25)
        # src_x = 200 - 1.25×192/2 = 200 - 120 = 80
        assert src_x == pytest.approx(80.0)
        # src_y = 150 - 1.25×256/2 = 150 - 160 = -10
        assert src_y == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# TopDownOnnxBackend — orchestration with fake models
# ---------------------------------------------------------------------------


def _build_fake_detector_onnx(path: Path) -> None:
    """Build a minimal ONNX model that mimics RTMDet-nano output layout.

    Accepts [1, 3, 320, 320] and returns:
        - dets: [1, 100, 5] — all zeros (no detections).
        - labels: [1, 100] — all zeros.
    """
    try:
        import onnx
        from onnx import TensorProto, helper
    except ImportError:
        pytest.skip("onnx python package not installed; cannot build fake model")

    input_tensor = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 320, 320])
    out_dets = helper.make_tensor_value_info("dets", TensorProto.FLOAT, [1, 100, 5])
    out_labels = helper.make_tensor_value_info("labels", TensorProto.INT64, [1, 100])

    # Constant tensors that produce zero outputs.
    dets_init = helper.make_tensor(
        "dets_zero", TensorProto.FLOAT, [1, 100, 5], np.zeros((1, 100, 5)).tolist()
    )
    labels_init = helper.make_tensor(
        "labels_zero", TensorProto.INT64, [1, 100], np.zeros((1, 100), dtype=np.int64).tolist()
    )

    # Identity nodes connect initializers to graph outputs.
    id_dets = helper.make_node("Identity", ["dets_zero"], ["dets"])
    id_labels = helper.make_node("Identity", ["labels_zero"], ["labels"])

    graph = helper.make_graph(
        [id_dets, id_labels],
        "fake_detector",
        [input_tensor],
        [out_dets, out_labels],
        initializer=[dets_init, labels_init],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


class TestTopDownOnnxBackend:
    """Test TopDownOnnxBackend orchestration with fake models."""

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    @pytest.mark.skipif(
        importlib.util.find_spec("onnx") is None,
        reason="onnx python package not installed",
    )
    def test_no_person_emits_zero_confidence(self, tmp_path: Path) -> None:
        """When detector returns no persons, should emit 17 zero-confidence keypoints."""
        # Build fake detector (returns all zeros → no detections).
        det_path = tmp_path / "rtmdet-nano.onnx"
        _build_fake_detector_onnx(det_path)
        # Use existing fake pose model.
        pose_path = tmp_path / "rtmpose.onnx"
        _build_trivial_onnx(pose_path)

        backend = TopDownOnnxBackend(
            detector_path=det_path,
            pose_path=pose_path,
        )
        frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(2)]
        result = backend.estimate(frames)

        assert len(result) == 2
        for kp2d in result:
            assert isinstance(kp2d, Keypoints2D)
            assert len(kp2d.keypoints) == _NUM_KEYPOINTS
            for kp in kp2d.keypoints:
                assert kp.confidence == 0.0
                assert kp.x == 0.0
                assert kp.y == 0.0

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    def test_implements_pose_estimator_protocol(self) -> None:
        """TopDownOnnxBackend should satisfy the PoseEstimator protocol."""
        backend = TopDownOnnxBackend()
        assert isinstance(backend, PoseEstimator)

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    @pytest.mark.skipif(
        importlib.util.find_spec("onnx") is None,
        reason="onnx python package not installed",
    )
    def test_with_person_detection(self, tmp_path: Path) -> None:
        """When a person is detected, should produce keypoints with valid range."""
        # Build fake detector that outputs one person detection.
        try:
            import onnx
            from onnx import TensorProto, helper
        except ImportError:
            pytest.skip("onnx python package not installed")

        det_path = tmp_path / "rtmdet-nano.onnx"
        input_tensor = helper.make_tensor_value_info(
            "input", TensorProto.FLOAT, [1, 3, 320, 320]
        )
        out_dets = helper.make_tensor_value_info("dets", TensorProto.FLOAT, [1, 100, 5])
        out_labels = helper.make_tensor_value_info("labels", TensorProto.INT64, [1, 100])

        # Build a dets tensor: one person at (50,50,250,350) with score=0.9.
        dets_data = np.zeros((1, 100, 5), dtype=np.float32)
        dets_data[0, 0] = [50.0, 50.0, 250.0, 350.0, 0.9]
        dets_init = helper.make_tensor(
            "dets_val", TensorProto.FLOAT, [1, 100, 5], dets_data.tolist()
        )
        labels_data = np.zeros((1, 100), dtype=np.int64)
        labels_data[0, 0] = 0  # person class
        labels_init = helper.make_tensor(
            "labels_val", TensorProto.INT64, [1, 100], labels_data.tolist()
        )

        # Identity nodes connect initializers to graph outputs.
        id_dets = helper.make_node("Identity", ["dets_val"], ["dets"])
        id_labels = helper.make_node("Identity", ["labels_val"], ["labels"])

        graph = helper.make_graph(
            [id_dets, id_labels],
            "fake_detector_with_person",
            [input_tensor],
            [out_dets, out_labels],
            initializer=[dets_init, labels_init],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
        model.ir_version = 8
        onnx.checker.check_model(model)
        onnx.save(model, str(det_path))

        pose_path = tmp_path / "rtmpose.onnx"
        _build_trivial_onnx(pose_path)

        backend = TopDownOnnxBackend(detector_path=det_path, pose_path=pose_path)
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = backend.estimate([frame])

        assert len(result) == 1
        kp2d = result[0]
        assert len(kp2d.keypoints) == _NUM_KEYPOINTS
        # With a detected person, keypoints should have been computed.
        # The fake pose model produces random-ish SimCC → non-zero coordinates.
        for kp in kp2d.keypoints:
            assert 0.0 <= kp.x <= 1.0
            assert 0.0 <= kp.y <= 1.0
            assert 0.0 <= kp.confidence <= 1.0

    def test_from_registry_construction(self) -> None:
        """from_registry should construct without touching binaries."""
        from aimation_actor_core.infrastructure.models.registry import ModelRegistry

        backend = TopDownOnnxBackend.from_registry(ModelRegistry(root=Path("models")))
        assert isinstance(backend, TopDownOnnxBackend)
        assert backend._detector_path is not None
        assert backend._detector_path.name == "rtmdet-nano.onnx"
        assert backend._pose_path is not None
        assert backend._pose_path.name == "rtmpose.onnx"
