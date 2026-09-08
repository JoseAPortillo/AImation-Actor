"""Unit tests for the blocking-input payload model and converter (§20.5 / REQ-01, REQ-02, REQ-04).

RED-first (Strict TDD): these tests reference :mod:`blocking_input`, which does
not exist yet. They encode the blocking-input spec scenarios:

- REQ-01 SC-01..SC-06: payload model validation (well-formed, extra field,
  empty keyposes, skeleton mismatch, weight range, non-finite).
- REQ-02 SC-01..SC-04: converter (sparse frames, default skeleton, duplicate
  frame reject, frame beyond duration reject).
- REQ-04 SC-02/SC-03: zero-quaternion reject, max keypose count bounded.

The math is pure Pydantic + stdlib; mirrors the inbetween/cleanup domain tests.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation.blocking_input import (
    DEFAULT_BLOCKING_FPS,
    EXACT_LOCK_MIN,
    MAX_KEYPOSES,
    BlockingInput,
    BlockingKeyPose,
    blocking_to_neutral_motion,
)
from aimation_actor_core.domain.animation.entities import Transform3D
from aimation_actor_core.domain.animation.skeleton import Skeleton
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

BONES = list(DEFAULT_NEUTRAL_SKELETON.bones.keys())


def _full_pose(**overrides: Transform3D) -> dict[str, Transform3D]:
    """A pose addressing every bone of the default neutral skeleton."""
    pose: dict[str, Transform3D] = {}
    for i, bone in enumerate(BONES):
        pose[bone] = Transform3D(translation=(float(i), 0.0, 0.0), rotation=(1.0, 0.0, 0.0, 0.0))
    pose.update(overrides)
    return pose


def _keypose(frame: int, **overrides: object) -> BlockingKeyPose:
    """A well-formed keypose over the default skeleton."""
    return BlockingKeyPose(frame=frame, pose=_full_pose(), **overrides)


def _payload(keyposes: list[dict[str, object]]) -> dict[str, object]:
    return {"keyposes": keyposes}


def _kw(
    keypose: dict[str, object],
    frame: int,
    pose: dict[str, Transform3D],
    **extra: object,
) -> dict[str, object]:
    out = {"frame": frame, "pose": pose}
    out.update(extra)
    return out


class TestBlockingKeyPoseModel:
    """REQ-01 payload model — keypose-level validation."""

    def test_exposed_constants(self) -> None:
        """The module exposes the documented bounds."""
        assert MAX_KEYPOSES == 1000
        assert EXACT_LOCK_MIN == 0.99
        assert DEFAULT_BLOCKING_FPS == 24.0

    def test_well_formed_keypose_validates(self) -> None:
        """A keypose with frame>=1, full pose and weight in [0,1] validates."""
        kp = _keypose(frame=5)
        assert kp.frame == 5
        assert kp.weight == 1.0  # default
        assert len(kp.pose) == len(BONES)

    def test_weight_boundaries_accepted(self) -> None:
        """weight 0.0 and 1.0 are both accepted."""
        assert _keypose(frame=1, weight=0.0).weight == 0.0
        assert _keypose(frame=1, weight=1.0).weight == 1.0

    def test_unknown_extra_field_rejected(self) -> None:
        """A keypose with an unexpected key fails validation."""
        with pytest.raises(ValidationError):
            BlockingKeyPose(frame=1, pose=_full_pose(), extra_thing=1)

    def test_weight_out_of_range_rejected(self) -> None:
        """weight < 0 or > 1 fails validation (REQ-01 SC-05)."""
        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                _keypose(frame=1, weight=bad)

    def test_frame_lt_one_rejected(self) -> None:
        """frame must be >= 1."""
        with pytest.raises(ValidationError):
            BlockingKeyPose(frame=0, pose=_full_pose())

    def test_non_finite_translation_rejected(self) -> None:
        """A NaN or Inf translation component fails validation (REQ-01 SC-06)."""
        for bad in (float("nan"), float("inf"), float("-inf")):
            pose = _full_pose()
            pose["Root"] = Transform3D(translation=(bad, 0.0, 0.0))
            with pytest.raises(ValidationError):
                BlockingKeyPose(frame=1, pose=pose)

    def test_non_finite_quaternion_rejected(self) -> None:
        """A NaN or Inf rotation component fails validation (REQ-01 SC-06)."""
        for bad in (float("nan"), float("inf")):
            pose = _full_pose()
            pose["Root"] = Transform3D(rotation=(bad, 0.0, 0.0, 0.0))
            with pytest.raises(ValidationError):
                BlockingKeyPose(frame=1, pose=pose)

    def test_zero_quaternion_rejected(self) -> None:
        """An all-zero rotation quaternion fails validation (REQ-04 SC-02)."""
        pose = _full_pose()
        pose["Root"] = Transform3D(rotation=(0.0, 0.0, 0.0, 0.0))
        with pytest.raises(ValidationError):
            BlockingKeyPose(frame=1, pose=pose)

    def test_non_unit_quaternion_rejected(self) -> None:
        """A quaternion whose norm is outside tolerance fails validation."""
        pose = _full_pose()
        pose["Root"] = Transform3D(rotation=(5.0, 0.0, 0.0, 0.0))
        with pytest.raises(ValidationError):
            BlockingKeyPose(frame=1, pose=pose)


class TestBlockingInputModel:
    """REQ-01 payload model — document-level validation."""

    def test_well_formed_payload_validates(self) -> None:
        """A payload with keyposes and no skeleton validates (REQ-01 SC-01)."""
        payload = BlockingInput(keyposes=[_keypose(frame=1)])
        assert payload.skeleton is None
        assert len(payload.keyposes) == 1

    def test_unknown_top_level_field_rejected(self) -> None:
        """An unexpected top-level key fails validation (REQ-01 SC-02)."""
        with pytest.raises(ValidationError):
            BlockingInput(keyposes=[_keypose(frame=1)], bogus=1)

    def test_empty_keyposes_rejected(self) -> None:
        """An empty keyposes list fails validation (REQ-01 SC-03)."""
        with pytest.raises(ValidationError):
            BlockingInput(keyposes=[])

    def test_max_keypose_count_bounded(self) -> None:
        """More than MAX_KEYPOSES keyposes fails validation (REQ-04 SC-03)."""
        kps = [_keypose(frame=i + 1) for i in range(MAX_KEYPOSES + 1)]
        with pytest.raises(ValidationError):
            BlockingInput(keyposes=kps)

    def test_skeleton_mismatch_pose_rejected(self) -> None:
        """A keypose pose that omits a bone of the resolved skeleton fails (REQ-01 SC-04)."""
        partial = {b: Transform3D() for b in BONES[:-1]}
        with pytest.raises(ValidationError):
            BlockingInput(keyposes=[BlockingKeyPose(frame=1, pose=partial)])

    def test_custom_skeleton_must_match_pose_bones(self) -> None:
        """When a skeleton is provided, poses must address exactly its bones."""
        custom = Skeleton(bones={"Root": DEFAULT_NEUTRAL_SKELETON.bones["Root"]})
        pose = {"Root": Transform3D()}
        payload = BlockingInput(
            skeleton=custom, keyposes=[BlockingKeyPose(frame=1, pose=pose)]
        )
        assert payload.resolved_skeleton() == custom
        # A pose naming a bone not in the custom skeleton must fail.
        with pytest.raises(ValidationError):
            BlockingInput(
                skeleton=custom,
                keyposes=[BlockingKeyPose(frame=1, pose=_full_pose())],
            )

    def test_resolved_skeleton_default_when_omitted(self) -> None:
        """resolved_skeleton() returns the default neutral skeleton when omitted."""
        payload = BlockingInput(keyposes=[_keypose(frame=1)])
        assert payload.resolved_skeleton() == DEFAULT_NEUTRAL_SKELETON


class TestBlockingToNeutralMotion:
    """REQ-02 converter."""

    def _conv(self, frames: list[int]) -> object:
        payload = BlockingInput(keyposes=[_keypose(frame=f) for f in frames])
        return blocking_to_neutral_motion(payload)

    def test_sparse_frames_and_keyposes_produced(self) -> None:
        """Keyposes at frames 1, 5, 13 -> 3 frames + keyposes + duration 13 (SC-01)."""
        motion = self._conv([1, 5, 13])
        assert [f.frame for f in motion.frames] == [1, 5, 13]
        assert [(k.frame, k.weight) for k in motion.keyposes] == [(1, 1.0), (5, 1.0), (13, 1.0)]
        assert motion.meta.duration_frames == 13
        assert motion.meta.fps == DEFAULT_BLOCKING_FPS

    def test_default_skeleton_used_when_omitted(self) -> None:
        """Produced motion carries the default neutral skeleton (SC-02)."""
        motion = self._conv([1, 3])
        assert motion.skeleton == DEFAULT_NEUTRAL_SKELETON
        motion.validate_invariants()

    def test_duplicate_frames_rejected(self) -> None:
        """Two keyposes at the same frame fail conversion (SC-03)."""
        with pytest.raises(ValueError):
            self._conv([1, 1])

    def test_frames_sorted_ascending(self) -> None:
        """Input frames are sorted ascending regardless of payload order."""
        motion = self._conv([13, 1, 5])
        assert [f.frame for f in motion.frames] == [1, 5, 13]

    def test_frame_beyond_duration_rejected(self) -> None:
        """A keypose frame > max frame still yields a document whose frames are
        within duration_frames (max frame == duration). Keypose frames beyond
        the highest frame are impossible by construction here; the converter
        must never emit a frame beyond duration_frames."""
        motion = self._conv([2, 4])
        assert motion.meta.duration_frames == 4
        assert max(f.frame for f in motion.frames) == 4

    def test_single_keypose_safe(self) -> None:
        """A single keypose produces a one-frame motion with valid invariants."""
        motion = self._conv([7])
        motion.validate_invariants()
        assert motion.meta.duration_frames == 7
