"""Tests for the core domain entities."""

import pytest

from aimation_actor.core.models import (
    FrameImage,
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)


def test_identity_quaternion() -> None:
    quaternion = Quaternion.identity()
    assert (quaternion.w, quaternion.x, quaternion.y, quaternion.z) == (1.0, 0.0, 0.0, 0.0)


def test_skeleton_reports_names_and_root() -> None:
    skeleton = Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )

    assert skeleton.names() == ("Main", "Pelvis")
    assert skeleton.root().name == "Main"


def test_timeline_state_holds_sparse_stepped_keys() -> None:
    skeleton = Skeleton(joints=(JointData(name="Main", parent=None),))
    keyframes = (
        Keyframe(frame=15, pose={"Main": JointPose(rotation=Quaternion.identity())}),
        Keyframe(frame=42, pose={"Main": JointPose(rotation=Quaternion.identity())}),
    )
    state = TimelineState(
        skeleton=skeleton, keyframes=keyframes, fps=24.0, frame_start=15, frame_end=42
    )

    assert state.frames() == (15, 42)


def test_a_frame_image_carries_a_flat_rgb_buffer() -> None:
    # M5 S2: what an engine receives is plain bytes, so the port layer never has
    # to know which toolkit decoded the video.
    frame = FrameImage(width=2, height=3, rgb=bytes(2 * 3 * 3))

    assert len(frame.rgb) == 18


def test_a_frame_image_whose_buffer_does_not_fit_is_rejected() -> None:
    # A truncated buffer would be a silently corrupted picture inside the engine,
    # so it fails at the boundary instead.
    with pytest.raises(ValueError, match=r"holds 17 bytes, expected 18"):
        FrameImage(width=2, height=3, rgb=bytes(17))
