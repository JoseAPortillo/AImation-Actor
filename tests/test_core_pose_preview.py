"""Tests for the imported-pose preview projection (FR-IMP-04, the eye's half).

A refined FBX carries no camera, so its overlay is an HONEST APPROXIMATION:
the pose's FK world positions projected front-view (domain X across, domain Z
up), scaled so the body fills ~85 % of the frame height with its feet near the
bottom and its bbox centered horizontally. It shows the animator's refinement
over the clip; it does not claim S1 capture alignment. A pose with no vertical
extent projects to nothing — no invented geometry.
"""

from __future__ import annotations

from aimation_actor.core.models import (
    JointData,
    JointPose,
    Quaternion,
    Skeleton,
    Vector3,
)
from aimation_actor.core.pose_preview import preview_projection


def _standing() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="Spine_1", parent="Pelvis", rest_translation=Vector3(z=20.0)),
            JointData(name="Neck", parent="Spine_1", rest_translation=Vector3(z=30.0)),
            JointData(name="Head", parent="Neck", rest_translation=Vector3(z=20.0)),
            JointData(name="L_Hip", parent="Pelvis", rest_translation=Vector3(x=10.0, z=-5.0)),
            JointData(name="R_Hip", parent="Pelvis", rest_translation=Vector3(x=-10.0, z=-5.0)),
        )
    )


_EMPTY_POSE: dict[str, JointPose] = {}


def test_a_standing_pose_projects_feet_low_head_high_and_centered() -> None:
    projected = preview_projection(_standing(), _EMPTY_POSE, frame_size=(1000, 500))

    feet = max(point[1] for point in projected.values())  # screen y grows down
    head = projected["Head"][1]
    assert head < feet  # head sits ABOVE the feet on screen (y grows down)
    assert feet <= 500.0
    center_x = (projected["L_Hip"][0] + projected["R_Hip"][0]) / 2.0
    assert center_x == 500.0  # bbox centered on the frame
    assert 465.0 <= feet <= 485.0  # feet near the bottom, not glued to it
    body_height = feet - projected["Head"][1]
    assert abs(body_height - 0.85 * 500.0) < 1.0  # the body fills the frame


def test_the_preview_reads_the_pose_so_a_crouch_shrinks_the_figure() -> None:
    skeleton = _standing()
    straight = preview_projection(skeleton, _EMPTY_POSE, frame_size=(1000, 500))
    # Fold the spine down: half the body height above the hips.
    bent_pose = {
        "Spine_1": JointPose(rotation=Quaternion.identity()),
        "Pelvis": JointPose(rotation=Quaternion.identity(), translation=Vector3(z=-40.0)),
    }
    bent = preview_projection(skeleton, bent_pose, frame_size=(1000, 500))

    straight_height = max(p[1] for p in straight.values()) - min(
        p[1] for p in straight.values()
    )
    bent_height = max(p[1] for p in bent.values()) - min(p[1] for p in bent.values())
    assert bent_height < straight_height


def test_depth_is_invisible_to_a_front_view() -> None:
    skeleton = _standing()
    flat = preview_projection(skeleton, _EMPTY_POSE, frame_size=(1000, 500))
    # The same skeleton moved purely along the domain Y (depth) axis: Main's
    # translation is a pose value, so move it and expect identical pixels.
    deeper = {"Main": JointPose(rotation=Quaternion.identity(), translation=Vector3(y=500.0))}
    moved = preview_projection(skeleton, deeper, frame_size=(1000, 500))

    assert moved == flat


def test_a_raised_pose_floats_above_the_floor_line() -> None:
    # The ground is the BIND's, not the pose's lowest point: elevation lives
    # in the data (jumps, sits) and the preview must show it, not pin the
    # figure back to the floor.
    skeleton = _standing()
    standing = preview_projection(skeleton, _EMPTY_POSE, frame_size=(1000, 500))
    jumped = {
        "Main": JointPose(rotation=Quaternion.identity(), translation=Vector3(z=40.0)),
    }
    raised = preview_projection(skeleton, jumped, frame_size=(1000, 500))

    assert max(p[1] for p in raised.values()) < max(p[1] for p in standing.values())


def test_a_pose_without_vertical_extent_projects_nothing() -> None:
    single = Skeleton(joints=(JointData(name="Main", parent=None),))

    assert preview_projection(single, _EMPTY_POSE, frame_size=(100, 100)) == {}


def test_a_degenerate_frame_size_projects_nothing() -> None:
    assert preview_projection(_standing(), _EMPTY_POSE, frame_size=(0, 500)) == {}
