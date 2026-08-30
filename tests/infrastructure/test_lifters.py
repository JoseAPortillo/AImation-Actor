"""Tests for 3D lifting backends (REQ-2)."""

import builtins
import importlib.util
import math

import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.infrastructure.ai_models.lifters import (
    HeuristicLiftingBackend,
    LiftingBackend,
    OnnxLiftingBackend,
    SyntheticLiftingBackend,
)

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


class TestOnnxLiftingBackend:
    """Test the lazy ONNX seam (REQ-2).

    Protocol conformance is not asserted here because constructing the backend
    requires onnxruntime to be importable; the import seam itself is covered
    below — ImportError via a monkeypatched ``__import__`` and the
    NotImplementedError placeholder via the single honest skip.
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

    @pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    )
    def test_lift_with_onnxruntime_raises_not_implemented(self) -> None:
        """Should raise NotImplementedError once onnxruntime is importable."""
        backend = OnnxLiftingBackend(model_path="dummy.onnx")
        with pytest.raises(NotImplementedError) as exc_info:
            backend.lift([_frame()])
        assert "not yet implemented" in str(exc_info.value).lower()
