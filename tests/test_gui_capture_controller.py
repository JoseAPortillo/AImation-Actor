"""Tests for the capture controller (spec FR-CAP-03, FR-CAP-04, FR-CAP-07, NFR-03).

The controller is driven through a fake video source and a fake engine, so the
timeline, marking and shortcut behavior are proven without a media backend or a
GPU. The extraction path itself is exercised for real in
``test_ai_extraction_pipeline.py``; here the extractor answers **synchronously**,
which keeps every case deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointData,
    JointPose,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)
from aimation_actor.core.services import key_frames, neutral_pose


class _FakeSource(QObject):
    """The video-source seam, in memory: records calls, scripts the signals."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.seeks: list[tuple[int, float]] = []
        self.plays = 0
        self.pauses = 0
        self.playing = False
        self.grabs = 0
        # Which frame the pane is really showing, when the source can prove it.
        # ``None`` stands for a backend that reports no timestamps.
        self.frame_index: int | None = None

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

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        self.grabs += 1
        return CapturedFrame(
            image=FrameImage(width=1, height=1, rgb=bytes(3)),
            frame_index=self.frame_index,
        )


class _FakeExtractor(QObject):
    """The extractor seam, in memory: answers on the spot, no thread involved."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, hip_height: float = 140.0) -> None:
        super().__init__()
        self.requests: list[tuple[int, FrameImage]] = []
        self.refuse = False
        self.failure: str | None = None
        self._hip_height = hip_height

    def start(self, frame_index: int, image: FrameImage) -> bool:
        if self.refuse:
            return False
        self.requests.append((frame_index, image))
        if self.failure is not None:
            self.failed.emit(frame_index, self.failure)
            return True
        self.extracted.emit(
            frame_index,
            WorldPose(translation=Vector3(z=self._hip_height), rotations={}),
        )
        return True


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
def extractor() -> _FakeExtractor:
    return _FakeExtractor()


@pytest.fixture
def controller(source: _FakeSource, extractor: _FakeExtractor) -> CaptureController:
    state = TimelineState(skeleton=_skeleton(), fps=24.0, frame_start=0, frame_end=0)
    return CaptureController(source, state, extractor=extractor)


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


def test_the_playhead_follows_the_frame_that_was_delivered(
    controller: CaptureController, source: _FakeSource
) -> None:
    # S13. The frame knows which frame it is; the backend's position events do
    # not arrive often enough to keep up with it, so the timeline follows the
    # frame once the source proves it can index one.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()

    source.frame_shown.emit(48)

    assert controller.frame == 48


def test_a_stale_position_does_not_pull_the_playhead_back(
    controller: CaptureController, source: _FakeSource
) -> None:
    # Measured on a real clip: after the pause, one more position event for an
    # older position still arrives. Following it would walk the timeline back
    # behind the frame on screen and leave the animator's key on a frame the
    # number no longer shows.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()
    source.frame_shown.emit(48)

    source.position_changed.emit(1958)  # 1958 ms -> frame 46, behind the pane

    assert controller.frame == 48


def test_a_position_still_drives_a_clip_that_cannot_be_indexed(
    controller: CaptureController, source: _FakeSource
) -> None:
    # Degradation, not a regression: a backend that never reports frame
    # timestamps keeps the old behavior, where position is all there is.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()

    source.position_changed.emit(500)  # 500 ms at 24 fps

    assert controller.frame == 12


def test_a_frame_delivered_while_paused_does_not_move_the_playhead(
    controller: CaptureController, source: _FakeSource
) -> None:
    # A seek (and the priming nudge on open) delivers a frame too. The animator's
    # own navigation owns the playhead then, so the frame must not relocate it.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.go_to_frame(15)

    source.frame_shown.emit(48)

    assert controller.frame == 15


# --------------------------------------------------------------------------- #
# Marking and removing (FR-CAP-07, plan §3.A)
# --------------------------------------------------------------------------- #


def test_marking_the_current_frame_writes_the_extracted_pose(
    controller: CaptureController, source: _FakeSource, extractor: _FakeExtractor
) -> None:
    # M5: ``K`` extracts the pose at the playhead and writes the *remapped*
    # result. The engine reports a 140 cm hip and the rig's Pelvis binds at
    # 100 cm, so the written offset is 40 — Pelvis carries height as an offset
    # (AGENTS.md).
    changes: list[int] = []
    controller.timeline_changed.connect(lambda: changes.append(controller.frame))
    controller.open_video("clip.mp4")
    _load_clip(source)
    changes.clear()  # loading a clip changes the range, so it already fired

    controller.go_to_frame(15)
    controller.mark_current()

    assert key_frames(controller.state) == (15,)
    key = next(k for k in controller.state.keyframes if k.frame == 15)
    assert key.pose["Pelvis"].translation == Vector3(z=40.0)
    assert key.pose != neutral_pose(_skeleton())  # a real pose, not a placeholder
    assert changes == [15]
    assert [frame for frame, _image in extractor.requests] == [15]


def test_a_mark_after_playback_keys_the_frame_on_screen(
    controller: CaptureController, source: _FakeSource, extractor: _FakeExtractor
) -> None:
    # The M5 verification blocker: the playhead follows the backend's *position*
    # events, which are far rarer than frames, so after a play it can lag the
    # pane by 1-3 frames. The captured frame is what the animator is looking at —
    # the key must land there, and the playhead must catch up to it. Otherwise the
    # animator sees one pose and gets another, silently.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.go_to_frame(40)
    source.frame_index = 43  # the pane is three frames ahead of the playhead
    controller.toggle_playback()

    controller.mark_current()

    assert key_frames(controller.state) == (43,)
    assert controller.frame == 43
    assert [frame for frame, _image in extractor.requests] == [43]


def test_a_source_that_cannot_index_the_frame_keeps_the_playhead(
    controller: CaptureController, source: _FakeSource, extractor: _FakeExtractor
) -> None:
    # Degradation, not refusal: a backend without timestamps cannot say which
    # frame it delivered, so the capture falls back to the playhead instead of
    # writing no key at all (the M5 rule for unusable metadata).
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.go_to_frame(15)
    source.frame_index = None

    controller.mark_current()

    assert key_frames(controller.state) == (15,)
    assert [frame for frame, _image in extractor.requests] == [15]


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
    assert shown["Pelvis"].translation == Vector3(z=40.0)  # the key's pose

    controller.go_to_frame(16)
    assert controller.current_pose() == neutral_pose(_skeleton())  # no key: the bind
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


# --------------------------------------------------------------------------- #
# S12/S13 regression additions (verifier probes)
# --------------------------------------------------------------------------- #


def test_an_out_of_range_captured_index_is_clamped(
    controller: CaptureController, source: _FakeSource
) -> None:
    # S12: the source's index is trusted for the key, but never outside the range.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0, duration_ms=1000)  # 24 frames: 0..23
    controller.go_to_frame(15)
    source.frame_index = 9999

    controller.mark_current()

    assert key_frames(controller.state) == (23,)
    assert controller.frame == 23


def test_indexing_must_be_proved_again_for_a_new_clip(
    controller: CaptureController, source: _FakeSource
) -> None:
    # S13 — "once a source has proved it can index a frame of the current clip".
    # A new clip re-proves it, so a position event still owns the playhead there.
    controller.open_video("first.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()
    source.frame_shown.emit(30)
    assert controller.frame == 30

    controller.open_video("second.mp4")
    source.playback_changed.emit(False)  # setSource stops playback
    _load_clip(source, fps=24.0)
    controller.toggle_playback()
    source.position_changed.emit(500)  # 500 ms at 24 fps

    assert controller.frame == 12


def test_a_proved_index_keeps_owning_the_playhead(
    controller: CaptureController, source: _FakeSource
) -> None:
    # S13: position stops driving the playhead the moment indexing is proved.
    controller.open_video("clip.mp4")
    _load_clip(source, fps=24.0)
    controller.toggle_playback()
    source.position_changed.emit(500)  # 12
    source.frame_shown.emit(20)
    source.position_changed.emit(1000)  # 24 — still ignored

    assert controller.frame == 20


def test_a_refused_mark_writes_no_key_and_leaves_the_timeline_intact(
    controller: CaptureController, source: _FakeSource, extractor: _FakeExtractor
) -> None:
    # S4: a K while an extraction is in flight is refused and marks nothing.
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()
    before = controller.state.keyframes
    requests = list(extractor.requests)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    extractor.refuse = True
    controller.go_to_frame(30)
    controller.mark_current()

    assert failures[-1] == (
        "Still extracting the previous frame; try again when it finishes."
    )
    assert controller.state.keyframes == before
    assert extractor.requests == requests


# --------------------------------------------------------------------------- #
# The rig adoption (T13): the production skeleton is real body-model data,
# so it arrives with the engine's first successful extraction — never invented.
# --------------------------------------------------------------------------- #


def _engine_rig_skeleton() -> Skeleton:
    """The rig the wiring under test would build from the engine's bind offsets."""
    from aimation_actor.core.production_skeleton import (
        PRODUCTION_BODY_JOINT_NAMES,
        production_skeleton,
    )

    offsets = {
        "Pelvis": Vector3(x=-0.18, y=-2.822, z=93.851),
        **{
            name: Vector3(x=1.0, y=0.0, z=-1.0)
            for name in PRODUCTION_BODY_JOINT_NAMES
        },
    }
    return production_skeleton(offsets)


def test_the_first_extraction_adopts_the_engine_template_rig(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    state = TimelineState(skeleton=Skeleton(joints=()), fps=24.0, frame_start=0, frame_end=0)
    calls: list[int] = []
    controller = CaptureController(
        source,
        state,
        extractor=extractor,
        skeleton_source=lambda: calls.append(1) or _engine_rig_skeleton(),
    )
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    assert key_frames(controller.state) == (15,)
    key = next(k for k in controller.state.keyframes if k.frame == 15)
    # the canned extractor reports a 140 cm hip; the adopted rig binds the
    # Pelvis at 93.851 cm, so the written offset is 140 - 93.851
    assert key.pose["Pelvis"].translation.z == pytest.approx(140.0 - 93.851)
    # the rig persists on the timeline: a second extraction must not re-ask
    assert calls == [1]
    controller.go_to_frame(30)
    controller.mark_current()
    assert calls == [1]
    assert key_frames(controller.state) == (15, 30)
    # every production joint is representable on the adopted rig
    assert set(_engine_rig_skeleton().names()) <= set(key.pose)


def test_an_extraction_without_an_available_rig_marks_nothing(
    source: _FakeSource, extractor: _FakeExtractor, qtbot  # noqa: ANN001
) -> None:
    state = TimelineState(skeleton=Skeleton(joints=()), fps=24.0, frame_start=0, frame_end=0)
    failures: list[str] = []
    controller = CaptureController(
        source, state, extractor=extractor, skeleton_source=lambda: None
    )
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    assert key_frames(controller.state) == ()
    assert failures and "rig" in failures[-1].lower()


def test_a_rig_builder_failure_is_a_typed_report(
    source: _FakeSource, extractor: _FakeExtractor, qtbot  # noqa: ANN001
) -> None:
    state = TimelineState(skeleton=Skeleton(joints=()), fps=24.0, frame_start=0, frame_end=0)
    failures: list[str] = []
    controller = CaptureController(
        source,
        state,
        extractor=extractor,
        skeleton_source=_raises_value_error,
    )
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load_clip(source)
    controller.go_to_frame(15)
    controller.mark_current()

    assert key_frames(controller.state) == ()
    assert failures and "valueerror" in failures[-1].lower()


def _raises_value_error() -> Skeleton:
    raise ValueError("template bind offsets are incomplete (missing: L_Knee)")
