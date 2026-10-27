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

import math
from collections.abc import Mapping

from aimation_actor.core.models import JointPose, Quaternion, Skeleton, Vector3

__all__ = [
    "bone_segments",
    "compose",
    "inverse",
    "joint_transforms",
    "joint_world_positions",
    "quaternion_between_directions",
    "rotate",
    "rotate_about_axis",
]

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


def compose(parent: Quaternion, child: Quaternion) -> Quaternion:
    """The combined rotation: ``child`` applied inside ``parent`` (world = parent ⊗ child)."""
    return Quaternion(
        w=parent.w * child.w - parent.x * child.x - parent.y * child.y - parent.z * child.z,
        x=parent.w * child.x + parent.x * child.w + parent.y * child.z - parent.z * child.y,
        y=parent.w * child.y - parent.x * child.z + parent.y * child.w + parent.z * child.x,
        z=parent.w * child.z + parent.x * child.y - parent.y * child.x + parent.z * child.w,
    )


def inverse(rotation: Quaternion) -> Quaternion:
    """The inverse of a unit quaternion: its conjugate."""
    return Quaternion(rotation.w, -rotation.x, -rotation.y, -rotation.z)


def quaternion_between_directions(source: Vector3, target: Vector3) -> Quaternion:
    """The minimal rotation taking unit ``source`` onto unit ``target``.

    Both inputs need not be exactly unit length (they are normalized here);
    the result has no twist component beyond the swing itself.
    """
    dot = source.x * target.x + source.y * target.y + source.z * target.z
    if dot > 1.0 - 1e-12:
        return _IDENTITY
    axis = Vector3(
        x=source.y * target.z - source.z * target.y,
        y=source.z * target.x - source.x * target.z,
        z=source.x * target.y - source.y * target.x,
    )
    magnitude = math.sqrt(axis.x**2 + axis.y**2 + axis.z**2)
    if magnitude <= 1e-12:
        # Opposite directions: a half turn about any perpendicular axis.
        perpendicular = _perpendicular_to(source)
        return Quaternion(w=0.0, x=perpendicular.x, y=perpendicular.y, z=perpendicular.z)
    total = dot + 1.0
    return Quaternion(
        w=total / math.sqrt(total**2 + magnitude**2),
        x=axis.x / math.sqrt(total**2 + magnitude**2),
        y=axis.y / math.sqrt(total**2 + magnitude**2),
        z=axis.z / math.sqrt(total**2 + magnitude**2),
    )


def rotate_about_axis(vector: Vector3, axis: Vector3, radians: float) -> Vector3:
    """``vector`` rotated by ``radians`` about the unit ``axis`` (Rodrigues)."""
    half = radians / 2.0
    sin = math.sin(half)
    return rotate(
        Quaternion(w=math.cos(half), x=axis.x * sin, y=axis.y * sin, z=axis.z * sin),
        vector,
    )


def _perpendicular_to(vector: Vector3) -> Vector3:
    """A unit vector perpendicular to the unit ``vector``."""
    smallest = min(
        ("x", abs(vector.x)),
        ("y", abs(vector.y)),
        ("z", abs(vector.z)),
        key=lambda item: item[1],
    )[0]
    third = Vector3(x=0.0, y=0.0, z=0.0)
    third = Vector3(**{smallest: 1.0})
    cross = Vector3(
        x=vector.y * third.z - vector.z * third.y,
        y=vector.z * third.x - vector.x * third.z,
        z=vector.x * third.y - vector.y * third.x,
    )
    length = math.sqrt(cross.x**2 + cross.y**2 + cross.z**2)
    return Vector3(x=cross.x / length, y=cross.y / length, z=cross.z / length)


def _add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x + right.x, y=left.y + right.y, z=left.z + right.z)


def joint_transforms(
    skeleton: Skeleton, pose: Mapping[str, JointPose]
) -> tuple[dict[str, Vector3], dict[str, Quaternion]]:
    """Every joint's world ``(position, accumulated rotation)``, hierarchy order.

    The rotations are the transforms FK actually produces; ``rotate``'s output
    and the placement of children use them, so a caller can reproduce any of
    this module's other functions from this one without re-walking the chain.
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
        rotations[joint.name] = compose(parent_rotation, local_rotation)

    return positions, rotations


def joint_world_positions(skeleton: Skeleton, pose: Mapping[str, JointPose]) -> dict[str, Vector3]:
    """Every joint's world-space position, in the skeleton's hierarchy order.

    ``pose`` is a sparse mapping: a joint absent from it (or absent from the
    pose's rotation) keeps its bind transform, so the result always covers the
    whole skeleton. ``skeleton`` must be ordered root-first — its documented
    invariant — because each joint is resolved from its already-placed parent.
    """
    positions, _rotations = joint_transforms(skeleton, pose)
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
