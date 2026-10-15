"""Pure forward kinematics: a sparse pose becomes world-space bone segments.

Standard library only: this module may import the domain (``core.models``) and
nothing from ``ports/`` or ``adapters/``, and no third-party package (NFR-01).

The rig is plain FK. A joint's local transform is its translation followed by
its rotation, and every joint inherits its parent's accumulated rotation. The
domain assumes identity bind rotations, so a pose rotation *is* the local
rotation, and ``JointPose.translation`` is an offset from ``rest_translation``
(see the ``AGENTS.md`` invariants).

This is the math the 3D viewport draws (plan §3.B), and the IK pass (M7) will
need the same world positions — both reasons to keep it out of the widgets.
"""

from __future__ import annotations

from collections.abc import Mapping

from aimation_actor.core.models import JointPose, Quaternion, Skeleton, Vector3

__all__ = ["bone_segments", "joint_world_positions", "rotate"]

_IDENTITY = Quaternion.identity()


def rotate(rotation: Quaternion, vector: Vector3) -> Vector3:
    """``vector`` rotated by the unit quaternion ``rotation``."""
    quaternion_vector = (rotation.x, rotation.y, rotation.z)
    qx, qy, qz = quaternion_vector
    # t = 2 * (q_vector x vector)
    tx = 2.0 * (qy * vector.z - qz * vector.y)
    ty = 2.0 * (qz * vector.x - qx * vector.z)
    tz = 2.0 * (qx * vector.y - qy * vector.x)
    # rotated = vector + w * t + q_vector x t
    return Vector3(
        x=vector.x + rotation.w * tx + (qy * tz - qz * ty),
        y=vector.y + rotation.w * ty + (qz * tx - qx * tz),
        z=vector.z + rotation.w * tz + (qx * ty - qy * tx),
    )


def _compose(parent: Quaternion, child: Quaternion) -> Quaternion:
    """The combined rotation: ``child`` applied inside ``parent``."""
    return Quaternion(
        w=parent.w * child.w - parent.x * child.x - parent.y * child.y - parent.z * child.z,
        x=parent.w * child.x + parent.x * child.w + parent.y * child.z - parent.z * child.y,
        y=parent.w * child.y - parent.x * child.z + parent.y * child.w + parent.z * child.x,
        z=parent.w * child.z + parent.x * child.y - parent.y * child.x + parent.z * child.w,
    )


def _add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x + right.x, y=left.y + right.y, z=left.z + right.z)


def joint_world_positions(skeleton: Skeleton, pose: Mapping[str, JointPose]) -> dict[str, Vector3]:
    """Every joint's world-space position, in the skeleton's hierarchy order.

    ``pose`` is a sparse mapping: a joint absent from it (or absent from the
    pose's rotation) keeps its bind transform, so the result always covers the
    whole skeleton. ``skeleton`` must be ordered root-first — its documented
    invariant — because each joint is resolved from its already-placed parent.
    """
    positions: dict[str, Vector3] = {}
    rotations: dict[str, Quaternion] = {}

    for joint in skeleton.joints:
        local = pose.get(joint.name)
        local_rotation = _IDENTITY if local is None else local.rotation
        offset = joint.rest_translation
        if local is not None:
            offset = _add(offset, local.translation)

        if joint.parent is None:
            positions[joint.name] = offset
            rotations[joint.name] = local_rotation
            continue

        parent_rotation = rotations[joint.parent]
        positions[joint.name] = _add(positions[joint.parent], rotate(parent_rotation, offset))
        rotations[joint.name] = _compose(parent_rotation, local_rotation)

    return positions


def bone_segments(
    skeleton: Skeleton, pose: Mapping[str, JointPose]
) -> tuple[tuple[Vector3, Vector3], ...]:
    """Parent→child line segments, in the skeleton's hierarchy order.

    The render-ready shape of ``joint_world_positions``: the root has no parent,
    so it contributes no segment.
    """
    positions = joint_world_positions(skeleton, pose)
    return tuple(
        (positions[joint.parent], positions[joint.name])
        for joint in skeleton.joints
        if joint.parent is not None
    )
