"""Retarget motion math (SDD §14, task 2.8).

The pure-stdlib transformation pipeline driven by a validated
:class:`RetargetMap`. Four deterministic passes over an immutable
:class:`NeutralMotion`:

① **Root height ratio** — when ``scale_source_height`` is on, a target height
   is present, and ``use_root_translation`` is enabled, the Hips translation
   is scaled by ``target/source`` root-to-ground height (source measured from
   the motion skeleton's rest chain).
②/③ **Per-bone rotation + scale** — each mapped bone gets its rotation
   composed via :func:`apply_rotation` (never fabricated from identity input)
   and its scale multiplied elementwise by the entry factor; *positions* of
   child bones are never touched.
④ **Foot-ground pass** — when ``foot_ik`` is on, Hips Y is lifted so the
   reference foot (contact-flagged tracks, else the lowest foot) rests on
   ground — purely translational, mirroring the cleanup clamp semantics.

The result passes ``validate_invariants()`` and is byte-deterministic.
"""

from __future__ import annotations

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.retargeting.map import RetargetMap
from aimation_actor_core.domain.retargeting.rotation import apply_rotation

#: The bone whose translation carries root scaling and the ground pass.
_ROOT_BONE = "Hips"
#: Ground-reference feet (canonical names, ADR-001).
_FOOT_BONES = ("LeftFoot", "RightFoot")
#: Contact-track key for a foot bone ("left_foot" / "right_foot" convention).
_CONTACT_TRACK_KEYS = {
    "LeftFoot": "left_foot",
    "RightFoot": "right_foot",
}


def retarget_motion(motion: NeutralMotion, retarget_map: RetargetMap) -> NeutralMotion:
    """Transform a neutral motion through the four retarget passes.

    Args:
        motion: The source :class:`NeutralMotion` (immutable).
        retarget_map: The validated retarget preset document.

    Returns:
        A new :class:`NeutralMotion` with the retarget applied; invariants
        validated and output deterministic (run twice -> byte-identical).
    """
    ratio: float | None = None
    if (
        retarget_map.scale_source_height
        and retarget_map.use_root_translation
        and retarget_map.target_root_to_ground_cm is not None
    ):
        source_ground = _source_root_to_ground_cm(motion)
        ratio = retarget_map.target_root_to_ground_cm / source_ground

    frames: list[Frame] = []
    for frame in motion.frames:
        transforms = dict(frame.pose.transforms)
        for source_name, entry in retarget_map.mapping.items():
            transform = transforms.get(source_name)
            if transform is None:
                continue  # bone not animated in this frame — leave untouched
            transforms[source_name] = transform.model_copy(
                update={
                    "rotation": apply_rotation(transform.rotation, entry),
                    "scale": (
                        transform.scale[0] * entry.scale[0],
                        transform.scale[1] * entry.scale[1],
                        transform.scale[2] * entry.scale[2],
                    ),
                }
            )
        if ratio is not None and _ROOT_BONE in transforms:
            hips = transforms[_ROOT_BONE]
            transforms[_ROOT_BONE] = hips.model_copy(
                update={
                    "translation": (
                        hips.translation[0] * ratio,
                        hips.translation[1] * ratio,
                        hips.translation[2] * ratio,
                    )
                }
            )
        if retarget_map.foot_ik:
            transforms = _foot_ground_pass(transforms, frame.frame, motion)
        frames.append(frame.model_copy(update={"pose": Pose(transforms=transforms)}))

    out = motion.model_copy(update={"frames": frames})
    out.validate_invariants()
    return out


def _source_root_to_ground_cm(motion: NeutralMotion) -> float:
    """Absolute rest-position height from a ground foot up to the root.

    The neutral skeleton's root-to-ground distance is the denominator of the
    height ratio (design: ``target_root_to_ground_cm`` is the numerator).
    """
    foot = next((f for f in _FOOT_BONES if f in motion.skeleton.bones), None)
    if foot is None:
        raise ValueError(
            "cannot scale source height: no foot bone in the motion skeleton"
        )
    total = 0.0
    bone: str | None = foot
    seen: set[str] = set()
    while bone is not None and bone in motion.skeleton.bones and bone not in seen:
        seen.add(bone)
        total += motion.skeleton.bones[bone].rest_position[1]
        bone = motion.skeleton.bones[bone].parent
    if total == 0.0:
        raise ValueError(
            "cannot scale source height: root-to-ground rest height is 0"
        )
    return abs(total)


def _foot_world_y(transforms: dict[str, Transform3D], motion: NeutralMotion, foot: str) -> float:
    """World Y of a foot: cumulative LOCAL translation up the parent chain."""
    y = 0.0
    bone: str | None = foot
    seen: set[str] = set()
    while bone is not None and bone in motion.skeleton.bones and bone not in seen:
        seen.add(bone)
        transform = transforms.get(bone)
        if transform is not None:
            y += transform.translation[1]
        else:
            y += motion.skeleton.bones[bone].rest_position[1]
        bone = motion.skeleton.bones[bone].parent
    return y


def _contact_at(motion: NeutralMotion, frame_number: int, foot: str) -> bool:
    """Whether ``foot`` is flagged in contact at ``frame_number``."""
    track = motion.contacts.get(_CONTACT_TRACK_KEYS[foot])
    if track is None:
        return False
    for sample in track.samples:
        if sample.frame == frame_number:
            return sample.contact
        if sample.frame > frame_number:
            break
    return False


def _foot_ground_pass(
    transforms: dict[str, Transform3D], frame_number: int, motion: NeutralMotion
) -> dict[str, Transform3D]:
    """Lift Hips Y so the reference foot rests on ground (translation-only).

    The reference is the contact-flagged foot when its track marks the frame in
    contact; otherwise the lowest foot. Feet already at/above ground need no
    lift; skeletons without both feet or without a Hips transform skip the pass.
    """
    feet = [f for f in _FOOT_BONES if f in motion.skeleton.bones]
    if not feet or _ROOT_BONE not in transforms:
        return transforms
    contact_feet = [f for f in feet if _contact_at(motion, frame_number, f)]
    reference_feet = contact_feet or feet
    penetration = min(_foot_world_y(transforms, motion, f) for f in reference_feet)
    if penetration >= 0.0:
        return transforms
    hips = transforms[_ROOT_BONE]
    updated = dict(transforms)
    updated[_ROOT_BONE] = hips.model_copy(
        update={
            "translation": (
                hips.translation[0],
                hips.translation[1] - penetration,
                hips.translation[2],
            )
        }
    )
    return updated