"""The video overlay's layout and coloring math (pose-video-overlay S1..S3).

Pure domain-side math, no Qt and no engines: the widget converts these
results to paint calls. Nothing here projects — the projection happens in
the engine worker, where the engine's own SMPL joints and camera live
(``WorldPose.projected``: joint name to full-frame ``(x, y)`` pixels). This
module colors and lays that mapping out: bones follow the child joint's
``L_``/``R_`` prefix (``core.production_skeleton``'s naming), joints without
a side prefix are trunk/head, the ground root ``Main`` is never drawn (it is
not on the person), and a partial projection simply drops its missing bones.
"""

from __future__ import annotations

from collections.abc import Mapping

from aimation_actor.core.models import Skeleton

__all__ = [
    "BLUE",
    "DOT_BORDER",
    "DOT_FILL",
    "RED",
    "YELLOW",
    "bone_side",
    "overlay_items",
]

RED = (199, 30, 30)
BLUE = (30, 79, 199)
YELLOW = (232, 187, 20)
DOT_BORDER = (70, 70, 70)
DOT_FILL = (210, 210, 210)

_BoneSegment = tuple[tuple[float, float], tuple[float, float], tuple[int, int, int]]
_JointDot = tuple[tuple[float, float], tuple[int, int, int], tuple[int, int, int]]


def bone_side(joint_name: str) -> str:
    """The color group of ``joint_name``: ``left``, ``right`` or ``trunk``."""
    if joint_name.startswith("L_"):
        return "left"
    if joint_name.startswith("R_"):
        return "right"
    return "trunk"


def overlay_items(
    skeleton: Skeleton, projected: Mapping[str, tuple[float, float]]
) -> tuple[tuple[_BoneSegment, ...], tuple[_JointDot, ...]]:
    """The render-ready overlay: colored bone segments plus joint dots, in pixels.

    ``projected`` is the engine's own projection of its joints onto the
    captured frame (``WorldPose.projected``). Every dot is a drawn joint's
    pixel position; the widget converts nothing itself.
    """
    root = skeleton.root().name
    side_colors = {"left": RED, "right": BLUE, "trunk": YELLOW}

    segments: list[_BoneSegment] = []
    dots: list[_JointDot] = []
    for joint in skeleton.joints:
        joint_projected = projected.get(joint.name) if joint.name != root else None
        if joint_projected is None:
            continue
        dots.append((joint_projected, DOT_BORDER, DOT_FILL))
        parent_projected = (
            projected.get(joint.parent)
            if joint.parent is not None and joint.parent != root
            else None
        )
        if parent_projected is not None:
            segments.append(
                (
                    parent_projected,
                    joint_projected,
                    side_colors[bone_side(joint.name)],
                )
            )
    return tuple(segments), tuple(dots)
