"""Overlay math (pose-video-overlay S1..S3): color rule and full-frame projection.

The projection is the same pinhole HMR2's demo renders the mesh with:
``pixel = focal * (point / depth) + frame centre``. The world side is the
domain's (Z-up centimetres); the engine side is Y-down metres. Both
directions use the measured axis mapping the adapter applies to
``root_translation`` (``(tx, ty, tz) -> (x, y, z) = (tx, tz, -ty) * 100``),
so the overlay's inverse is consistent with capture by construction. Exact
shades are pinned here so the widget lands them unchanged.
"""

from __future__ import annotations

from aimation_actor.core.models import JointData, ProjectionCamera, Skeleton, Vector3
from aimation_actor.core.overlay import (
    BLUE,
    DOT_BORDER,
    DOT_FILL,
    RED,
    YELLOW,
    bone_side,
    colored_bone_segments,
    joint_dots,
    position_to_pixels,
)


def test_the_color_rule_reads_sides_from_the_child_joint_prefix() -> None:
    assert bone_side("L_Knee") == "left"
    assert bone_side("R_Hip") == "right"
    assert bone_side("Pelvis") == "trunk"
    assert bone_side("Spine_2") == "trunk"
    assert bone_side("Head") == "trunk"
    assert bone_side("Main") == "trunk"


def test_the_side_colors_and_dot_shades_are_pinned() -> None:
    assert RED == (199, 30, 30)
    assert BLUE == (30, 79, 199)
    assert YELLOW == (232, 187, 20)
    assert DOT_BORDER == (70, 70, 70)
    assert DOT_FILL == (210, 210, 210)


def test_a_point_lands_on_full_frame_pixels_by_the_pinhole_rule() -> None:
    camera = ProjectionCamera(focal_px=5000.0, width_px=1280, height_px=720)
    # Domain (Z-up cm): 50 cm right of the camera axis, 5 m of depth, 1 m up.
    # Engine metres: X = 0.5, Y = -1.0 (1 m up in a Y-down frame), Z = 5.0.
    pixel = position_to_pixels(Vector3(x=50.0, y=500.0, z=100.0), camera)
    assert pixel == (1140.0, -640.0)  # +500 px right of centre, 1000 px above it


def test_the_projection_inverts_the_adapter_field_mapping() -> None:
    """Engine [tx, ty, tz] -> domain (x, y, z) = (tx, tz, -ty) * 100 — and back."""
    camera = ProjectionCamera(focal_px=5000.0, width_px=1280, height_px=720)
    engine_m = (0.1, -1.0, 5.0)  # tx right, ty up in the engine's frame, tz depth
    domain_cm = Vector3(
        x=engine_m[0] * 100.0, y=engine_m[2] * 100.0, z=-engine_m[1] * 100.0
    )
    pixel = position_to_pixels(domain_cm, camera)
    cx, cy = 640.0, 360.0
    assert pixel == (
        5000.0 * engine_m[0] / engine_m[2] + cx,
        5000.0 * engine_m[1] / engine_m[2] + cy,
    )


def test_a_colored_bone_list_skips_the_ground_root_and_colors_by_child() -> None:
    positions = {
        "Main": Vector3(),
        "Pelvis": Vector3(x=0, y=0, z=95.0),
        "L_Hip": Vector3(x=-10.0, y=0, z=95.0),
        "R_Hip": Vector3(x=10.0, y=0, z=95.0),
        "L_Knee": Vector3(x=-12.0, y=0, z=50.0),
        "Neck": Vector3(x=0, y=0, z=140.0),
        "Head": Vector3(x=0, y=0, z=150.0),
    }
    segments = colored_bone_segments(_skeleton(), positions)
    colors = {f"{parent}->{child}": color for parent, child, color in segments}
    assert colors == {
        "Pelvis->L_Hip": RED,
        "Pelvis->R_Hip": BLUE,
        "L_Hip->L_Knee": RED,
        "Pelvis->Neck": YELLOW,
        "Neck->Head": YELLOW,
    }


def test_dots_mark_every_drawn_joint_but_not_the_ground_root() -> None:
    positions = {
        "Main": Vector3(),
        "Pelvis": Vector3(x=0, y=0, z=95.0),
        "L_Hip": Vector3(x=-10.0, y=0, z=95.0),
        "R_Hip": Vector3(x=10.0, y=0, z=95.0),
    }
    joints = joint_dots(_skeleton(), positions)
    assert {joint[0] for joint in joints} == {"Pelvis", "L_Hip", "R_Hip"}
    # The dots share the segments' endpoint world positions, so the widget
    # converts each exactly once with the same projection rule.
    world = {joint[0]: joint[1] for joint in joints}
    assert world["Pelvis"] == Vector3(x=0, y=0, z=95.0)


def _skeleton() -> Skeleton:
    parents = {
        "Main": None,
        "Pelvis": "Main",
        "L_Hip": "Pelvis",
        "R_Hip": "Pelvis",
        "L_Knee": "L_Hip",
        "Neck": "Pelvis",
        "Head": "Neck",
    }
    return Skeleton(
        joints=tuple(
            JointData(name=name, parent=parent) for name, parent in parents.items()
        )
    )
