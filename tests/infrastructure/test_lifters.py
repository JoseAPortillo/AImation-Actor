"""Tests for 3D lifting backends (REQ-2)."""

import builtins
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.infrastructure.ai_models.lifters import (
    MOTIONBERT_H36M_LABELS,
    HeuristicLiftingBackend,
    LiftingBackend,
    OnnxLiftingBackend,
    SyntheticLiftingBackend,
    _build_h36m_frame,
    _crop_scale_motion,
    _map_z_to_domain,
)

#: Whether onnxruntime (required to construct ``OnnxLiftingBackend``) is present.
ONNXRUNTIME_MISSING = importlib.util.find_spec("onnxruntime") is None

#: Whether both onnxruntime AND the onnx builder (required for the fake-model
#: end-to-end tests) are present.
ONNX_DEPS_MISSING = ONNXRUNTIME_MISSING or importlib.util.find_spec("onnx") is None

# 17 COCO labels with normalized (x, y) for a standing person (pose-2d's
# FIXED_KEYPOINTS shape), all at confidence 0.95.
STANDING_POSE: list[tuple[str, float, float]] = [
    ("nose", 0.50, 0.20),
    ("left_eye", 0.48, 0.18),
    ("right_eye", 0.52, 0.18),
    ("left_ear", 0.45, 0.20),
    ("right_ear", 0.55, 0.20),
    ("left_shoulder", 0.40, 0.35),
    ("right_shoulder", 0.60, 0.35),
    ("left_elbow", 0.35, 0.50),
    ("right_elbow", 0.65, 0.50),
    ("left_wrist", 0.30, 0.65),
    ("right_wrist", 0.70, 0.65),
    ("left_hip", 0.45, 0.60),
    ("right_hip", 0.55, 0.60),
    ("left_knee", 0.45, 0.75),
    ("right_knee", 0.55, 0.75),
    ("left_ankle", 0.45, 0.90),
    ("right_ankle", 0.55, 0.90),
]


def _frame(frame_index: int = 0) -> Keypoints2D:
    """Build a full standing-pose Keypoints2D frame."""
    return Keypoints2D(
        frame_index=frame_index,
        keypoints=[
            Keypoint(label=label, x=x, y=y, confidence=0.95) for (label, x, y) in STANDING_POSE
        ],
    )


def _pose_with_shoulders(shoulder_dx: float, frame_index: int = 0) -> Keypoints2D:
    """Build a pose whose shoulder separation is ``shoulder_dx``."""
    center = 0.5
    return Keypoints2D(
        frame_index=frame_index,
        keypoints=[
            Keypoint(label="left_shoulder", x=center - shoulder_dx / 2, y=0.35, confidence=0.95),
            Keypoint(label="right_shoulder", x=center + shoulder_dx / 2, y=0.35, confidence=0.95),
            Keypoint(label="left_ankle", x=0.45, y=0.90, confidence=0.95),
            Keypoint(label="right_ankle", x=0.55, y=0.90, confidence=0.95),
        ],
    )


class TestSyntheticLiftingBackend:
    """Test SyntheticLiftingBackend (REQ-2)."""

    def test_implements_protocol(self) -> None:
        """Should implement the LiftingBackend protocol."""
        backend = SyntheticLiftingBackend()
        assert isinstance(backend, LiftingBackend)

    def test_z_table_head_and_torso_on_camera_plane(self) -> None:
        """Should place head/torso joints on the camera plane (z == 0.5)."""
        backend = SyntheticLiftingBackend()
        result = backend.lift([_frame()])
        z_by_label = {kp.label: kp.z for kp in result[0].keypoints}
        for label in (
            "nose",
            "left_eye",
            "right_eye",
            "left_shoulder",
            "right_shoulder",
            "left_hip",
        ):
            assert z_by_label[label] == 0.5

    def test_z_table_extremities_in_range(self) -> None:
        """Should place wrists/ankles in the documented 0.55-0.65 deviation band."""
        backend = SyntheticLiftingBackend()
        result = backend.lift([_frame()])
        z_by_label = {kp.label: kp.z for kp in result[0].keypoints}
        for label in ("left_wrist", "right_wrist", "left_ankle", "right_ankle"):
            assert 0.55 <= z_by_label[label] <= 0.65
            assert z_by_label[label] > 0.5

    def test_deterministic_across_runs(self) -> None:
        """Should produce identical output for identical input (determinism)."""
        backend = SyntheticLiftingBackend()
        run1 = backend.lift([_frame(0), _frame(1)])
        run2 = backend.lift([_frame(0), _frame(1)])
        assert len(run1) == len(run2)
        for seq1, seq2 in zip(run1, run2, strict=True):
            assert seq1.frame_index == seq2.frame_index
            assert len(seq1.keypoints) == len(seq2.keypoints)
            for kp1, kp2 in zip(seq1.keypoints, seq2.keypoints, strict=True):
                assert kp1.label == kp2.label
                assert kp1.x == kp2.x
                assert kp1.y == kp2.y
                assert kp1.z == kp2.z
                assert kp1.confidence == kp2.confidence
                assert kp1.visible == kp2.visible

    def test_output_fields(self) -> None:
        """Should set confidence 0.95, visible True, and preserve x/y geometry."""
        backend = SyntheticLiftingBackend()
        result = backend.lift([_frame()])
        for kp in result[0].keypoints:
            assert kp.confidence == 0.95
            assert kp.visible is True
        assert result[0].keypoints[0].x == 0.50
        assert result[0].keypoints[0].y == 0.20

    def test_frame_index_preserved(self) -> None:
        """Should preserve the input frame_index on each output frame."""
        backend = SyntheticLiftingBackend()
        result = backend.lift([_frame(0), _frame(3), _frame(9)])
        assert [seq.frame_index for seq in result] == [0, 3, 9]

    def test_unknown_label_defaults_to_camera_plane(self) -> None:
        """Should default labels outside the z-table to z == 0.5."""
        frame = Keypoints2D(
            frame_index=0,
            keypoints=[Keypoint(label="custom_joint", x=0.5, y=0.5, confidence=0.5)],
        )
        result = SyntheticLiftingBackend().lift([frame])
        assert result[0].keypoints[0].z == 0.5
        assert result[0].keypoints[0].confidence == 0.95

    def test_depth_mode_flat_zeroes_deviation(self) -> None:
        """Should multiply deviation by 0 in 'flat' mode (all z == 0.5)."""
        backend = SyntheticLiftingBackend(depth_mode="flat")
        result = backend.lift([_frame()])
        assert all(kp.z == 0.5 for kp in result[0].keypoints)

    def test_unknown_depth_mode_falls_back_to_default(self) -> None:
        """Should treat an unknown depth_mode as the default (proportional)."""
        default = SyntheticLiftingBackend().lift([_frame()])
        unknown = SyntheticLiftingBackend(depth_mode="bogus-mode").lift([_frame()])
        assert [kp.z for kp in default[0].keypoints] == [kp.z for kp in unknown[0].keypoints]

    def test_empty_input_returns_empty_list(self) -> None:
        """Should return [] for empty input without erroring."""
        assert SyntheticLiftingBackend().lift([]) == []

    def test_output_is_json_serializable(self) -> None:
        """Should produce JSON-serializable Keypoints3D (no numpy values)."""
        result = SyntheticLiftingBackend().lift([_frame()])
        assert '"z"' in result[0].model_dump_json()
        assert result[0].model_dump_json()


class TestHeuristicLiftingBackend:
    """Test HeuristicLiftingBackend (REQ-2)."""

    def test_implements_protocol(self) -> None:
        """Should implement the LiftingBackend protocol."""
        backend = HeuristicLiftingBackend()
        assert isinstance(backend, LiftingBackend)

    def test_deterministic_across_runs(self) -> None:
        """Should produce identical output for identical input (determinism)."""
        backend = HeuristicLiftingBackend()
        run1 = backend.lift([_frame(0)])
        run2 = backend.lift([_frame(0)])
        assert len(run1) == len(run2)
        for seq1, seq2 in zip(run1, run2, strict=True):
            assert seq1.frame_index == seq2.frame_index
            for kp1, kp2 in zip(seq1.keypoints, seq2.keypoints, strict=True):
                assert kp1.label == kp2.label
                assert kp1.x == kp2.x
                assert kp1.y == kp2.y
                assert kp1.z == kp2.z
                assert kp1.confidence == kp2.confidence

    def test_z_varies_with_person_scale(self) -> None:
        """Should produce different z for the same joint at different scales."""
        backend = HeuristicLiftingBackend()
        wide = backend.lift([_pose_with_shoulders(shoulder_dx=0.9)])[0]
        narrow = backend.lift([_pose_with_shoulders(shoulder_dx=0.1)])[0]
        z_by_label = {kp.label: kp.z for kp in wide.keypoints}
        z_wide = z_by_label["left_ankle"]
        z_narrow = {kp.label: kp.z for kp in narrow.keypoints}["left_ankle"]
        # A wider person at the same y produces a larger depth deviation.
        assert z_wide > z_narrow

    def test_frame_index_preserved(self) -> None:
        """Should preserve the input frame_index."""
        result = HeuristicLiftingBackend().lift([_frame(4), _frame(8)])
        assert [seq.frame_index for seq in result] == [4, 8]

    def test_z_bounds_are_respected(self) -> None:
        """Should keep every z inside [0, 1] for extreme-but-valid geometry."""
        backend = HeuristicLiftingBackend()
        extreme = Keypoints2D(
            frame_index=0,
            keypoints=[
                # Shoulders at the image edges -> maximal scale.
                Keypoint(label="left_shoulder", x=0.0, y=0.0, confidence=0.5),
                Keypoint(label="right_shoulder", x=1.0, y=0.0, confidence=0.5),
                Keypoint(label="left_ankle", x=0.0, y=1.0, confidence=0.5),
            ],
        )
        for seq in backend.lift([extreme, _frame()]):
            assert all(0.0 <= kp.z <= 1.0 for kp in seq.keypoints)

    def test_bone_length_consistency_clamp(self) -> None:
        """Should clamp z-spread across a short bone to the 2D bone length.

        A nearly-degenerate elbow-wrist bone cannot stretch arbitrarily far
        in depth: |dz| must stay within 50% of the 2D bone length.
        """
        frame = Keypoints2D(
            frame_index=0,
            keypoints=[
                Keypoint(label="left_shoulder", x=0.4, y=0.35, confidence=0.95),
                Keypoint(label="right_shoulder", x=0.6, y=0.35, confidence=0.95),
                Keypoint(label="left_elbow", x=0.5, y=0.5, confidence=0.95),
                Keypoint(label="left_wrist", x=0.51, y=0.5, confidence=0.95),
            ],
        )
        result = HeuristicLiftingBackend().lift([frame])[0]
        z_by_label = {kp.label: kp.z for kp in result.keypoints}
        dz = z_by_label["left_wrist"] - z_by_label["left_elbow"]
        bone_2d = math.hypot(0.51 - 0.5, 0.5 - 0.5)
        # Unclamped priors differ by more than the clamp allows (0.03 > 0.005).
        assert dz <= 0.5 * bone_2d + 1e-9
        assert dz > 0.0

    def test_missing_labels_produce_empty_per_frame_never_crash(self) -> None:
        """Should return an empty per-frame Keypoints3D for a frame without labels."""
        frame = Keypoints2D(frame_index=7, keypoints=[])
        result = HeuristicLiftingBackend().lift([frame])
        assert len(result) == 1
        assert result[0].frame_index == 7
        assert result[0].keypoints == []

    def test_empty_input_returns_empty_list(self) -> None:
        """Should return [] for empty input without erroring."""
        assert HeuristicLiftingBackend().lift([]) == []

    def test_unknown_depth_mode_falls_back_to_default(self) -> None:
        """Should treat an unknown depth_mode as the default (proportional)."""
        default = HeuristicLiftingBackend().lift([_frame()])
        unknown = HeuristicLiftingBackend(depth_mode="bogus-mode").lift([_frame()])
        assert [kp.z for kp in default[0].keypoints] == [kp.z for kp in unknown[0].keypoints]

    def test_output_is_json_serializable(self) -> None:
        """Should produce JSON-serializable Keypoints3D (no numpy values)."""
        result = HeuristicLiftingBackend().lift([_frame()])
        assert '"z"' in result[0].model_dump_json()
        assert result[0].model_dump_json()


def _build_trivial_lifting_onnx(path: Path) -> None:
    """Build a minimal MotionBERT-shaped ONNX model (Identity).

    Input ``keypoints_2d`` and output ``keypoints_3d`` share the dynamic
    shape (1, frames, 17, 3) float32 and the model returns its input verbatim,
    so the backend's z channel receives the confidence column (untouched by
    ``crop_scale``). Exercises the full preprocess -> session -> postprocess
    path without real weights.
    """
    try:
        import onnx
        from onnx import TensorProto, helper
    except ImportError:
        pytest.skip("onnx python package not installed; cannot build fake model")

    input_tensor = helper.make_tensor_value_info(
        "keypoints_2d", TensorProto.FLOAT, [1, "frames", 17, 3]
    )
    output_tensor = helper.make_tensor_value_info(
        "keypoints_3d", TensorProto.FLOAT, [1, "frames", 17, 3]
    )
    identity = helper.make_node("Identity", ["keypoints_2d"], ["keypoints_3d"])
    graph = helper.make_graph(
        [identity], "trivial_lifting", [input_tensor], [output_tensor]
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


class TestMotionBertPreprocessing:
    """Pure-function tests for the MotionBERT input/output mapping.

    No onnxruntime needed: these cover the COCO->H36M conversion, the
    ``crop_scale`` normalization, and the z -> domain mapping in isolation.
    """

    def _index(self) -> dict[str, int]:
        """H36M label -> row index map."""
        return {label: index for index, label in enumerate(MOTIONBERT_H36M_LABELS)}

    def test_build_h36m_frame_shape_and_midpoint_synthesis(self) -> None:
        """Should produce a (17, 3) float32 frame with synthesized midpoints."""
        frame = _build_h36m_frame(_frame().keypoints)
        assert frame.shape == (17, 3)
        assert frame.dtype == np.float32
        idx = self._index()
        # root = mid-hip, neck = mid-shoulder, belly = mid(root, neck).
        np.testing.assert_allclose(frame[idx["root"]], [0.5, 0.6, 0.95])
        np.testing.assert_allclose(frame[idx["neck"]], [0.5, 0.35, 0.95])
        np.testing.assert_allclose(frame[idx["belly"]], [0.5, 0.475, 0.95])
        # head = mid(nose, ears): ears mid = (0.5, 0.20) -> head = (0.5, 0.20).
        np.testing.assert_allclose(frame[idx["head"]], [0.5, 0.2, 0.95])
        # Direct joints are copied 1:1 with their confidence.
        np.testing.assert_allclose(frame[idx["nose"]], [0.5, 0.2, 0.95])
        np.testing.assert_allclose(frame[idx["left_ankle"]], [0.45, 0.9, 0.95])

    def test_build_h36m_frame_missing_sources_are_absent(self) -> None:
        """Should zero synthesized joints whose sources are missing/uncertain."""
        idx = self._index()
        # Only one hip: root requires both -> absent (confidence 0).
        one_sided = Keypoints2D(
            frame_index=0,
            keypoints=[
                Keypoint(label="left_hip", x=0.45, y=0.60, confidence=0.95),
                Keypoint(label="left_shoulder", x=0.40, y=0.35, confidence=0.95),
                Keypoint(label="right_shoulder", x=0.60, y=0.35, confidence=0.95),
            ],
        )
        frame = _build_h36m_frame(one_sided.keypoints)
        assert frame[idx["root"]][2] == 0.0
        assert frame[idx["belly"]][2] == 0.0
        # Both shoulders present -> neck synthesizes normally.
        assert frame[idx["neck"]][2] == pytest.approx(0.95)
        # A zero-confidence direct joint is NOT copied (absent, not garbage).
        sparse = Keypoints2D(
            frame_index=0,
            keypoints=[
                Keypoint(label="nose", x=0.5, y=0.2, confidence=0.0),
                Keypoint(label="left_shoulder", x=0.4, y=0.35, confidence=0.95),
                Keypoint(label="right_shoulder", x=0.6, y=0.35, confidence=0.95),
                Keypoint(label="left_ankle", x=0.45, y=0.9, confidence=0.95),
                Keypoint(label="right_ankle", x=0.55, y=0.9, confidence=0.95),
            ],
        )
        frame2 = _build_h36m_frame(sparse.keypoints)
        assert frame2[idx["nose"]][2] == 0.0
        assert frame2[idx["left_ankle"]][2] == pytest.approx(0.95)

    def test_crop_scale_motion_normalizes_and_is_deterministic(self) -> None:
        """Should center on the bbox, map to [-1, 1], and stay deterministic."""
        motion = np.stack([_build_h36m_frame(_frame().keypoints) for _ in range(2)])
        normalized, scale = _crop_scale_motion(motion)
        assert normalized.shape == (2, 17, 3)
        # y extent 0.20..0.90 dominates (eyes at 0.18 have no H36M row, so the
        # model-side bbox starts at the nose/ears row).
        assert scale == pytest.approx(0.70)
        # Vertical extent maps to [-1, 1]; the narrower x span to +/-4/7.
        ys = normalized[0, :, 1]
        assert ys.min() == pytest.approx(-1.0, abs=1e-6)
        assert ys.max() == pytest.approx(1.0, abs=1e-6)
        xs = normalized[0, :, 0]
        assert xs.min() == pytest.approx(-4.0 / 7.0, abs=1e-6)
        assert xs.max() == pytest.approx(4.0 / 7.0, abs=1e-6)
        # Confidence column is untouched by the coordinate normalization.
        np.testing.assert_allclose(normalized[0, :, 2], 0.95)
        # Deterministic across calls.
        normalized2, scale2 = _crop_scale_motion(motion)
        np.testing.assert_array_equal(normalized, normalized2)
        assert scale == scale2

    def test_crop_scale_motion_zeroes_confidence_zero_rows(self) -> None:
        """Should zero entire rows whose input confidence is 0."""
        keypoints = [
            Keypoint(
                label=label,
                x=x,
                y=y,
                confidence=0.0 if label == "left_ankle" else 0.95,
            )
            for (label, x, y) in STANDING_POSE
        ]
        motion = _build_h36m_frame(keypoints)[np.newaxis, ...]
        normalized, scale = _crop_scale_motion(motion)
        assert scale == pytest.approx(0.70)
        idx = self._index()
        np.testing.assert_array_equal(normalized[0, idx["left_ankle"]], [0, 0, 0])
        # The zero-confidence joint no longer participates in the bbox.
        np.testing.assert_allclose(
            normalized[0, idx["right_ankle"]], [1.0 / 7.0, 1.0, 0.95], rtol=1e-5
        )

    def test_crop_scale_motion_requires_four_valid_joints(self) -> None:
        """Should return scale 0.0 (and zeros) with fewer than 4 valid joints."""
        motion = np.zeros((1, 17, 3), dtype=np.float32)
        motion[0, :3, :] = 1.0  # only 3 valid rows
        normalized, scale = _crop_scale_motion(motion)
        assert scale == 0.0
        assert np.count_nonzero(normalized) == 0

    def test_map_z_to_domain_root_relative_and_scaled(self) -> None:
        """Should express z around 0.5 in image units and clamp to [0, 1]."""
        z_model = np.asarray([[0.0, 0.2, -0.2]], dtype=np.float32)
        z_root = np.asarray([[0.0]], dtype=np.float32)
        z_domain = _map_z_to_domain(z_model, z_root, scale=0.5)
        # z_scale = 2/0.5 = 4: 0.2 model units -> 0.05 image units.
        np.testing.assert_allclose(z_domain[0], [0.5, 0.55, 0.45])
        # Clamped into [0, 1].
        huge = _map_z_to_domain(
            np.asarray([[5.0]], dtype=np.float32), np.zeros((1, 1)), scale=0.5
        )
        assert huge[0, 0] == 1.0


class TestOnnxLiftingBackend:
    """Test the MotionBERT ONNX backend (REQ-2).

    Constructing the backend requires onnxruntime to be importable; the import
    seam itself is covered below via a monkeypatched ``__import__``.
    """

    def test_construction_without_onnxruntime_raises_clear_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should raise a clear ImportError when onnxruntime is unavailable.

        The lazy onnxruntime import is deterministically forced to fail by
        patching ``__import__``, so this test never passes vacuously and does
        not depend on whether onnxruntime happens to be installed.
        """
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
            OnnxLiftingBackend(model_path="dummy.onnx")

        assert "onnxruntime" in str(exc_info.value).lower()

    @pytest.mark.skipif(ONNXRUNTIME_MISSING, reason="onnxruntime not installed")
    def test_implements_protocol(self) -> None:
        """Should implement the LiftingBackend protocol."""
        backend = OnnxLiftingBackend(model_path="dummy.onnx")
        assert isinstance(backend, LiftingBackend)

    @pytest.mark.skipif(ONNXRUNTIME_MISSING, reason="onnxruntime not installed")
    def test_empty_input_returns_empty_list_without_loading_model(self) -> None:
        """Should short-circuit [] before touching the model file."""
        backend = OnnxLiftingBackend(model_path="does-not-exist.onnx")
        assert backend.lift([]) == []

    @pytest.mark.skipif(ONNXRUNTIME_MISSING, reason="onnxruntime not installed")
    def test_missing_model_raises_file_not_found_with_install_hint(self) -> None:
        """Should raise FileNotFoundError with an exporter hint for missing models."""
        backend = OnnxLiftingBackend(model_path="does-not-exist.onnx")
        with pytest.raises(FileNotFoundError) as exc_info:
            backend.lift([_frame()])
        message = str(exc_info.value)
        assert "does-not-exist.onnx" in message
        assert "export_motionbert_onnx" in message

    @pytest.mark.skipif(ONNXRUNTIME_MISSING, reason="onnxruntime not installed")
    def test_from_registry_resolves_motionbert_entry(self) -> None:
        """Should point at the manifest's motionbert model without touching binaries."""
        from aimation_actor_core.infrastructure.models.registry import ModelRegistry

        backend = OnnxLiftingBackend.from_registry(ModelRegistry(root=Path("models")))
        assert isinstance(backend, OnnxLiftingBackend)
        assert backend.model_path.name == "motionbert.onnx"

    @pytest.mark.skipif(ONNXRUNTIME_MISSING, reason="onnxruntime not installed")
    def test_from_registry_missing_manifest_raises(self, tmp_path: Path) -> None:
        """Should raise ModelManifestError when no manifest exists."""
        from aimation_actor_core.infrastructure.models.registry import (
            ModelManifestError,
            ModelRegistry,
        )

        with pytest.raises(ModelManifestError):
            OnnxLiftingBackend.from_registry(ModelRegistry(root=tmp_path))

    @pytest.mark.skipif(ONNX_DEPS_MISSING, reason="onnxruntime/onnx not installed")
    def test_lift_with_trivial_onnx_model(self, tmp_path: Path) -> None:
        """Should run preprocess -> session -> postprocess and emit domain frames.

        The fake model echoes its input, so the z channel reaching the output
        mapping is the confidence column: a joint with a deviating confidence
        lifts off the camera plane exactly as
        ``0.5 + (conf - root_conf) / z_scale`` with ``z_scale = 2 / scale``.
        """
        model_path = tmp_path / "motionbert.onnx"
        _build_trivial_lifting_onnx(model_path)
        backend = OnnxLiftingBackend(model_path=model_path)

        valid = Keypoints2D(
            frame_index=0,
            keypoints=[
                Keypoint(
                    label=label,
                    x=x,
                    y=y,
                    confidence=0.80 if label == "nose" else 0.95,
                )
                for (label, x, y) in STANDING_POSE
            ],
        )
        zero_ankle = Keypoints2D(
            frame_index=2,
            keypoints=[
                Keypoint(
                    label=label,
                    x=x,
                    y=y,
                    confidence=0.0 if label == "left_ankle" else 0.95,
                )
                for (label, x, y) in STANDING_POSE
            ],
        )
        empty = Keypoints2D(frame_index=5, keypoints=[])
        result = backend.lift([valid, zero_ankle, empty])

        assert [seq.frame_index for seq in result] == [0, 2, 5]
        # An empty input frame degrades to an empty output frame, never crashes.
        assert result[2].keypoints == []

        first = result[0]
        assert len(first.keypoints) == 17
        assert [kp.label for kp in first.keypoints] == [label for label, _, _ in STANDING_POSE]
        by_label = {kp.label: kp for kp in first.keypoints}
        # Standing-pose bbox y extent over the H36M rows (eyes excluded):
        # 0.20 (nose/ears) .. 0.90 (ankles).
        scale = 0.70
        # nose deviates from the 0.95 root confidence -> off the camera plane.
        expected_nose_z = 0.5 + (0.80 - 0.95) / (2.0 / scale)
        assert by_label["nose"].z == pytest.approx(expected_nose_z)
        # Joints sharing the root confidence (incl. the mid-hip root row) sit
        # on the camera plane; COCO joints without an H36M row (eyes) too.
        assert by_label["left_hip"].z == pytest.approx(0.5)
        assert by_label["left_eye"].z == 0.5
        # Geometry, confidence and JSON-serializability survive the round trip.
        for kp in first.keypoints:
            assert 0.0 <= kp.z <= 1.0
            assert kp.confidence in (0.80, 0.95)
        assert '"z"' in first.model_dump_json()

        # Zero-confidence joint: camera plane + not visible; x/y preserved.
        zero = {kp.label: kp for kp in result[1].keypoints}["left_ankle"]
        assert zero.z == 0.5
        assert zero.visible is False
        assert zero.x == 0.45
        assert zero.y == 0.90

    @pytest.mark.skipif(ONNX_DEPS_MISSING, reason="onnxruntime/onnx not installed")
    def test_lift_stays_on_camera_plane_when_sequence_cannot_be_normalized(
        self, tmp_path: Path
    ) -> None:
        """Should skip inference and keep z = 0.5 when fewer than 4 valid joints."""
        model_path = tmp_path / "motionbert.onnx"
        _build_trivial_lifting_onnx(model_path)
        backend = OnnxLiftingBackend(model_path=model_path)
        # Only both shoulders: after H36M synthesis (neck) just 3 rows are
        # valid — below the crop-scale requirement of 4.
        sparse = Keypoints2D(
            frame_index=0,
            keypoints=[
                Keypoint(label="left_shoulder", x=0.4, y=0.35, confidence=0.9),
                Keypoint(label="right_shoulder", x=0.6, y=0.35, confidence=0.9),
            ],
        )
        result = backend.lift([sparse])
        assert len(result) == 1
        assert result[0].frame_index == 0
        assert all(kp.z == 0.5 for kp in result[0].keypoints)
        assert all(kp.visible for kp in result[0].keypoints)
        assert all(kp.confidence == 0.9 for kp in result[0].keypoints)
