"""Pure business logic: keyframe management and offset calculation.

Standard library only: this module may import the domain (``core.models``) and
nothing from ``ports/`` or ``adapters/``, and no third-party package.

Key management implements the timeline rules the UI relies on:

- a timeline carries **at most one key per frame** (spec ``FR-CAP-07``);
- keys stay ordered by frame, so navigation and export are deterministic;
- ``TimelineState`` is frozen, so every operation returns a **new** state and
  leaves the input untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from aimation_actor.core.models import (
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)

__all__ = [
    "build_production_pose",
    "clamp_frame",
    "find_key",
    "key_frames",
    "mark_pose",
    "neutral_pose",
    "next_key_frame",
    "previous_key_frame",
    "remove_pose",
]

_PELVIS = "Pelvis"


def key_frames(state: TimelineState) -> tuple[int, ...]:
    """The frame indices that carry a keyframe, sorted ascending and unique."""
    return tuple(sorted({keyframe.frame for keyframe in state.keyframes}))


def find_key(state: TimelineState, frame: int) -> Keyframe | None:
    """The keyframe at ``frame``, or ``None`` when the frame is empty."""
    for keyframe in state.keyframes:
        if keyframe.frame == frame:
            return keyframe
    return None


def mark_pose(state: TimelineState, frame: int, pose: Mapping[str, JointPose]) -> TimelineState:
    """Add or replace the pose at ``frame`` and return the new timeline.

    Re-marking an existing frame **overwrites** it, so a frame never holds two
    keys (spec ``FR-CAP-07``); the result is always sorted by frame.
    """
    replacement = Keyframe(frame=frame, pose=dict(pose))
    kept = [keyframe for keyframe in state.keyframes if keyframe.frame != frame]
    kept.append(replacement)
    kept.sort(key=lambda keyframe: keyframe.frame)
    return replace(state, keyframes=tuple(kept))


def remove_pose(state: TimelineState, frame: int) -> TimelineState:
    """Drop the key at ``frame``; removing an empty frame is a no-op."""
    kept = tuple(keyframe for keyframe in state.keyframes if keyframe.frame != frame)
    if len(kept) == len(state.keyframes):
        return state
    return replace(state, keyframes=kept)


def next_key_frame(state: TimelineState, frame: int) -> int | None:
    """The first keyed frame strictly after ``frame``, or ``None``."""
    later = [candidate for candidate in key_frames(state) if candidate > frame]
    return later[0] if later else None


def previous_key_frame(state: TimelineState, frame: int) -> int | None:
    """The last keyed frame strictly before ``frame``, or ``None``."""
    earlier = [candidate for candidate in key_frames(state) if candidate < frame]
    return earlier[-1] if earlier else None


def clamp_frame(state: TimelineState, frame: int) -> int:
    """``frame`` constrained to the timeline's ``[frame_start, frame_end]`` span."""
    low, high = state.frame_start, state.frame_end
    if high < low:  # empty/unset range: the start is the only valid frame.
        return low
    return max(low, min(high, frame))


def neutral_pose(skeleton: Skeleton) -> dict[str, JointPose]:
    """Every joint of ``skeleton`` at its bind: identity rotation, zero offset.

    This is the pose the 3D viewport shows on a frame without a Golden Pose
    (plan §3.B). Marking no longer writes it: per ``FR-CAP-07`` a frame whose pose
    was never extracted must not gain a key, so the placeholder M4 wrote was
    retired when the pipeline landed (M5, L5).
    """
    return {joint.name: JointPose(rotation=Quaternion.identity()) for joint in skeleton.joints}


def build_production_pose(pose: WorldPose, skeleton: Skeleton) -> dict[str, JointPose]:
    """Map a raw world-space ``pose`` onto ``skeleton``'s production hierarchy.

    The split follows the domain invariants:

    - the ground root is the **animator's world control** and carries the
      session-relative root displacement on all three axes;
    - ``Pelvis`` carries the residual local height after root displacement,
      with local ``x``/``y`` pinned to ``0``;
    - every other joint carries rotation only.

    Translations are offsets from each joint's ``rest_translation`` — the
    convention ``document._channel_values`` adds back when it writes the FBX
    ``Lcl Translation`` — and the ground root keeps an identity rotation,
    because global motion is a pure translation. The production skeleton must
    name its hip joint ``Pelvis``; a missing rotation falls back to the bind
    pose, so the result is always a full pose.
    """
    root = skeleton.root().name
    hip_height = pose.translation.z
    root_translation = pose.root_translation

    built: dict[str, JointPose] = {}
    for joint in skeleton.joints:
        rest = joint.rest_translation
        if joint.name == _PELVIS:
            translation = Vector3(
                x=-rest.x,
                y=-rest.y,
                z=hip_height - rest.z - root_translation.z,
            )
            rotation = pose.rotations.get(joint.name, Quaternion.identity())
        elif joint.name == root:
            translation = root_translation
            rotation = Quaternion.identity()
        else:
            translation = Vector3()
            rotation = (
                Quaternion.identity()
                if joint.name == root
                else pose.rotations.get(joint.name, Quaternion.identity())
            )
        built[joint.name] = JointPose(rotation=rotation, translation=translation)
    return built
