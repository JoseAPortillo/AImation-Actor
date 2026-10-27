"""High-frequency jitter damping on generated rows (R3).

The user's diagnosis of the "afinar" agenda item: the noise appears when
generating inbetweens, never on the Golden Poses themselves, and it is
frame-to-frame tremor — the same pose shaking. That is the diffusion's
free rows oscillating around their own trend; capture is innocent. The
tool's answer is the rotational analog of M8's ``smooth_root_trajectory``:
at adoption, blend every FREE row's joint rotations toward a binomial
kernel of its neighbours, while the anchors (human keys and reasserted
guides) survive byte-exact — the same FR-GEN-01 contract feathering and
pinning keep.

Why a binomial kernel (for radius r the weights C(2r, r+d), e.g.
``[1 4 6 4 1]/16``): it is the discrete Gaussian — the same shape as M8's
quarter-half-quarter pass — so it halves period-2 alternation (the tremor
signature) and leaves constant-velocity arcs essentially where they are.
Quaternions are averaged componentwise after being sign-aligned to the
centre sample (``q`` and ``-q`` are one rotation; an unaligned mean
cancels), then normalised (nlerp) and reached by ``slerp`` with a blend
``strength`` so the animator's content is eased, not replaced.

Channels stay split like the passes around it: ``Main``'s rotation is
identity by domain invariant and never filtered, translations belong to
root smoothing and pinning, and joints missing from the neighbourhood
window keep their value. Radius/strength are provisional until the R3 T3
probe measures them on the real clip (``odd/tasks/r3-generated-jitter.md``).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

from aimation_actor.core.models import Keyframe, Quaternion, TimelineState
from aimation_actor.core.resampling import slerp

#: Neighbour frames on each side a free row averages over. Binomial, so
#: radius 2 is the [1 4 6 4 1] kernel (T3 measures).
JITTER_KERNEL_RADIUS = 2
#: How far a free row moves toward its kernel mean per adoption
#: (1.0 = replace with the mean). 0.75 keeps a quarter of the model's own
#: frame value as authorship (T3 measures).
JITTER_DAMP_STRENGTH = 0.75
#: A row whose blend turns out this small is not rewritten at all: it
#: keeps its Keyframe object and the count stays honest.
JITTER_EPSILON_DEG = 0.01


def _angle_deg(left: Quaternion, right: Quaternion) -> float:
    """The rotation angle between two unit quaternions, in degrees."""
    dot = (
        left.w * right.w
        + left.x * right.x
        + left.y * right.y
        + left.z * right.z
    )
    return math.degrees(2.0 * math.acos(min(1.0, max(-1.0, abs(dot)))))


def _kernel_mean(
    center: Quaternion, samples: list[tuple[float, Quaternion]]
) -> Quaternion | None:
    """The sign-aligned, weighted, normalised mean of ``samples``.

    Every neighbour quaternion is flipped when it lies in the opposite
    cover of ``center`` (same rotation, opposite sign), then accumulated
    with its kernel weight; the result is normalised (nlerp). A fully
    cancelled sum returns ``None`` — there is no direction to damp toward.
    """
    total = [0.0, 0.0, 0.0, 0.0]
    for weight, quat in samples:
        sign = -1.0 if (center.w * quat.w + center.x * quat.x
                        + center.y * quat.y + center.z * quat.z) < 0.0 else 1.0
        total[0] += weight * sign * quat.w
        total[1] += weight * sign * quat.x
        total[2] += weight * sign * quat.y
        total[3] += weight * sign * quat.z
    norm = math.sqrt(sum(component * component for component in total))
    if norm < 1e-9:
        return None
    return Quaternion(*(component / norm for component in total))


def damp_generated_jitter(
    timeline: TimelineState,
    anchors: Sequence[int],
    *,
    radius: int = JITTER_KERNEL_RADIUS,
    strength: float = JITTER_DAMP_STRENGTH,
) -> tuple[TimelineState, int]:
    """Blend the rows between ``anchors`` toward their local trend.

    ``anchors`` are the frames holding captured poses (human keys plus
    reasserted guides), in any order; anchor rows present in the timeline
    are never rewritten, but they do serve as filter context for their
    free neighbours. Every free row averages its joint rotations over the
    ``[centre - radius, centre + radius]`` window with binomial weights
    renormalised over the neighbours actually present — a row at the
    sequence edge still dampens — and needs at least three samples
    (itself plus two neighbours) to filter at all. The blend is
    ``slerp(original, kernel_mean, strength)``; blends smaller than the
    epsilon leave the row's ``Keyframe`` object untouched, so callers can
    compare keyframe identity freely. ``Main`` is never filtered and no
    translation ever moves. Returns the state and how many rows were
    rewritten.
    """
    if radius < 1 or strength <= 0.0:
        return timeline, 0
    root = timeline.skeleton.root().name
    rows = {keyframe.frame: keyframe for keyframe in timeline.keyframes}
    anchored = {frame for frame in anchors if frame in rows}
    # Binomial weights C(2*radius, radius + d) for offsets -radius..radius.
    weights = {
        d: math.comb(2 * radius, radius + d) for d in range(-radius, radius + 1)
    }

    damped = 0
    keyframes: list[Keyframe] = []
    for keyframe in timeline.keyframes:
        if keyframe.frame in anchored:
            keyframes.append(keyframe)
            continue
        pose = dict(keyframe.pose)
        changed = False
        for name, entry in keyframe.pose.items():
            if name == root:
                continue  # S4: Main carries no rotation to damp
            samples: list[tuple[float, Quaternion]] = []
            for offset, weight in weights.items():
                neighbour = rows.get(keyframe.frame + offset)
                if neighbour is None:
                    continue
                neighbour_entry = neighbour.pose.get(name)
                if neighbour_entry is None:
                    samples = []  # a window the joint does not exist across
                    break
                samples.append((weight, neighbour_entry.rotation))
            if len(samples) < 3:
                continue  # no trend to damp toward
            mean = _kernel_mean(entry.rotation, samples)
            if mean is None:
                continue
            blended = slerp(entry.rotation, mean, strength)
            if _angle_deg(entry.rotation, blended) < JITTER_EPSILON_DEG:
                continue  # already smooth: damping never adds motion
            pose[name] = dataclasses.replace(entry, rotation=blended)
            changed = True
        if changed:
            damped += 1
            keyframes.append(dataclasses.replace(keyframe, pose=pose))
        else:
            keyframes.append(keyframe)
    if not damped:
        return timeline, 0
    return dataclasses.replace(timeline, keyframes=tuple(keyframes)), damped
