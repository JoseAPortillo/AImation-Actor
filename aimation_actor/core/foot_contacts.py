"""Planted-foot detection for the IK pin pass (M7, the FR-IK-01 detection half).

Standard library only: this module may import the domain (``core.models``,
``core.kinematics``) and nothing from ``ports/`` or ``adapters/``, and no
third-party package (NFR-01).

A foot is "planted" across a span when, at the two bounding ORIGINAL keys of
the span, its world position sits at ground contact and does not move beyond
the planting tolerance between them. The thresholds are open question 8's
answer (2026-10-23, the balanced option; re-tuned 2026-10-24 at the
animator's decision after the M8 S7 detection crop moved the standing
subject's readings to 5.24 cm drift / 6.5 cm toe z on the real JACE clip):
they are calibrated against the measured HMR2 per-frame noise — identical
guidance frames hit with a mean error of 3.1-6.3 cm (M6 T8 evidence) — so a
real contact whose readings wobble inside that noise is detected, while a
foot actually swinging away is not.

Detection reads the FOOT joints (``L_Foot``/``R_Foot``, the toe balls); the
pin pass (``core.foot_ik``) pins their ANKLE partners, so the split foot pair
drive both ends without a second joint hierarchy traversal. Ground z = 0:
the domain's ground plane is the one ``Pelvis``' height is measured from, and
a foot reading below it is a penetration —
still a contact, which the pass must fix.

Foot positions come from the same pure forward kinematics the 3D viewport
draws (``core.kinematics.joint_world_positions``), so a marked foot can never
disagree between the pane and the IK pass.
"""

from __future__ import annotations

import math

from aimation_actor.core.kinematics import joint_world_positions
from aimation_actor.core.models import JointPose, Skeleton, TimelineState, Vector3

__all__ = [
    "FOOT_JOINTS",
    "GROUND_CONTACT_HEIGHT_CM",
    "PLANT_POSITION_TOLERANCE_CM",
    "contact_spans",
]

#: The detected joints and the joints the pin pass later drives: each pair is
#: ``(contact_joint, attach_joint)`` — the toe ball is read for the plant, the
#: ankle is the point the two-bone IK lands on the first key's contact.
FOOT_JOINTS: tuple[tuple[str, str], ...] = (
    ("L_Foot", "L_Ankle"),
    ("R_Foot", "R_Ankle"),
)

#: Open question 8 (2026-10-23, the balanced option; re-tuned 2026-10-24
#: after the M8 S7 detection crop; re-tuned again 2026-10-27 at R5, at the
#: animator's decision): the two bounding original keys agree on a planted
#: foot within this much world drift. R5 evidence: on the real rotating
#: camera clip the planted-key drift measures 6.9-8.2 cm body-relative
#: (median), up to 23.9 (max) - above the old 5.5 cm bar the detector saw
#: only 5/15 spans and the animator's eyes read the rest as sliding. At
#: 12 cm the sweep found 9/15 planted with no new artifact class under
#: grounding (key-boundary jumps 4.5 -> 1.7 cm); the one accepted cost is
#: a span with 7.3 cm key-to-key z travel ((77,93) R_Foot, step-LIKE -
#: either a real step or capture noise, and the animator's eye test of
#: the pinned output preferred the pin).
PLANT_POSITION_TOLERANCE_CM = 12.0

#: ... and the toe ball reads this close to the ground plane to count as a
#: contact (a reading below it is penetration, still planted).
GROUND_CONTACT_HEIGHT_CM = 8.0


def contact_spans(
    timeline: TimelineState,
    original_key_frames: tuple[int, ...],
    *,
    ground_z: float = 0.0,
    position_tolerance_cm: float = PLANT_POSITION_TOLERANCE_CM,
    ground_height_cm: float = GROUND_CONTACT_HEIGHT_CM,
) -> dict[tuple[int, int], set[str]]:
    """Which feet are planted across each original-key span of the timeline.

    ``original_key_frames`` lists the pre-fill human keys in any order; every
    one must be a keyed frame of ``timeline`` (a caller listing a frame the
    timeline does not carry is a bug, named loudly). Spans run between sorted
    adjacent pairs; a pair with no interior frames (the keys are adjacent)
    has nothing to correct and is not reported.

    Returns ``{(left_key, right_key): {foot names planted}}`` — a span key
    with an empty set means no foot of that span is a contact, which the pin
    pass must treat as "nothing pinned here".
    """
    keyed = {keyframe.frame for keyframe in timeline.keyframes}
    frames = sorted(set(original_key_frames))
    missing = [frame for frame in frames if frame not in keyed]
    if missing:
        raise ValueError(
            "the original keys must be keyed frames of the timeline "
            f"(missing: {missing})"
        )

    spans: dict[tuple[int, int], set[str]] = {}
    for left, right in zip(frames, frames[1:], strict=False):
        if right - left <= 1:
            continue
        left_pose = _keyed_pose(timeline, left)
        right_pose = _keyed_pose(timeline, right)
        left_world = joint_world_positions(timeline.skeleton, left_pose)
        right_world = joint_world_positions(timeline.skeleton, right_pose)

        planted: set[str] = set()
        for contact, _ankle in FOOT_JOINTS:
            if _is_planted(
                _planting_read(timeline.skeleton, left_world, contact),
                _planting_read(timeline.skeleton, right_world, contact),
                ground_z=ground_z,
                position_tolerance_cm=position_tolerance_cm,
                ground_height_cm=ground_height_cm,
            ):
                planted.add(contact)
        spans[(left, right)] = planted
    return spans


def _planting_read(
    skeleton: Skeleton, world: dict[str, Vector3], contact: str
) -> Vector3:
    """A contact reading that root displacement cannot fake drift into (M8 S6).

    The root carries the M8 captured trajectory; a body standing still while
    its root moves must still read as planted, so the horizontal comparison
    happens against the body's own frame. World Z stays: the ground plane is
    a world fact.
    """
    root = world[skeleton.root().name]
    foot = world[contact]
    return Vector3(x=foot.x - root.x, y=foot.y - root.y, z=foot.z)


def _keyed_pose(timeline: TimelineState, frame: int) -> dict[str, JointPose]:
    """The pose of the keyframe at ``frame`` (validated to exist upstream)."""
    for keyframe in timeline.keyframes:
        if keyframe.frame == frame:
            return dict(keyframe.pose)
    raise KeyError(frame)  # pragma: no cover - guarded by the caller


def _is_planted(
    left: Vector3,
    right: Vector3,
    *,
    ground_z: float,
    position_tolerance_cm: float,
    ground_height_cm: float,
) -> bool:
    """Whether one foot's two key readings name a contact (S4 threshold)."""
    on_ground = (
        left.z <= ground_z + ground_height_cm
        and right.z <= ground_z + ground_height_cm
    )
    drift = math.sqrt(
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )
    return on_ground and drift <= position_tolerance_cm
