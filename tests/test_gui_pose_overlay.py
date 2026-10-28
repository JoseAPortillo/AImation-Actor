"""Tests for the video pane's PoseOverlay widget (pose-video-overlay T3).

The widget consumes exactly what ``CaptureController.overlay_snapshot_at``
returns — ``(segments, dots)`` already in the engine's full-frame pixels —
and maps those pixels onto itself with the same letterbox rule the video
surface uses to draw the frame. Painting is verified by really rendering
the widget into a blank image and sampling pixels, not by mocking.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage

from aimation_actor.adapters.gui.pose_overlay import (
    PoseOverlay,
    display_transform,
)
from aimation_actor.core.overlay import DOT_BORDER, DOT_FILL, RED


def _snapshot() -> tuple[tuple, tuple]:
    """One red horizontal bone and one dot, in full-frame pixels."""
    segments = (((10.0, 50.0), (90.0, 50.0), RED),)
    dots = (((50.0, 20.0), DOT_BORDER, DOT_FILL),)
    return segments, dots


def _render(widget: PoseOverlay, size: int = 100) -> QImage:
    """The widget painted over a fully transparent image, ready to sample."""
    widget.resize(size, size)
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    return image


def _is_red(color) -> bool:
    return color.alpha() > 0 and color.red() > 150 and color.green() < 90 and color.blue() < 90


def test_the_full_frame_is_letterboxed_into_the_widget(qtbot) -> None:
    # The video surface aspect-fits its frame on black; the overlay's pixel
    # mapping is that same rule, stated once here and used by paintEvent.
    assert display_transform(200, 100, 100, 100) == (0.5, 0.0, 25.0)  # wider: top/bottom bars
    assert display_transform(100, 200, 100, 100) == (0.5, 25.0, 0.0)  # taller: side bars
    assert display_transform(100, 100, 100, 100) == (1.0, 0.0, 0.0)  # exact fit
    assert display_transform(400, 200, 800, 400) == (2.0, 0.0, 0.0)  # up too


def test_a_snapshot_paints_its_segments_and_dots(qtbot) -> None:
    overlay = PoseOverlay()
    overlay.set_frame_size(100, 100)
    overlay.set_snapshot(_snapshot())
    image = _render(overlay)

    midpoint = image.pixelColor(50, 50)  # the middle of the red bone
    assert _is_red(midpoint)
    dot_center = image.pixelColor(50, 20)  # the dot's light-gray core
    assert dot_center.red() > 180 and dot_center.green() > 180 and dot_center.blue() > 180
    assert dot_center.alpha() > 0


def test_no_snapshot_paints_nothing(qtbot) -> None:
    overlay = PoseOverlay()
    overlay.set_frame_size(100, 100)
    image = _render(overlay)
    assert not any(
        _is_red(image.pixelColor(x, y)) for x in range(0, 100, 7) for y in range(0, 100, 7)
    )


def test_a_snapshot_without_a_frame_size_paints_nothing(qtbot) -> None:
    # Without the displayed frame's native size the widget cannot map source
    # pixels onto itself; drawing would be a guess, so it draws nothing.
    overlay = PoseOverlay()
    overlay.set_snapshot(_snapshot())
    image = _render(overlay)
    assert not any(
        _is_red(image.pixelColor(x, y)) for x in range(0, 100, 7) for y in range(0, 100, 7)
    )


def test_a_new_snapshot_replaces_the_previous_figure(qtbot) -> None:
    overlay = PoseOverlay()
    overlay.set_frame_size(100, 100)
    overlay.set_snapshot(_snapshot())
    moved = ((((10.0, 80.0), (90.0, 80.0), RED),), ())
    overlay.set_snapshot((moved[0], ()))
    image = _render(overlay)

    assert _is_red(image.pixelColor(50, 80))  # the new bone is there
    assert not _is_red(image.pixelColor(50, 50))  # the old one is gone


@pytest.mark.parametrize(
    ("snapshot", "frame_size"),
    [((((),), ()), None), (None, (100, 100))],
)
def test_empty_inputs_paint_nothing(snapshot, frame_size) -> None:
    overlay = PoseOverlay()
    if frame_size is not None:
        overlay.set_frame_size(*frame_size)
    overlay.set_snapshot(snapshot)
    image = _render(overlay)
    assert not any(
        _is_red(image.pixelColor(x, y)) for x in range(0, 100, 7) for y in range(0, 100, 7)
    )


def test_the_overlay_ignores_the_mouse(qtbot) -> None:
    # The skeleton must never steal a click or the keyboard from the player
    # pane beneath it.
    overlay = PoseOverlay()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_painting_happens_in_widget_coordinates_not_source_pixels(qtbot) -> None:
    # The projection is in FULL-FRAME pixels; the widget scales and offsets
    # them exactly like the surface's letterbox, so a bone through the frame's
    # middle lands through the widget's middle even when the widget is larger.
    overlay = PoseOverlay()
    overlay.resize(200, 100)
    overlay.set_frame_size(200, 100)
    overlay.set_snapshot(((((0.0, 50.0), (200.0, 50.0), RED),), ()))
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    overlay.render(image)
    assert _is_red(image.pixelColor(QPoint(100, 50)))
