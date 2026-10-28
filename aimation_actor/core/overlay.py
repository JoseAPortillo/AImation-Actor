"""The video overlay's projection and coloring math (pose-video-overlay S1..S3).

Pure domain-side math, no Qt and no engines: the widget converts these
results to paint calls. Nothing here invents camera data — the focal comes
from the engine's own full-frame projection (``ProjectionCamera`` on a
``WorldPose``); poses without one simply stay unprojected, and the overlay
reports that instead of drawing a guess.

Axis consistency (measured, T15/T12): the adapter maps the engine's camera
frame to the domain as ``tx, ty, tz -> (x, y, z) = (tx, tz, -ty) * 100``
(engine side Y-up metres, domain side Z-up centimetres). ``position_to_pixels``
is that mapping's inverse composed with the engine's pinhole rule, so
projecting the domain pose lands where the engine's own projection put the
person — same focal, same frame centre.

Bone coloring follows the production names (``core.production_skeleton``):
the child joint's ``L_``/``R_`` prefix gives the limb's side, and joints
without a side prefix (``Main`` excluded from drawing) are trunk/head.
"""

from __future__ import annotations

from collections.abc import Mapping

from aimation_actor.core.kinematics import joint_world_positions
from aimation_actor.core.models import JointPose, ProjectionCamera, Skeleton, Vector3

__all__ = [
    "BLUE",
    "DOT_BORDER",
    "DOT_FILL",
    "RED",
    "YELLOW",
    "bone_side",
    "colored_bone_segments",
    "joint_dots",
    "overlay_items",
    "position_to_pixels",
]

RED = (199, 30, 30)
BLUE = (30, 79, 199)
YELLOW = (232, 187, 20)
DOT_BORDER = (70, 70, 70)
DOT_FILL = (210, 210, 210)


def bone_side(joint_name: str) -> str:
    """The color group of ``joint_name``: ``left``, ``right`` or ``trunk``."""
    if joint_name.startswith("L_"):
        return "left"
    if joint_name.startswith("R_"):
        return "right"
    return "trunk"


def position_to_pixels(point: Vector3, camera: ProjectionCamera) -> tuple[float, float]:
    """Project a domain point (Z-up centimetres) onto the camera's full frame.

    Inverse of the adapter's field mapping (see module docstring), composed
    with the engine's pinhole projection around the frame centre. A depth at
    or behind the camera plane projects nowhere: ``None`` there would only
    shift the refusal to the painter, so this is a caller contract instead —
    captured poses sit in front of the camera by construction.
    """
    engine_x = point.x / 100.0
    engine_y_up = -point.z / 100.0  # Y-down metres: the domain's height goes up
    engine_depth = point.y / 100.0
    return (
        camera.focal_px * engine_x / engine_depth + camera.width_px / 2.0,
        camera.focal_px * engine_y_up / engine_depth + camera.height_px / 2.0,
    )


def colored_bone_segments(
    skeleton: Skeleton, world_positions: Mapping[str, Vector3]
) -> tuple[tuple[str, str, tuple[int, int, int]], ...]:
    """Parent/lab-child bone triples colored by the child joint's side.

    The ground root (``Main``) is not on the person, so its bone to ``Pelvis``
    is not drawn; every other parent→child pair is, and its color reads the
    *child* joint's name — ``L_`` bones are the subject's left elements, which
    is the convention an animator reads in Maya, not what a mirrored viewer
    happens to show.
    """
    root = skeleton.root().name
    side_colors = {"left": RED, "right": BLUE, "trunk": YELLOW}
    return tuple(
        (joint.parent, joint.name, side_colors[bone_side(joint.name)])
        for joint in skeleton.joints
        if joint.parent is not None and joint.parent != root
    )


def joint_dots(
    skeleton: Skeleton, world_positions: Mapping[str, Vector3]
) -> tuple[tuple[str, Vector3], ...]:
    """The joints that carry a dot (S3): every drawn joint but the ground root."""
    root = skeleton.root().name
    return tuple(
        (joint.name, world_positions[joint.name])
        for joint in skeleton.joints
        if joint.name != root and joint.name in world_positions
    )


def overlay_items(
    skeleton: Skeleton, pose: Mapping[str, JointPose], camera: ProjectionCamera
) -> tuple[
    tuple[tuple[tuple[float, float], tuple[float, float], tuple[int, int, int]], ...],
    tuple[tuple[tuple[float, float], tuple[int, int, int], tuple[int, int, int]], ...],
]:
    """The render-ready overlay: colored segments plus joint dots, in pixels.

    The world positions are resolved once here (``kinematics`` owns FK), so
    the widget paints tuples straight away and never re-walks the hierarchy.
    Every dot is a drawn joint converted with the same projection rule as the
    segment endpoints around it.
    """
    positions = joint_world_positions(skeleton, pose)
    segments = tuple(
        (
            position_to_pixels(positions[parent], camera),
            position_to_pixels(positions[child], camera),
            color,
        )
        for parent, child, color in colored_bone_segments(skeleton, positions)
        if child in positions and parent in positions
    )
    dots = tuple(
        (position_to_pixels(positions[name], camera), DOT_BORDER, DOT_FILL)
        for name, _world in joint_dots(skeleton, positions)
    )
    return segments, dots
