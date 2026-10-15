"""Tests for the pure keyframe-management services (spec FR-CAP-04, FR-CAP-07)."""

from __future__ import annotations

from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)
from aimation_actor.core.services import (
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
