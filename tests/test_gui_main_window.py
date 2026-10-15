"""Tests for the capture window (S4, S6, S8, S9, S12).

Real playback and pixel output stay manual checks. What is pinned here is the
wiring the specs describe: which key does what, and that the video pane, the
timeline and the 3D pane all follow one time indicator (plan §3.B).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.core.models import JointData, Skeleton, Vector3


class _FakeSource(QObject):
    """A headless video source: it records what it was asked to do."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.played = 0
        self.paused = 0
        self.seeks: list[tuple[int, float]] = []

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None:
        self.played += 1

    def pause(self) -> None:
        self.paused += 1

    def seek_frame(self, frame: int, fps: float) -> None:
        self.seeks.append((frame, fps))


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )


@pytest.fixture
def source() -> _FakeSource:
    return _FakeSource()


@pytest.fixture
def window(qtbot, source: _FakeSource) -> MainWindow:
    window = MainWindow(source=source, skeleton=_skeleton())
    qtbot.addWidget(window)
    return window


def _load_two_seconds(window: MainWindow, source: _FakeSource) -> None:
    """Load a clip: 2000 ms at 24 fps is 48 frames, so the range is 0..47."""
    window.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)


def test_the_window_puts_the_video_beside_the_viewport(window: MainWindow) -> None:
    # plan §3.B: a split-view interface.
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.splitter.count() == 2
    assert window.splitter.widget(1) is window.viewport


def test_the_shortcuts_are_the_ones_the_plan_names(window: MainWindow) -> None:
    # plan §3.A / S4: the exact key bindings, not an approximation.
    assert window.action_play_pause.shortcut() == QKeySequence("Space")
    assert window.action_step_back.shortcut() == QKeySequence("Left")
    assert window.action_step_forward.shortcut() == QKeySequence("Right")
    assert window.action_mark.shortcut() == QKeySequence("K")
    assert window.action_remove_key.shortcut() == QKeySequence("Delete")
    assert window.action_next_key.shortcut() == QKeySequence("Shift+Right")
    assert window.action_previous_key.shortcut() == QKeySequence("Shift+Left")


def test_the_status_reports_the_loaded_clip(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    report = window.statusBar().currentMessage()
    assert "clip.mp4" in report
    assert "48" in report


def test_the_timeline_and_the_viewport_share_the_playhead(
    window: MainWindow, source: _FakeSource
) -> None:
    # plan §3.B: both panes are linked to the same time indicator.
    _load_two_seconds(window, source)

    window.action_step_forward.trigger()

    assert window.controller.frame == 1
    assert window.timeline.frame == 1
    assert source.seeks[-1][0] == 1
    # Frame 1 carries no key, so the pane shows the rig in its neutral pose.
    assert window.viewport.segments != ()


def test_space_plays_and_pauses(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    window.action_play_pause.trigger()
    assert source.played == 1

    source.playback_changed.emit(True)
    window.action_play_pause.trigger()
    assert source.paused == 1


def test_the_arrow_keys_step_one_frame_at_a_time(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    window.action_step_forward.trigger()
    window.action_step_forward.trigger()
    window.action_step_back.trigger()

    assert window.controller.frame == 1
    assert window.controller.total_frames == 48


def test_k_marks_the_playhead_and_delete_removes_it(
    window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()

    window.action_mark.trigger()
    assert window.controller.has_key(1)
    assert window.timeline.key_strip.keys == (1,)

    window.action_remove_key.trigger()
    assert not window.controller.has_key(1)
    assert window.timeline.key_strip.keys == ()


def test_shift_arrows_jump_between_golden_poses(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)
    window.controller.go_to_frame(10)
    window.action_mark.trigger()
    window.controller.go_to_frame(30)
    window.action_mark.trigger()
    window.controller.go_to_frame(20)

    window.action_next_key.trigger()
    assert window.controller.frame == 30

    window.action_previous_key.trigger()
    assert window.controller.frame == 10


def test_the_open_action_hands_the_path_to_the_controller(
    window: MainWindow, source: _FakeSource
) -> None:
    window.load_video("clip.mp4")

    assert source.opened == ["clip.mp4"]
    assert window.action_open.shortcut() == QKeySequence("Ctrl+O")


def test_a_failed_open_is_reported_and_the_capture_stays_usable(
    window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)

    source.failed.emit("Cannot decode clip.mp4.")

    assert "Cannot decode clip.mp4." in window.statusBar().currentMessage()
    assert window.controller.has_media  # the loaded clip survives (FR-CAP-01)

    window.action_step_forward.trigger()  # and the session keeps working
    assert window.controller.frame == 1
