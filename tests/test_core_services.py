"""Tests for the pure keyframe-management services (spec FR-CAP-04, FR-CAP-07, FR-EXP-02)."""

from __future__ import annotations

import pytest
from fbx_helpers import rotation_z

from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)
from aimation_actor.core.services import (
    build_production_pose,
    clamp_frame,
    find_key,
    key_frames,
    mark_pose,
    next_key_frame,
    previous_key_frame,
    remove_pose,
)


def _state(*frames: int, frame_start: int = 0, frame_end: int = 100) -> TimelineState:
    skeleton = Skeleton(joints=(JointData(name="Main", parent=None),))
    keyframes = tuple(
        Keyframe(frame=frame, pose={"Main": JointPose(rotation=Quaternion.identity())})
        for frame in frames
    )
    return TimelineState(
        skeleton=skeleton,
        keyframes=keyframes,
        fps=24.0,
        frame_start=frame_start,
        frame_end=frame_end,
    )


def test_key_frames_are_sorted_and_unique() -> None:
    state = _state(42, 15, 42)

    assert key_frames(state) == (15, 42)


def test_find_key_returns_the_keyframe_or_none() -> None:
    state = _state(15)

    assert find_key(state, 15) is not None
    assert find_key(state, 16) is None


def test_mark_pose_inserts_in_frame_order() -> None:
    state = _state(15, 42)

    marked = mark_pose(state, 30, {"Main": JointPose(rotation=Quaternion.identity())})

    assert key_frames(marked) == (15, 30, 42)


def test_mark_pose_overwrites_without_duplicating() -> None:
    state = _state(15)
    replacement = {"Main": JointPose(rotation=Quaternion.identity(), translation=Vector3(x=5.0))}

    marked = mark_pose(state, 15, replacement)

    assert key_frames(marked) == (15,)  # still one key at frame 15
    assert find_key(marked, 15).pose["Main"].translation == Vector3(x=5.0)


def test_remove_pose_drops_the_key_and_ignores_empty_frames() -> None:
    state = _state(15, 42)

    removed = remove_pose(state, 15)
    assert key_frames(removed) == (42,)
    assert remove_pose(removed, 15) is removed  # absent frame -> same state


def test_navigation_lands_on_the_neighbouring_keys() -> None:
    state = _state(15, 42, 60)

    assert next_key_frame(state, 15) == 42
    assert next_key_frame(state, 20) == 42
    assert next_key_frame(state, 60) is None
    assert previous_key_frame(state, 42) == 15
    assert previous_key_frame(state, 41) == 15
    assert previous_key_frame(state, 15) is None


def test_operations_leave_the_input_untouched() -> None:
    state = _state(15)
    before = state.keyframes

    mark_pose(state, 42, {"Main": JointPose(rotation=Quaternion.identity())})
    remove_pose(state, 15)

    assert state.keyframes == before  # frozen: inputs are never mutated


def test_clamp_frame_keeps_the_frame_within_the_span() -> None:
    state = _state(frame_start=15, frame_end=42)

    assert clamp_frame(state, 0) == 15
    assert clamp_frame(state, 30) == 30
    assert clamp_frame(state, 99) == 42


# --------------------------------------------------------------------------- #
# Offset calculation (plan §5.B): splitting a world pose over Main / Pelvis.
# --------------------------------------------------------------------------- #

BIND_HIP_HEIGHT = 100.0


def _production_skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=BIND_HIP_HEIGHT)),
            JointData(name="Spine_1", parent="Pelvis"),
            JointData(name="Head", parent="Spine_1"),
        )
    )


def test_build_production_pose_keeps_the_ground_root_clean_for_the_animator() -> None:
    pose = WorldPose(translation=Vector3(x=10.0, y=20.0, z=95.0), rotations={})

    built = build_production_pose(pose, _production_skeleton())

    # ``Main`` is the animator's world control: the capture never writes it, so
    # the blocking export ships "in place" and the recovered horizontal
    # displacement is deliberately dropped.
    assert built["Main"].translation == Vector3()
    assert built["Main"].rotation == Quaternion.identity()


def test_build_production_pose_turns_the_world_hip_height_into_a_bind_offset() -> None:
    pose = WorldPose(translation=Vector3(x=10.0, y=20.0, z=95.0), rotations={})

    built = build_production_pose(pose, _production_skeleton())

    pelvis = built["Pelvis"]
    # 95 cm of world height against a 100 cm bind -> a -5 cm local offset, which
    # the FBX writer adds back to the bind translation.
    assert (pelvis.translation.x, pelvis.translation.y, pelvis.translation.z) == pytest.approx(
        (0.0, 0.0, 95.0 - BIND_HIP_HEIGHT)
    )


def test_build_production_pose_keeps_body_rotations_and_zeroes_their_translation() -> None:
    rotation = rotation_z(30.0)
    pose = WorldPose(translation=Vector3(), rotations={"Spine_1": rotation})

    built = build_production_pose(pose, _production_skeleton())

    assert built["Spine_1"] == JointPose(rotation=rotation, translation=Vector3())


def test_build_production_pose_returns_a_full_pose_with_bind_defaults() -> None:
    pose = WorldPose(translation=Vector3(), rotations={"Spine_1": rotation_z(30.0)})

    built = build_production_pose(pose, _production_skeleton())

    assert set(built) == {"Main", "Pelvis", "Spine_1", "Head"}
    assert built["Head"].rotation == Quaternion.identity()


def test_build_production_pose_ignores_a_raw_rotation_for_the_ground_root() -> None:
    pose = WorldPose(translation=Vector3(), rotations={"Main": rotation_z(90.0)})

    built = build_production_pose(pose, _production_skeleton())

    assert built["Main"].rotation == Quaternion.identity()
