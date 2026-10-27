"""Tests for the 3D skeleton viewport (plan §3.B; AGENTS.md stack choice).

Drawing needs a live OpenGL context, so the pixels stay a manual check. What is
pinned here is the part that can regress silently: the pose-to-segments plumbing
and the camera fitting that keeps the figure on screen.
"""

from __future__ import annotations

import pytest

from aimation_actor.adapters.gui.viewport_3d import SkeletonViewport, fit_view, to_view
from aimation_actor.core.models import JointData, Skeleton, Vector3
from aimation_actor.core.services import neutral_pose


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="Head", parent="Pelvis", rest_translation=Vector3(z=70.0)),
        )
    )


def test_fitting_a_figure_finds_its_centre_and_half_size() -> None:
    points = [Vector3(x=-50.0), Vector3(x=50.0), Vector3(z=180.0)]

    center, half_size = fit_view(points, margin=0.1)

    assert (center.x, center.y, center.z) == pytest.approx((0.0, 0.0, 90.0))
    assert half_size == pytest.approx(99.0)  # the widest half-extent, plus margin


def test_fitting_a_single_point_keeps_a_usable_size() -> None:
    center, half_size = fit_view([Vector3(z=100.0)])

    assert center.z == pytest.approx(100.0)
    assert half_size == pytest.approx(1.0)  # a floor, so the view never collapses


def test_the_view_mapping_is_a_rotation_and_not_a_mirror() -> None:
    # The domain is Z-up and OpenGL is Y-up, so this is R_x(-90 degrees).
    # `(x, z, y)` would leave the figure upright but swap left and right, which an
    # animator would read backwards without anything looking wrong.
    assert to_view(Vector3(x=1.0, y=2.0, z=3.0)) == pytest.approx((1.0, 3.0, -2.0))


def test_the_view_mapping_sends_domain_up_to_screen_up() -> None:
    # The invariant that keeps the figure standing: +Z in the domain is +Y on screen.
    assert to_view(Vector3(z=1.0))[1] == pytest.approx(1.0)

    # And depth goes away from the eye (OpenGL looks down -Z), so a point further
    # along +Y in the domain must not land in front of the camera.
    assert to_view(Vector3(y=1.0))[2] == pytest.approx(-1.0)


def test_fitting_nothing_keeps_a_usable_size() -> None:
    assert fit_view(()) == (Vector3(), 1.0)


def test_the_viewport_shows_the_segments_of_the_pose_it_is_given(qtbot) -> None:
    viewport = SkeletonViewport()
    qtbot.addWidget(viewport)
    skeleton = _skeleton()

    viewport.set_pose(skeleton, neutral_pose(skeleton))

    assert len(viewport.segments) == 2  # the root has no parent, so no segment
    start, end = viewport.segments[0]
    assert (start.z, end.z) == pytest.approx((0.0, 100.0))


def test_the_viewport_accepts_a_session_without_a_rig(qtbot) -> None:
    # Until M5 supplies the production rig a session can legitimately have none:
    # the preview must degrade to nothing drawn, not crash (NFR-03).
    viewport = SkeletonViewport()
    qtbot.addWidget(viewport)

    viewport.set_pose(Skeleton(joints=()), {})

    assert viewport.segments == ()


def test_the_viewport_names_a_missing_rig_and_clears_it_when_one_arrives(qtbot) -> None:
    # A blank pane would read as a broken app, so it has to say which blank it is.
    viewport = SkeletonViewport()
    qtbot.addWidget(viewport)
    skeleton = _skeleton()

    viewport.set_pose(Skeleton(joints=()), {})
    assert "No rig" in viewport.notice_label.text()

    viewport.set_pose(skeleton, neutral_pose(skeleton))
    assert "No rig" not in viewport.notice_label.text()
