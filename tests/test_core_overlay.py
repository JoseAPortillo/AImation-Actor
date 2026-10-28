"""Overlay math (pose-video-overlay S1..S3): side coloring over projected joints.

The projection happens WHERE the truth lives: the HMR2 worker projects the
engine's own SMPL joints with the engine's own camera rule (the vendored
``perspective_projection``) and reports ``projected_joints`` as a mapping of
joint name to full-frame ``(x, y)`` pixels. This module colors and lays out
that mapping for the overlay widget: bones by the child joint's side rule,
joint dots' shades, the ground root ``Main`` never drawn. Exact shades are
pinned so the widget lands them unchanged.
"""

from __future__ import annotations

from aimation_actor.core.models import JointData, Skeleton
from aimation_actor.core.overlay import (
    BLUE,
    DOT_BORDER,
    DOT_FILL,
    RED,
    YELLOW,
    bone_side,
    overlay_items,
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


def test_bones_color_by_their_child_joint_and_the_ground_root_is_not_drawn() -> None:
    skeleton = _skeleton()
    projected = {
        "Main": (640.0, 900.0),  # the ground root projects off the person
        "Pelvis": (640.0, 360.0),
        "L_Hip": (604.0, 360.0),
        "R_Hip": (676.0, 360.0),
        "L_Knee": (592.0, 560.0),
        "Neck": (640.0, 220.0),
        "Head": (640.0, 180.0),
    }
    segments, dots = overlay_items(skeleton, projected)
    colors = {tuple(segment[:2]): segment[2] for segment in segments}
    assert colors == {
        ((640.0, 360.0), (604.0, 360.0)): RED,
        ((640.0, 360.0), (676.0, 360.0)): BLUE,
        ((604.0, 360.0), (592.0, 560.0)): RED,
        ((640.0, 360.0), (640.0, 220.0)): YELLOW,
        ((640.0, 220.0), (640.0, 180.0)): YELLOW,
    }
    assert ((640.0, 900.0), (640.0, 360.0)) not in colors  # no Main bone


def test_dots_mark_every_projected_joint_but_not_the_ground_root() -> None:
    skeleton = _skeleton()
    projected = {
        "Main": (640.0, 900.0),
        "Pelvis": (640.0, 360.0),
        "L_Hip": (604.0, 360.0),
        "R_Hip": (676.0, 360.0),
    }
    _segments, dots = overlay_items(skeleton, projected)
    centers = {dot[0] for dot in dots}
    assert centers == {(640.0, 360.0), (604.0, 360.0), (676.0, 360.0)}
    assert all(dot[1] == DOT_BORDER and dot[2] == DOT_FILL for dot in dots)


def test_a_partial_projection_drops_only_its_missing_bones() -> None:
    skeleton = _skeleton()
    segments, _dots = overlay_items(skeleton, {"Pelvis": (1.0, 1.0), "Neck": (2.0, 2.0)})
    assert [tuple(segment[:2]) for segment in segments] == [((1.0, 1.0), (2.0, 2.0))]
    _segments2, dots = overlay_items(skeleton, {"Pelvis": (1.0, 1.0)})
    assert {dot[0] for dot in dots} == {(1.0, 1.0)}


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
