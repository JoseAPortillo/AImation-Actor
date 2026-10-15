"""Tests for the pure forward-kinematics helpers (plan §3.B, split view).

The viewport draws bone segments, so the math that turns a sparse pose into
world-space positions is pinned here, away from Qt.
"""

from __future__ import annotations

import pytest
from fbx_helpers import rotation_x

from aimation_actor.core.kinematics import bone_segments, joint_world_positions
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Quaternion,
    Skeleton,
    Vector3,
)


def _skeleton() -> Skeleton:
    """A four-joint chain: offsets along ``z``, so a rotation is observable."""
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="Spine_1", parent="Pelvis", rest_translation=Vector3(z=20.0)),
            JointData(name="Head", parent="Spine_1", rest_translation=Vector3(z=30.0)),
        )
    )


def _neutral(skeleton: Skeleton) -> dict[str, JointPose]:
    """Every joint at its bind: identity rotation, zero offset."""
    return {joint.name: JointPose(rotation=Quaternion.identity()) for joint in skeleton.joints}


def _xyz(vector: Vector3) -> tuple[float, float, float]:
    return (vector.x, vector.y, vector.z)


def test_joint_world_positions_accumulate_the_bind_offsets() -> None:
    skeleton = _skeleton()

    positions = joint_world_positions(skeleton, _neutral(skeleton))

    assert _xyz(positions["Main"]) == pytest.approx((0.0, 0.0, 0.0))
    assert _xyz(positions["Pelvis"]) == pytest.approx((0.0, 0.0, 100.0))
    assert _xyz(positions["Spine_1"]) == pytest.approx((0.0, 0.0, 120.0))
    assert _xyz(positions["Head"]) == pytest.approx((0.0, 0.0, 150.0))


def test_joint_world_positions_apply_a_parent_rotation_to_its_children() -> None:
    skeleton = _skeleton()
    pose = _neutral(skeleton)
    # 90 degrees about X turns a ``+z`` offset into ``-y``.
    pose["Pelvis"] = JointPose(rotation=rotation_x(90.0))

    positions = joint_world_positions(skeleton, pose)

    # The rotated joint itself stays put; everything below it swings.
    assert _xyz(positions["Pelvis"]) == pytest.approx((0.0, 0.0, 100.0))
    assert _xyz(positions["Spine_1"]) == pytest.approx((0.0, -20.0, 100.0))
    assert _xyz(positions["Head"]) == pytest.approx((0.0, -50.0, 100.0))


def test_joint_world_positions_add_the_pose_translation_offset() -> None:
    skeleton = _skeleton()
    pose = _neutral(skeleton)
    # Translations are offsets from ``rest_translation``, not absolutes.
    pose["Pelvis"] = JointPose(rotation=Quaternion.identity(), translation=Vector3(z=-30.0))

    positions = joint_world_positions(skeleton, pose)

    assert _xyz(positions["Pelvis"]) == pytest.approx((0.0, 0.0, 70.0))
    assert _xyz(positions["Head"]) == pytest.approx((0.0, 0.0, 120.0))


def test_joint_world_positions_rotate_the_whole_rig_with_the_root() -> None:
    skeleton = _skeleton()
    pose = _neutral(skeleton)
    pose["Main"] = JointPose(rotation=rotation_x(90.0))

    positions = joint_world_positions(skeleton, pose)

    assert _xyz(positions["Pelvis"]) == pytest.approx((0.0, -100.0, 0.0))
    assert _xyz(positions["Spine_1"]) == pytest.approx((0.0, -120.0, 0.0))


def test_joint_world_positions_treat_a_missing_joint_as_its_bind() -> None:
    skeleton = _skeleton()

    positions = joint_world_positions(skeleton, {})

    assert _xyz(positions["Head"]) == pytest.approx((0.0, 0.0, 150.0))


def test_bone_segments_connect_every_joint_to_its_parent_in_hierarchy_order() -> None:
    skeleton = _skeleton()

    segments = bone_segments(skeleton, _neutral(skeleton))

    assert len(segments) == 3  # the root has no parent, so it is not a segment
    assert [_xyz(start) for start, _ in segments] == [
        pytest.approx((0.0, 0.0, 0.0)),
        pytest.approx((0.0, 0.0, 100.0)),
        pytest.approx((0.0, 0.0, 120.0)),
    ]
    assert [_xyz(end) for _, end in segments] == [
        pytest.approx((0.0, 0.0, 100.0)),
        pytest.approx((0.0, 0.0, 120.0)),
        pytest.approx((0.0, 0.0, 150.0)),
    ]
