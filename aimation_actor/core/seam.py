"""Seam feathering between captured anchors and generated rows (R2).

The M9 probe measured it on the real clip: a captured anchor row at
164.8 deg (upper arm from vertical) with the engine's first content row at
114.5 — a ~50 deg snap at every anchor boundary, visible as a pop. The
model's free rows simply disagree with the capture, and no conditioning
knob moves them (M6 L23, M9 S5). What the tool CAN do at adoption: feather
the FREE rows adjacent to each anchor toward that anchor over a short
window, along the great arc (`resampling.slerp`), so the boundary reads as
a quick ease instead of a cut.

The guarantees mirror the fills it post-processes:

- anchor rows (human keys and reasserted guides) survive untouched — the
  same byte-exact contract FR-GEN-01 pins;
- only rotations move, and never the root's: ``Main``'s rotation is
  identity by domain invariant, and translations belong to the
  root-smoothing and pinning passes;
- content that already agrees with the anchor within ``threshold_deg`` is
  left exactly where it is — feathering never adds motion.

Window / strength / threshold are provisional until the R2 T3 probe
measures them against the real clip (``odd/tasks/r2-anchor-seam.md``).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

from aimation_actor.core.models import Keyframe, Quaternion, TimelineState
from aimation_actor.core.resampling import slerp

#: Rows on each side of an anchor that a seam may span (T3 measures).
SEAM_WINDOW_FRAMES = 4
#: Blend applied to the row directly against an anchor; it decays to zero
#: at the window edge (T3 measures).
SEAM_BLEND_STRENGTH = 0.8
#: Joint rotations closer than this to the anchor are already continuous
#: for the eye; touching them would only stir clean content (T3 measures).
SEAM_THRESHOLD_DEG = 30.0


def _angle_deg(left: Quaternion, right: Quaternion) -> float:
    """The rotation angle between two unit quaternions, in degrees."""
    dot = (
        left.w * right.w
        + left.x * right.x
        + left.y * right.y
        + left.z * right.z
    )
    return math.degrees(2.0 * math.acos(min(1.0, max(-1.0, abs(dot)))))


def feather_anchor_seams(
    timeline: TimelineState,
    anchors: Sequence[int],
    *,
    window: int = SEAM_WINDOW_FRAMES,
    strength: float = SEAM_BLEND_STRENGTH,
    threshold_deg: float = SEAM_THRESHOLD_DEG,
) -> tuple[TimelineState, int]:
    """Ease the rows adjacent to ``anchors`` toward those anchor poses.

    ``anchors`` are the frames holding captured poses (human keys plus
    reasserted guides), in any order; only frames actually present as rows
    act as boundaries. Between two consecutive boundaries the nearest one
    wins for every free row inside ``window``, blended with
    ``slerp(content, anchor, alpha)`` where ``alpha`` is ``strength`` at
    the anchor and decays linearly to nothing at the window edge. The
    timeline is never mutated: untouched rows keep their ``Keyframe``
    objects, so callers can compare keyframe identity freely. Returns the
    state and how many rows were rewritten.
    """
    root = timeline.skeleton.root().name
    rows = {keyframe.frame: keyframe for keyframe in timeline.keyframes}
    boundaries = sorted({frame for frame in anchors if frame in rows})

    plans: dict[int, tuple[dict, float]] = {}
    if window >= 1:
        for left, right in zip(boundaries, boundaries[1:], strict=False):
            for frame in range(left + 1, right):
                if frame not in rows:
                    continue
                distance_left = frame - left
                distance_right = right - frame
                if distance_left <= window and distance_left <= distance_right:
                    target, distance = left, distance_left
                elif distance_right <= window:
                    target, distance = right, distance_right
                else:
                    continue
                alpha = strength * (1.0 - distance / (window + 1.0))
                if alpha > 0.0:
                    plans[frame] = (rows[target].pose, alpha)

    corrected = 0
    keyframes: list[Keyframe] = []
    for keyframe in timeline.keyframes:
        plan = plans.get(keyframe.frame)
        if plan is None:
            keyframes.append(keyframe)
            continue
        anchor_pose, alpha = plan
        pose = dict(keyframe.pose)
        changed = False
        for name, entry in keyframe.pose.items():
            if name == root:
                continue  # S4: Main carries no rotation to feather
            target_entry = anchor_pose.get(name)
            if target_entry is None:
                continue  # nothing captured here for this joint to ease toward
            if _angle_deg(entry.rotation, target_entry.rotation) < threshold_deg:
                continue  # already continuous: feathering never adds motion
            pose[name] = dataclasses.replace(
                entry, rotation=slerp(entry.rotation, target_entry.rotation, alpha)
            )
            changed = True
        if changed:
            corrected += 1
            keyframes.append(dataclasses.replace(keyframe, pose=pose))
        else:
            keyframes.append(keyframe)
    if not corrected:
        return timeline, 0
    return dataclasses.replace(timeline, keyframes=tuple(keyframes)), corrected
