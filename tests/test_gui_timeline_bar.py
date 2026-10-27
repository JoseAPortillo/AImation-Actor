"""Tests for the timeline scrubber (spec FR-CAP-03, FR-CAP-04; plan §3.A)."""

from __future__ import annotations

import pytest

from aimation_actor.adapters.gui.timeline_bar import TimelineBar, frame_x


def test_the_readout_reports_the_current_and_total_frames(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)

    bar.set_timeline(frame_start=0, frame_end=119, fps=24.0)
    bar.set_frame(15)

    assert bar.frame == 15
    assert bar.total_frames == 120
    assert bar.frame_label.text() == "Frame 15 / 120"
    assert bar.fps_label.text() == "24 fps"


def test_a_frame_outside_the_clip_is_clamped(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)
    bar.set_timeline(frame_start=0, frame_end=23, fps=24.0)

    bar.set_frame(999)
    assert bar.frame == 23

    bar.set_frame(-5)
    assert bar.frame == 0


def test_the_range_follows_the_timeline(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)

    bar.set_timeline(frame_start=5, frame_end=30, fps=25.0)

    assert (bar.slider.minimum(), bar.slider.maximum()) == (5, 30)
    assert bar.fps_label.text() == "25 fps"


def test_moving_the_slider_asks_for_that_frame(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)
    bar.set_timeline(frame_start=0, frame_end=100, fps=24.0)
    asked: list[int] = []
    bar.frame_requested.connect(asked.append)

    bar.slider.setValue(42)

    assert asked == [42]


def test_showing_a_frame_never_asks_for_it(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)
    bar.set_timeline(frame_start=0, frame_end=100, fps=24.0)
    asked: list[int] = []
    bar.frame_requested.connect(asked.append)

    bar.set_frame(42)
    bar.set_timeline(frame_start=0, frame_end=50, fps=24.0)

    # Programmatic updates must not bounce back as seeks, or the controller's own
    # reporting would loop into another seek.
    assert asked == []


def test_the_key_markers_follow_the_timeline_keys(qtbot) -> None:
    bar = TimelineBar()
    qtbot.addWidget(bar)

    bar.set_keys((15, 42))

    assert bar.key_strip.keys == (15, 42)
    assert bar.key_strip.isVisible() or bar.key_strip.parent() is bar


def test_frames_map_across_the_strip() -> None:
    assert frame_x(0, 0, 119, 119) == pytest.approx(0.0)
    assert frame_x(119, 0, 119, 119) == pytest.approx(119.0)
    assert frame_x(60, 0, 119, 119) == pytest.approx(60.0)
    assert frame_x(30, 0, 119, 238) == pytest.approx(60.0)


def test_a_single_frame_range_maps_without_dividing_by_zero() -> None:
    assert frame_x(7, 7, 7, 100) == pytest.approx(0.0)
    assert frame_x(7, 0, 100, 0) == pytest.approx(0.0)
