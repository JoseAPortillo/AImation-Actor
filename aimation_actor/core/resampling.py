"""The sampling-clock bridge: interpolation, resampling, and gap filling.

CondMDI generates at HumanML3D's 20 fps while the timeline runs at its own
rate (24 for video), so generated motion enters and leaves the timeline
through a clock ratio. This module is that bridge, engine-agnostic and standard
library only: it knows two rates, a dense pose sequence, and the S1 rule that
human keys are hard constraints a generated fill may never rewrite.

The generated-motion contract shared by every function here: ``dense[i]`` is
the pose at dense-clock frame ``i``; a target frame ``f`` samples the sequence
at the fractional dense index ``(f - frame_start) * source_fps / target_fps``.
Anchoring ``frame_start`` — not the timeline's origin — is what lets the
adapter fill each gap from its own engine call.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from aimation_actor.core.models import JointPose, Keyframe, Quaternion, TimelineState, Vector3

__all__ = [
    "fill_gap_synthetically",
    "interpolate_pose",
    "resample_dense_poses",
    "slerp",
]

#: Below this dot product the slerp angle is large enough that ``acos`` is
#: numerically reliable; above it, a normalized lerp avoids the ``acos`` knee.
_NLERP_THRESHOLD = 0.9995


def _normalized(quaternion: Quaternion) -> Quaternion:
    """``quaternion`` rescaled to unit length."""
    norm = math.sqrt(
        quaternion.w**2 + quaternion.x**2 + quaternion.y**2 + quaternion.z**2
    )
    if norm == 0.0:
        raise ValueError("cannot normalize a zero quaternion")
    return Quaternion(
        w=quaternion.w / norm,
        x=quaternion.x / norm,
        y=quaternion.y / norm,
        z=quaternion.z / norm,
    )


def slerp(origin: Quaternion, target: Quaternion, t: float) -> Quaternion:
    """The shortest-arc rotation a fraction ``t`` of the way from origin to target.

    ``t`` outside ``[0, 1]`` is clamped — this bridge interpolates, it never
    extrapolates. Antipodal quaternions name the *same* rotation (double
    cover): one of the pair is negated first so the arc is the short one.
    """
    if t <= 0.0:
        return origin
    if t >= 1.0:
        return target

    left, right = origin, target
    dot = left.w * right.w + left.x * right.x + left.y * right.y + left.z * right.z
    if dot < 0.0:
        right = Quaternion(w=-right.w, x=-right.x, y=-right.y, z=-right.z)
        dot = -dot

    if dot > _NLERP_THRESHOLD:
        # Nearly identical rotations: normalized lerp is numerically safer
        # than acos at the knee, where sin(theta) loses all precision.
        blended = Quaternion(
            w=left.w + t * (right.w - left.w),
            x=left.x + t * (right.x - left.x),
            y=left.y + t * (right.y - left.y),
            z=left.z + t * (right.z - left.z),
        )
        return _normalized(blended)

    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    origin_weight = math.sin((1.0 - t) * theta) / sin_theta
    target_weight = math.sin(t * theta) / sin_theta
    return Quaternion(
        w=origin_weight * left.w + target_weight * right.w,
        x=origin_weight * left.x + target_weight * right.x,
        y=origin_weight * left.y + target_weight * right.y,
        z=origin_weight * left.z + target_weight * right.z,
    )


def _lerp(origin: float, target: float, t: float) -> float:
    return origin + t * (target - origin)


def interpolate_pose(origin: JointPose, target: JointPose, t: float) -> JointPose:
    """The pose a fraction ``t`` between two keyed poses.

    Rotations follow the shortest slerp arc; translations blend linearly.
    ``t`` is clamped to ``[0, 1]``. A joint pose is a local transform, so this
    presumes both endpoints describe the *same* joint of the *same* skeleton —
    the callers' contract, not this function's to re-check.
    """
    clamped = min(1.0, max(0.0, t))
    return JointPose(
        rotation=slerp(origin.rotation, target.rotation, clamped),
        translation=Vector3(
            x=_lerp(origin.translation.x, target.translation.x, clamped),
            y=_lerp(origin.translation.y, target.translation.y, clamped),
            z=_lerp(origin.translation.z, target.translation.z, clamped),
        ),
    )


def resample_dense_poses(
    dense: Sequence[Mapping[str, JointPose]],
    source_fps: float,
    target_fps: float,
    *,
    frame_start: int,
) -> dict[int, dict[str, JointPose]]:
    """Dense motion at ``source_fps`` re-expressed per target-clock frame.

    The result maps each target frame whose sample time lies inside the dense
    span to a pose interpolated from its neighbouring dense samples (fractional
    indices included). Frames past the span are simply absent — extending
    motion the engine never made is this module's caller's decision, not a
    silent extrapolation. ``frame_start`` is the target-clock frame where
    ``dense[0]`` sits, so a per-gap engine call anchors itself at its own left
    key.
    """
    if source_fps <= 0.0 or target_fps <= 0.0:
        raise ValueError(
            f"frame rates must be positive, got source={source_fps} target={target_fps}"
        )
    if not dense:
        raise ValueError("cannot resample an empty motion")

    ratio = source_fps / target_fps  # dense frames per target frame
    last_index = len(dense) - 1
    last_offset = math.floor(last_index / ratio)

    covered: dict[int, dict[str, JointPose]] = {}
    for offset in range(last_offset + 1):
        position = offset * ratio
        lower = min(math.floor(position), last_index)
        fraction = position - lower
        from_pose = dense[lower]
        if lower >= last_index or fraction == 0.0:
            covered[frame_start + offset] = dict(from_pose)
            continue
        to_pose = dense[lower + 1]
        blended: dict[str, JointPose] = {}
        for name, origin_joint in from_pose.items():
            target_joint = to_pose.get(name, origin_joint)
            blended[name] = interpolate_pose(origin_joint, target_joint, fraction)
        covered[frame_start + offset] = blended
    return covered


def fill_gap_synthetically(
    timeline: TimelineState,
    start_frame: int,
    end_frame: int,
    poses_by_frame: Mapping[int, Mapping[str, JointPose]],
) -> TimelineState:
    """The S1 rule materialized: generated keys fill the gap, keys stay locked.

    ``start_frame`` and ``end_frame`` must both be keyed frames of
    ``timeline``; the open interval between them gains a key per empty frame,
    taken from ``poses_by_frame``. Poses landing on the keyed endpoints are
    ignored — the keys are hard constraints and win over anything generated —
    while poses reaching outside the span are rejected. Every frame of the
    interval must be either keyed or supplied: a hole is raised, never left
    silently.
    """
    if end_frame < start_frame:
        raise ValueError(f"the gap runs backwards: {start_frame} -> {end_frame}")
    for bound in (start_frame, end_frame):
        if bound not in {keyframe.frame for keyframe in timeline.keyframes}:
            raise ValueError(f"frame {bound} is not a keyed frame of the timeline")

    interval = range(start_frame + 1, end_frame)
    span = range(start_frame, end_frame + 1)
    keyed_frames = {keyframe.frame for keyframe in timeline.keyframes}
    # Poses landing on the keyed endpoints are simply never written (keys win,
    # S1); only motion reaching OUTSIDE the span is a caller error.
    extra = sorted(frame for frame in poses_by_frame if frame not in span)
    if extra:
        raise ValueError(
            "the generated motion reaches outside the locked span: "
            f"{extra[0]}..{extra[-1]} (locked span {start_frame}..{end_frame})"
        )
    missing = sorted(
        frame for frame in interval if frame not in keyed_frames and frame not in poses_by_frame
    )
    if missing:
        raise ValueError(
            f"the generated motion leaves {len(missing)} gap frame(s) empty: "
            f"{missing[0]}..{missing[-1]}"
        )

    generated = [
        Keyframe(frame=frame, pose=dict(poses_by_frame[frame]))
        for frame in interval
        if frame not in keyed_frames
    ]
    if not generated:
        return timeline
    kept = list(timeline.keyframes) + generated
    kept.sort(key=lambda keyframe: keyframe.frame)
    return replace(timeline, keyframes=tuple(kept))
