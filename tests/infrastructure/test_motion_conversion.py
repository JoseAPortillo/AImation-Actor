"""Tests for Keypoints3D → NeutralMotion conversion (REQ-1).

The converter is pure deterministic math: normalized [0,1] → scene cm via the
person-height heuristic (default 172 cm, overridable), image y-down → scene
up-Y flip, abs→local offsets, identity rotation, and 0→1 frame numbering.
Designed so every real assertion would FAIL if the conversion logic were
wrong.
"""

from __future__ import annotations

import json

import pytest

from aimation_actor_core.domain.animation.keypoints3d import Keypoint3D, Keypoints3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.infrastructure.ai_models.motion_conversion import (
    DEFAULT_PERSON_HEIGHT_CM,
    convert_keypoints_to_motion,
)


def _kp(label: str, x: float = 0.5, y: float = 0.5, z: float = 0.5, c: float = 0.9) -> Keypoint3D:
    return Keypoint3D(label=label, x=x, y=y, z=z, confidence=c)


def _frame(frame_index: int = 0, keypoints: list[Keypoint3D] | None = None) -> Keypoints3D:
    return Keypoints3D(frame_index=frame_index, keypoints=keypoints or [])


def _standing_frame() -> Keypoints3D:
    """A full synthetic standing pose mirroring the estimator COCO labels."""
    return Keypoints3D(
        frame_index=0,
        keypoints=[
            _kp("nose", x=0.5, y=0.2),
            _kp("left_eye", x=0.48, y=0.18),
            _kp("right_eye", x=0.52, y=0.18),
            _kp("left_ear", x=0.45, y=0.20),
            _kp("right_ear", x=0.55, y=0.20),
            _kp("left_shoulder", x=0.40, y=0.35),
            _kp("right_shoulder", x=0.60, y=0.35),
            _kp("left_elbow", x=0.35, y=0.50),
            _kp("right_elbow", x=0.65, y=0.50),
            _kp("left_wrist", x=0.30, y=0.65),
            _kp("right_wrist", x=0.70, y=0.65),
            _kp("left_hip", x=0.45, y=0.60),
            _kp("right_hip", x=0.55, y=0.60),
            _kp("left_knee", x=0.45, y=0.75),
            _kp("right_knee", x=0.55, y=0.75),
            _kp("left_ankle", x=0.45, y=0.90),
            _kp("right_ankle", x=0.55, y=0.90),
        ],
    )


class TestScale:
    """Person-height scaling (default 172, override proportional)."""

    def test_default_scale_multiplies_by_172(self) -> None:
        """abs = normalized × 172 (scene cm), inspected via only_local=False."""
        motion = convert_keypoints_to_motion(
            [_frame(keypoints=[_kp("left_shoulder", x=0.4, y=0.35, z=0.5)])],
            only_local=False,
        )
        trans = motion.frames[0].pose.transforms["LShoulder"].translation
        assert trans[0] == pytest.approx(0.4 * DEFAULT_PERSON_HEIGHT_CM)
        assert trans[1] == pytest.approx((1.0 - 0.35) * DEFAULT_PERSON_HEIGHT_CM)
        assert trans[2] == pytest.approx(0.5 * DEFAULT_PERSON_HEIGHT_CM)

    def test_override_185_scales_proportionally_not_absolutely(self) -> None:
        """Override must scale by the ratio 185/172, not by an absolute."""
        frame = _frame(keypoints=[_kp("right_wrist", x=0.7, y=0.65, z=0.6)])
        default = convert_keypoints_to_motion([frame], only_local=False)
        override = convert_keypoints_to_motion([frame], person_height_cm=185.0, only_local=False)
        d = default.frames[0].pose.transforms["RForeArm"].translation
        o = override.frames[0].pose.transforms["RForeArm"].translation
        ratio = 185.0 / DEFAULT_PERSON_HEIGHT_CM
        assert o[0] == pytest.approx(d[0] * ratio)
        assert o[1] == pytest.approx(d[1] * ratio)
        assert o[2] == pytest.approx(d[2] * ratio)
        # Sanity: the override is NOT the default constant (not absolute).
        assert o[0] != pytest.approx(d[0])


class TestYFlip:
    """Image y-down → scene up-Y flip (nose above ankles)."""

    def test_nose_sits_above_ankles_in_scene(self) -> None:
        """With up-Y scene coords the head must be above the feet (flipped)."""
        motion = convert_keypoints_to_motion([_standing_frame()], only_local=False)
        head_y = motion.frames[0].pose.transforms["Head"].translation[1]
        lfoot_y = motion.frames[0].pose.transforms["LFoot"].translation[1]
        assert head_y > lfoot_y


class TestLocalOffsets:
    """Abs→local derivation."""

    def test_local_is_abs_child_minus_abs_parent(self) -> None:
        """local(LArm) = abs(LArm) − abs(LShoulder) along X with default only_local."""
        frame = _frame(
            keypoints=[
                _kp("left_shoulder", x=0.40, y=0.35),
                _kp("left_elbow", x=0.35, y=0.50),
            ]
        )
        motion = convert_keypoints_to_motion([frame])  # only_local=True default
        local = motion.frames[0].pose.transforms["LArm"].translation
        assert local[0] == pytest.approx((0.35 - 0.40) * DEFAULT_PERSON_HEIGHT_CM)
        assert local[1] == pytest.approx(((1.0 - 0.50) - (1.0 - 0.35)) * DEFAULT_PERSON_HEIGHT_CM)

    def test_only_local_false_leaves_absolute(self) -> None:
        """only_local=False returns absolute scene positions, not the diff."""
        frame = _frame(keypoints=[_kp("left_elbow", x=0.35, y=0.50)])
        motion = convert_keypoints_to_motion([frame], only_local=False)
        abs_x = motion.frames[0].pose.transforms["LArm"].translation[0]
        assert abs_x == pytest.approx(0.35 * DEFAULT_PERSON_HEIGHT_CM)

    def test_missing_parent_keeps_rest_offset(self) -> None:
        """A bone whose parent has no data keeps its neutral rest offset."""
        frame = _frame(keypoints=[_kp("nose", x=0.5, y=0.2)])
        motion = convert_keypoints_to_motion([frame])
        # 'Head' maps from nose, but its parent 'Neck' has no data → Head keeps rest.
        spine_trans = motion.frames[0].pose.transforms["Spine"].translation
        assert spine_trans == (0.0, 12.0, 0.0)  # rest offset preserved


class TestRotationsAndIdentity:
    """Identity rotation / scale on every bone."""

    def test_all_rotations_identity(self) -> None:
        """Every bone should carry the identity quaternion (IK deferred)."""
        motion = convert_keypoints_to_motion([_standing_frame()])
        for transform in motion.frames[0].pose.transforms.values():
            assert transform.rotation == (1.0, 0.0, 0.0, 0.0)

    def test_all_scales_identity(self) -> None:
        """Every bone should carry identity scale."""
        motion = convert_keypoints_to_motion([_standing_frame()])
        for transform in motion.frames[0].pose.transforms.values():
            assert transform.scale == (1.0, 1.0, 1.0)


class TestFrameNumbering:
    """0→1 base conversion."""

    def test_frame_index_zero_becomes_frame_one(self) -> None:
        """frame_index=0 → Frame.frame=1; time = frame/fps (24.0 default)."""
        motion = convert_keypoints_to_motion([_frame(frame_index=0)])
        assert [f.frame for f in motion.frames] == [1]
        assert motion.meta.fps == pytest.approx(24.0)
        assert motion.frames[0].time == pytest.approx(1 / 24.0)

    def test_two_frames_number_1_and_2(self) -> None:
        """Sequential input frames number 1 and 2 in order."""
        motion = convert_keypoints_to_motion([_frame(0), _frame(1)])
        assert [f.frame for f in motion.frames] == [1, 2]

    def test_duration_frames_equals_max_frame(self) -> None:
        """meta.duration_frames = max(frame) (2 for the two-frame clip)."""
        motion = convert_keypoints_to_motion([_frame(0), _frame(1)])
        assert motion.meta.duration_frames == 2


class TestConfidence:
    """Frame.confidence = mean joint confidence."""

    def test_confidence_is_mean_joint_confidence(self) -> None:
        """Frame confidence should be the mean of the frame keypoints."""
        frame = _frame(keypoints=[_kp("nose", c=0.8), _kp("left_shoulder", c=0.6)])
        motion = convert_keypoints_to_motion([frame])
        assert motion.frames[0].confidence == pytest.approx(0.7)

    def test_confidence_none_for_empty_frame(self) -> None:
        """A frame with no keypoints reports confidence None."""
        motion = convert_keypoints_to_motion([_frame()])
        assert motion.frames[0].confidence is None


class TestMissingAndInvalidLabels:
    """Missing/invalid labels never fail; the frame still assembles."""

    def test_unknown_label_is_skipped_and_frame_assembles(self) -> None:
        """An unknown label maps to no bone; valid bones still assemble 22 transforms."""
        frame = _frame(
            keypoints=[
                _kp("left_shoulder", x=0.4),
                _kp("left_big_toe", x=0.5),  # not in the mapping
            ]
        )
        motion = convert_keypoints_to_motion([frame])
        assert len(motion.frames) == 1
        pose = motion.frames[0].pose.transforms
        assert len(pose) == 22  # all neutral bones present; the unknown label is ignored
        # The mapped bone moved, the unmapped bone (e.g. Head) kept rest.
        assert (
            pose["LShoulder"].translation
            != DEFAULT_NEUTRAL_SKELETON.bones["LShoulder"].rest_position
        )
        assert pose["Head"].translation == DEFAULT_NEUTRAL_SKELETON.bones["Head"].rest_position


class TestEmptyInput:
    """Empty input → empty motion carrying the default skeleton."""

    def test_empty_input_returns_empty_motion_with_skeleton(self) -> None:
        """convert([]) must yield frames=[] but STILL carry DEFAULT_NEUTRAL_SKELETON."""
        motion = convert_keypoints_to_motion([])
        assert isinstance(motion, NeutralMotion)
        assert motion.frames == []
        assert motion.skeleton == DEFAULT_NEUTRAL_SKELETON
        # The empty motion with the real skeleton passes invariants (a bare
        # NeutralMotion() with an empty skeleton would raise HierarchyError).
        motion.validate_invariants()
        assert motion.meta.duration_frames == 0


class TestDeterminismAndSerde:
    """Pure deterministic behavior and JSON safety."""

    def test_deterministic_two_runs_identical(self) -> None:
        """Identical input must produce byte-identical output on two runs."""
        frames = [_standing_frame(), _frame(frame_index=1)]
        a = convert_keypoints_to_motion(frames)
        b = convert_keypoints_to_motion(frames)
        assert a.model_dump() == b.model_dump()

    def test_model_dump_json_is_serializable(self) -> None:
        """model_dump_json() must yield string-serializable JSON."""
        motion = convert_keypoints_to_motion([_standing_frame()])
        payload = motion.model_dump_json()
        parsed = json.loads(payload)
        assert parsed["meta"]["units"] == "cm"
        assert len(parsed["frames"]) == 1
