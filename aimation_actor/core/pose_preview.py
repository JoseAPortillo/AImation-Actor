"""The imported pose's front-view preview (FR-IMP-04).

A refined FBX carries poses, not cameras: it knows nothing about where the
person stood in the video frame. The import overlay therefore draws an
HONEST APPROXIMATION — the pose's FK world positions seen from the front
(domain ``x`` across, domain ``z`` up), never a claimed capture alignment
(that stays the engine projection's job, S1).

The rule, stated once here so the controller and tests read the same
geometry:

- the figure's scale is fixed by the BIND's reach (the neutral pose's height),
  so a crouch really renders shorter than a stand; the bind fills ~85 % of
  the frame's height;
- the bind's ground (its lowest point, the feet at rest) sits at 95 % of the
  frame's height — a pose raised above it (a jump, a sit) floats there,
  because that elevation IS in the data;
- the bind's horizontal center maps to the frame's center, so the pose's own
  ``x`` (the root motion the captures recorded) walks across the clip.

A skeleton with no vertical reach, or a frame with no size, projects nothing:
the preview never invents a figure out of degenerate input.
"""

from __future__ import annotations

from collections.abc import Mapping

from aimation_actor.core.kinematics import joint_world_positions
from aimation_actor.core.models import JointPose, Skeleton

__all__ = ["BODY_FILL", "FLOOR_AT", "preview_projection"]

#: How much of the frame's height the neutral bind figure occupies.
BODY_FILL = 0.85
#: Where the figure's lowest point sits, as a fraction of the frame's height.
FLOOR_AT = 0.95


def preview_projection(
    skeleton: Skeleton,
    pose: Mapping[str, JointPose],
    *,
    frame_size: tuple[int, int],
) -> dict[str, tuple[float, float]]:
    """Joint name -> ``(x, y)`` pixels for the pose drawn over a frame.

    ``frame_size`` is the clip's native ``(width, height)`` — the same
    full-frame space the engine projections use, so the overlay widget
    letterboxes the preview exactly like the captures.
    """
    width, height = frame_size
    if width <= 0 or height <= 0:
        return {}
    bind = joint_world_positions(skeleton, {})
    bind_reach = _span(axis_z(bind.values()))
    if bind_reach <= 0.0:
        return {}
    scale = BODY_FILL * height / bind_reach
    anchor_x = sum(axis_x(bind.values())) / len(bind)
    ground_z = min(axis_z(bind.values()))
    positions = joint_world_positions(skeleton, pose)
    return {
        name: (
            width / 2.0 + (point.x - anchor_x) * scale,
            FLOOR_AT * height - (point.z - ground_z) * scale,
        )
        for name, point in positions.items()
    }


def _span(values) -> float:
    values = list(values)
    return max(values) - min(values) if values else 0.0


def axis_z(points) -> list[float]:
    return [point.z for point in points]


def axis_x(points) -> list[float]:
    return [point.x for point in points]
