"""Rotation rig helpers (SDD §14, task 2.10).

Two pieces of rig-grade rotation math:

- :func:`apply_rotation` — composes a bone's motion rotation ``q`` with its
  retarget entry: ``q' = normalize(axis_correction * q * rotation_offset)``.
  The offset is applied in LOCAL space (post-multiplied) and the axis
  correction in global space (pre-multiplied). Decision C (MVP): an identity
  *source* rotation is returned as identity — rotation is never fabricated
  from a source that carries none.
- :func:`axis_correction_quat` — the documented forward-axis correction pairs
  (FBX -Z forward <-> glTF +Z forward: half-turn about Y; yup <-> zup:
  quarter-turn about X). Same-convention pairs are the identity; pairs outside
  the table fail loudly.
"""

from __future__ import annotations

import math

from aimation_actor_core.domain.animation.quat import quat_multiply, quat_normalize
from aimation_actor_core.domain.retargeting.map import RetargetEntry
from aimation_actor_core.shared.types import Vec4

#: Identity quaternion ``(w, x, y, z)``.
IDENTITY_QUAT: Vec4 = (1.0, 0.0, 0.0, 0.0)

#: cos/sin of 45 degrees — the half-turn about X used for up-axis flips.
_SIN_45: float = math.sqrt(2.0) / 2.0

#: Documented forward-axis correction pairs (keyed by source, target).
_FORWARD_AXIS_PAIRS: dict[tuple[str, str], Vec4] = {
    # FBX convention is -Z forward; glTF is +Z forward: reverse Z with a
    # half-turn about Y (never about X/Z, which would flip the character
    # sideways or upside-down).
    ("fbx", "gltf"): (0.0, 0.0, 1.0, 0.0),
    ("gltf", "fbx"): (0.0, 0.0, 1.0, 0.0),  # self-inverse
    # yup -> zup re-aims the up axis onto +Z: +90deg about X; reverse is -90deg.
    ("yup", "zup"): (_SIN_45, _SIN_45, 0.0, 0.0),
    ("zup", "yup"): (_SIN_45, -_SIN_45, 0.0, 0.0),
}


def apply_rotation(rotation: Vec4, entry: RetargetEntry) -> Vec4:
    """Compose a bone's motion rotation with its retarget configuration.

    Args:
        rotation: The bone's LOCAL motion rotation ``(w, x, y, z)``.
        entry: The bone's retarget entry (LOCAL offset, optional axis).

    Returns:
        ``q' = normalize(axis_correction * rotation * rotation_offset)``; an
        identity ``rotation`` is returned as identity (Decision C — the MVP
        never fabricates rotation from an identity source).
    """
    if rotation == IDENTITY_QUAT:
        return IDENTITY_QUAT
    q = rotation
    if entry.axis_correction is not None:
        q = quat_multiply(entry.axis_correction, q)
    q = quat_multiply(q, entry.rotation_offset)
    return quat_normalize(q)


def axis_correction_quat(source_forward: str, target_forward: str) -> Vec4:
    """Return the reorientation quaternion for a forward-axis convention pair.

    Args:
        source_forward: Source convention token — one of ``"fbx"``, ``"gltf"``,
            ``"yup"``, ``"zup"``.
        target_forward: Target convention token (same vocabulary).

    Returns:
        The axis-correction ``(w, x, y, z)`` quaternion; identity when the
        conventions match.

    Raises:
        ValueError: For pairs outside the documented table.
    """
    if source_forward == target_forward:
        return IDENTITY_QUAT
    try:
        return _FORWARD_AXIS_PAIRS[(source_forward, target_forward)]
    except KeyError:
        raise ValueError(
            f"no axis correction for forward-axis pair "
            f"({source_forward!r}, {target_forward!r})"
        ) from None