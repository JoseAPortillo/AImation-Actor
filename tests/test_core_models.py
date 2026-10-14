"""Tests for the core domain entities."""

from aimation_actor.core.models import (
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
