"""Tests for the capture controller (spec FR-CAP-03, FR-CAP-04, FR-CAP-07, NFR-03).

The controller is driven through a fake video source, so the timeline, marking
and shortcut behavior are proven without a media backend.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)
from aimation_actor.core.services import key_frames, neutral_pose


class _FakeSource(QObject):
    """The video-source seam, in memory: records calls, scripts the signals."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.seeks: list[tuple[int, float]] = []
        self.plays = 0
        self.pauses = 0
        self.playing = False

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None:
        self.plays += 1
        self.playing = True
        self.playback_changed.emit(True)

    def pause(self) -> None:
        self.pauses += 1
        self.playing = False
        self.playback_changed.emit(False)

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
def controller(source: _FakeSource) -> CaptureController:
    state = TimelineState(skeleton=_skeleton(), fps=24.0, frame_start=0, frame_end=0)
    return CaptureController(source, state)


def _load_clip(source: _FakeSource, fps: float = 24.0, duration_ms: int = 5000) -> None:
    """Open a clip and let the source answer, as the real player would."""
    source.media_loaded.emit(fps, duration_ms)


# --------------------------------------------------------------------------- #
# Media loading (FR-CAP-03, NFR-03)
# --------------------------------------------------------------------------- #


def test_opening_a_clip_takes_its_frame_rate_and_frame_range(
    controller: CaptureController, source: _FakeSource
) -> None:
    changed: list[int] = []
    controller.frame_changed.connect(changed.append)

    controller.open_video("reference.mp4")
    _load_clip(source, fps=30.0, duration_ms=4000)

    assert source.opened == ["reference.mp4"]
    assert controller.state.fps == pytest.approx(30.0)
    assert (controller.state.frame_start, controller.state.frame_end) == (0, 119)
    assert controller.total_frames == 120
    assert changed[-1] == 0


def test_a_clip_without_reported_frame_rate_keeps_the_default(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("reference.mov")
    _load_clip(source, fps=0.0, duration_ms=1000)

    assert controller.state.fps == pytest.approx(24.0)
    assert controller.total_frames == 24


def test_loading_a_second_clip_starts_a_fresh_timeline(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("first.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    controller.open_video("second.mp4")
    _load_clip(source, duration_ms=1000)

    assert key_frames(controller.state) == ()  # keys belong to the clip


def test_a_failed_first_open_leaves_no_clip_loaded(
    controller: CaptureController, source: _FakeSource
) -> None:
    failures: list[str] = []
    controller.failed.connect(failures.append)

    controller.open_video("broken.mp4")
    source.failed.emit("broken.mp4: unsupported or corrupt media")

    assert failures == ["broken.mp4: unsupported or corrupt media"]
    assert controller.has_media is False
    assert controller.video_path is None


def test_a_failed_open_reports_and_leaves_the_loaded_clip_usable(
    controller: CaptureController, source: _FakeSource
) -> None:
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.open_video("good.mp4")
    _load_clip(source, fps=25.0, duration_ms=2000)

    controller.open_video("broken.mp4")
    source.failed.emit("broken.mp4: unsupported or corrupt media")

    assert failures == ["broken.mp4: unsupported or corrupt media"]
    assert controller.state.fps == pytest.approx(25.0)
    assert controller.total_frames == 50
    assert controller.has_media is True


# --------------------------------------------------------------------------- #
# Playhead and shortcuts (FR-CAP-04, plan §3.A)
# --------------------------------------------------------------------------- #


def test_stepping_moves_one_frame_and_clamps_to_the_range(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source, duration_ms=1000)  # 24 frames: 0..23

    controller.step(-1)
    assert controller.frame == 0  # clamped at the start

    controller.step(1)
    controller.step(1)
    assert controller.frame == 2
    assert source.seeks[-1] == (2, 24.0)

    controller.go_to_frame(999)
    assert controller.frame == 23  # clamped at the end
    controller.step(1)
    assert controller.frame == 23


def test_going_to_a_frame_seeks_the_video_source(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    source.seeks.clear()

    controller.go_to_frame(15)

    assert source.seeks == [(15, 24.0)]


def test_jumping_between_keys_lands_on_captured_poses(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    for frame in (15, 42):
        controller.go_to_frame(frame)
        controller.mark_current()

    controller.go_to_frame(0)
    controller.jump_to_key(1)
    assert controller.frame == 15
    controller.jump_to_key(1)
    assert controller.frame == 42

    controller.jump_to_key(-1)
    assert controller.frame == 15

    controller.go_to_frame(0)
    controller.jump_to_key(-1)
    assert controller.frame == 0  # no earlier key: the playhead stays put


def test_toggle_playback_delegates_and_mirrors_the_player(
    controller: CaptureController, source: _FakeSource
) -> None:
    states: list[bool] = []
    controller.playback_changed.connect(states.append)
    controller.open_video("clip.mp4")
    _load_clip(source)

    controller.toggle_playback()
    assert (source.plays, source.pauses) == (1, 0)
    assert controller.is_playing is True

    controller.toggle_playback()
    assert (source.plays, source.pauses) == (1, 1)
    assert controller.is_playing is False
    assert states == [True, False]


def test_playback_position_moves_the_playhead(
    controller: CaptureController, source: _FakeSource
) -> None:
    frames: list[int] = []
    controller.frame_changed.connect(frames.append)
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()

    source.position_changed.emit(500)  # 500 ms at 24 fps

    assert controller.frame == 12
    assert frames[-1] == 12


def test_a_paused_position_is_not_treated_as_playback(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    source.seeks.clear()

    # The echo of our own seek must not bounce the playhead or re-seek.
    source.position_changed.emit(625)  # 15 frames at 24 fps

    assert controller.frame == 15
    assert source.seeks == []


# --------------------------------------------------------------------------- #
# Marking and removing (FR-CAP-07, plan §3.A)
# --------------------------------------------------------------------------- #


def test_marking_the_current_frame_adds_a_neutral_pose_key(
    controller: CaptureController, source: _FakeSource
) -> None:
    changes: list[int] = []
    controller.timeline_changed.connect(lambda: changes.append(controller.frame))
    controller.open_video("clip.mp4")
    _load_clip(source)
    changes.clear()  # loading a clip changes the range, so it already fired

    controller.go_to_frame(15)
    controller.mark_current()

    assert key_frames(controller.state) == (15,)
    key = next(k for k in controller.state.keyframes if k.frame == 15)
    assert key.pose == neutral_pose(_skeleton())
    assert changes == [15]


def test_remarking_a_frame_does_not_duplicate_the_key(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)

    controller.mark_current()
    controller.mark_current()

    assert key_frames(controller.state) == (15,)
    assert len(controller.state.keyframes) == 1


def test_removing_the_current_frame_drops_its_key(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    controller.remove_current()

    assert key_frames(controller.state) == ()


def test_marking_without_a_clip_reports_instead_of_marking(
    controller: CaptureController,
) -> None:
    failures: list[str] = []
    controller.failed.connect(failures.append)

    controller.mark_current()

    assert failures == ["Open a reference video before marking golden poses."]
    assert key_frames(controller.state) == ()


# --------------------------------------------------------------------------- #
# What the viewport shows (plan §3.B)
# --------------------------------------------------------------------------- #


def test_the_pose_is_the_key_on_a_keyed_frame_and_neutral_elsewhere(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    shown = controller.current_pose()
    assert shown == neutral_pose(_skeleton())

    controller.go_to_frame(16)
    assert controller.current_pose() == neutral_pose(_skeleton())
    assert controller.has_key(15) is True
    assert controller.has_key(16) is False


# --------------------------------------------------------------------------- #
# Reported state (NFR-03)
# --------------------------------------------------------------------------- #


def test_status_reports_the_clip_the_frame_and_the_key_state(
    controller: CaptureController, source: _FakeSource
) -> None:
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    # The window pulls the initial status right after wiring: a signal emitted
    # during construction would fire before any receiver is connected.
    assert controller.status() == "No video loaded."

    controller.open_video("reference.mp4")
    _load_clip(source, duration_ms=1000)
    controller.go_to_frame(15)
    controller.mark_current()

    status = statuses[-1]
    assert "reference.mp4" in status
    assert "15 / 24" in status  # current / total frames (FR-CAP-03)
    assert "24 fps" in status
    assert "1 golden pose" in status
    assert "keyed" in status


def test_a_corrupt_pose_mapping_is_never_needed_to_show_a_frame(
    controller: CaptureController, source: _FakeSource
) -> None:
    controller.open_video("clip.mp4")
    _load_clip(source)

    # Every frame of the range can be displayed without a key: the neutral pose
    # covers the whole skeleton.
    for frame in range(controller.total_frames):
        controller.go_to_frame(frame)
        shown: Mapping[str, JointPose] = controller.current_pose()
        assert set(shown) == set(_skeleton().names())

    assert Quaternion.identity() == controller.current_pose()["Main"].rotation
