"""Keypoints3D → NeutralMotion converter (REQ-1).

Pure deterministic math: normalized [0,1] 3D keypoints → a ``NeutralMotion``
document in scene centimetres based on a person-height heuristic (default
~172 cm, overridable). Image y-down is flipped to the scene up-Y axis, so the
nose ends up above the ankles. Detected COCO labels are mapped to neutral
bones, absolute positions are derived, then abs→local offsets are computed
against the parent (identity rotation — IK is deferred). Missing or invalid
labels keep that bone's neutral rest offset and never fail; empty input
yields an empty ``NeutralMotion`` that still carries the default skeleton.
"""

from __future__ import annotations

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D
from aimation_actor_core.domain.animation.mapping import COCO_TO_NEUTRAL
from aimation_actor_core.domain.animation.neutral_motion import NeutralMeta, NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

#: Person-height heuristic used to upscale normalized keypoints into cm.
DEFAULT_PERSON_HEIGHT_CM = 172.0

#: Frame rate for deriving ``Frame.time = frame / fps`` (deliberate fixed 24).
_FPS = 24.0


def _abs_positions(frame: Keypoints3D, height: float) -> dict[str, tuple[float, float, float]]:
    """Compute the absolute scene position (cm) of every skeleton bone.

    Detected COCO landmarks are placed at their normalized keypoint scaled by
    ``height``, with the image y-down axis flipped to scene up-Y (``1 - y``).
    ``Hips`` is the midpoint of the two hip landmarks when both are present;
    otherwise it falls back to its rest (neutral) offset. Undetected bones are
    walked from their parent using their rest offset, so their local output
    preserves the neutral pose.
    """
    kps = {kp.label: kp for kp in frame.keypoints}

    # Direct distal-end mappings (exact COCO keys, design D2).
    detected: dict[str, tuple[float, float, float]] = {}
    for coco_label, bone_name in COCO_TO_NEUTRAL.items():
        kp = kps.get(coco_label)
        if kp is not None:
            detected[bone_name] = (kp.x * height, (1.0 - kp.y) * height, kp.z * height)

    # Derived Hips = midpoint of both hips (kept rest when a hip is missing).
    left_hip = kps.get("left_hip")
    right_hip = kps.get("right_hip")
    if left_hip is not None and right_hip is not None:
        detected["Hips"] = (
            (left_hip.x + right_hip.x) / 2.0 * height,
            ((1.0 - left_hip.y) + (1.0 - right_hip.y)) / 2.0 * height,
            (left_hip.z + right_hip.z) / 2.0 * height,
        )

    # Walk any bone without detection up from its (already-resolved) parent,
    # accumulating the neutral rest offset. Parents-before-children order
    # guarantees the parent's absolute position is available on first pass.
    for name, bone in DEFAULT_NEUTRAL_SKELETON.bones.items():
        if name in detected:
            continue
        parent = bone.parent
        if parent is None:
            detected[name] = (0.0, 0.0, 0.0)
        else:
            px, py, pz = detected[parent]
            rx, ry, rz = bone.rest_position
            detected[name] = (px + rx, py + ry, pz + rz)

    return detected


def _build_frame(
    frame: Keypoints3D,
    height: float,
    only_local: bool,
) -> Frame:
    """Convert a single ``Keypoints3D`` frame into a neutral ``Frame``."""
    abs_pos = _abs_positions(frame, height)

    transforms: dict[str, Transform3D] = {}
    for name, bone in DEFAULT_NEUTRAL_SKELETON.bones.items():
        x, y, z = abs_pos[name]
        if only_local and bone.parent is not None:
            px, py, pz = abs_pos[bone.parent]
            translation = (x - px, y - py, z - pz)
        else:
            translation = (x, y, z)
        # Transform3D defaults rotation=(1,0,0,0) and scale=(1,1,1) — identity
        # (IK deferred, design D5).
        transforms[name] = Transform3D(translation=translation)

    # Frame.confidence = mean joint confidence (producer convention), or None.
    confidences = [kp.confidence for kp in frame.keypoints]
    confidence: float | None = sum(confidences) / len(confidences) if confidences else None

    frame_number = frame.frame_index + 1  # 0-based → 1-based (spec-pinned)
    return Frame(
        frame=frame_number,
        time=frame_number / _FPS,
        pose=Pose(transforms=transforms),
        confidence=confidence,
    )


def convert_keypoints_to_motion(
    keypoints: list[Keypoints3D],
    *,
    person_height_cm: float = DEFAULT_PERSON_HEIGHT_CM,
    only_local: bool = True,
) -> NeutralMotion:
    """Convert a list of 3D keypoints into a :class:`NeutralMotion`.

    Deterministic: ``abs = normalized * height``; ``only_local=True`` derives
    ``local = abs(child) - abs(parent)`` (``False`` leaves absolute scene
    positions); identity rotation; ``Frame.frame = frame_index + 1``;
    ``Frame.time = frame / 24.0``; ``duration_frames = max(frame)``. Missing or
    invalid labels keep the bone's rest offset (never fail). Empty input
    returns an empty ``NeutralMotion`` that still carries the default skeleton.
    Always ends with ``validate_invariants()`` (raises only on a bug).
    """
    frames = [_build_frame(kp, person_height_cm, only_local) for kp in keypoints]
    duration = max((f.frame for f in frames), default=0)
    motion = NeutralMotion(
        meta=NeutralMeta(duration_frames=duration, source_type="video-to-motion"),
        skeleton=DEFAULT_NEUTRAL_SKELETON,
        frames=frames,
    )
    motion.validate_invariants()
    return motion
