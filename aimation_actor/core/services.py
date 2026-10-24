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

from collections.abc import Iterable, Mapping, Sequence
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
    "smooth_root_path",
    "smooth_root_trajectory",
]

_PELVIS = "Pelvis"

#: M8 S5 root-jitter filter shape: two robust median-3 passes (they delete
#: single-frame spikes) followed by one quarter-half-quarter average (it
#: halves period-2 alternation and preserves linear motion exactly).
_MEDIAN_PASSES = 2


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


# --------------------------------------------------------------------------- #
# Root-jitter reduction (M8 S5)
# --------------------------------------------------------------------------- #


def smooth_root_path(
    values: Mapping[int, Vector3], anchors: Iterable[int]
) -> dict[int, Vector3]:
    """A jitter-reduced copy of a root-translation series (M8 S5).

    Frames listed in ``anchors`` — the original keyframes — keep their exact
    value. Every **contiguous run of interior frames bounded by an anchor on
    both sides** is replaced by a robust temporal filter per axis: two
    median-3 passes (they remove single-frame spikes) followed by one
    quarter-half-quarter average (it halves period-2 alternation and leaves
    linear motion unchanged, so real travel is not distorted). Runs without an
    anchor on one side are passed through untouched — smoothing needs both
    edges to know where the motion truly starts and ends.
    """
    anchored = set(anchors)
    out = dict(values)
    frames = sorted(values)
    index = 0
    total = len(frames)
    while index < total:
        if frames[index] in anchored:
            index += 1
            continue
        start = index
        while index < total and frames[index] not in anchored:
            index += 1
        stop = index
        # Bounded only when the frame before the run exists and is an anchor,
        # and the frame after the run exists and is an anchor too.
        if start == 0 or frames[start - 1] not in anchored:
            continue
        if stop == total or frames[stop] not in anchored:
            continue
        left = values[frames[start - 1]]
        right = values[frames[stop]]
        run = frames[start:stop]
        smoothed = _smooth_axes([values[frame] for frame in run], left, right)
        for frame, translation in zip(run, smoothed, strict=True):
            out[frame] = translation
    return out


def smooth_root_trajectory(
    timeline: TimelineState, anchors: Sequence[int]
) -> tuple[TimelineState, int]:
    """Smooth the root translation of non-anchor rows of a filled timeline.

    The original keyframes' pose objects survive untouched — the same
    guarantee the fill adoption makes — and rows only change when the filter
    actually edits them. Returns the new state and how many interior frames
    were rewritten.
    """
    root = timeline.skeleton.root().name
    poses = {keyframe.frame: dict(keyframe.pose) for keyframe in timeline.keyframes}
    path = {
        frame: pose[root].translation
        for frame, pose in poses.items()
        if root in pose
    }
    smoothed = smooth_root_path(path, anchors)
    rewritten = 0
    keyframes = []
    for keyframe in timeline.keyframes:
        entry = keyframe.pose.get(root)
        if entry is None or smoothed.get(keyframe.frame) == entry.translation:
            keyframes.append(keyframe)
            continue
        rewritten += 1
        pose = dict(keyframe.pose)
        pose[root] = replace(entry, translation=smoothed[keyframe.frame])
        keyframes.append(replace(keyframe, pose=pose))
    return (
        replace(timeline, keyframes=tuple(keyframes)),
        rewritten,
    )


def _smooth_axes(
    series: list[Vector3], left: Vector3, right: Vector3
) -> list[Vector3]:
    """The filter per axis over one interior run (never empty).

    ``left``/``right`` are the bounding anchor values: they pad the filter
    windows, so a boundary frame still sees the motion it really connects to.
    """
    smoothed_x = _smooth_series([value.x for value in series], left.x, right.x)
    smoothed_y = _smooth_series([value.y for value in series], left.y, right.y)
    smoothed_z = _smooth_series([value.z for value in series], left.z, right.z)
    return [
        Vector3(x=x, y=y, z=z)
        for x, y, z in zip(smoothed_x, smoothed_y, smoothed_z, strict=True)
    ]


def _smooth_series(series: list[float], left: float, right: float) -> list[float]:
    """Median-3 passes, then one quarter-half-quarter average.

    The anchor values pad every window: a boundary frame therefore averages
    with the key it connects to, which preserves linear motion exactly.
    """
    for _ in range(_MEDIAN_PASSES):
        padded = [left, *series, right]
        series = [sorted(padded[i : i + 3])[1] for i in range(len(series))]
    padded = [left, *series, right]
    return [
        (padded[i] + 2.0 * padded[i + 1] + padded[i + 2]) / 4.0
        for i in range(len(series))
    ]
