"""End-to-end tests for the extraction pipeline (M5 S3, S5, S6, S8 · FR-CAP-05..07).

These wire the real pieces together — the controller, the real ``QThread`` runner
and a deterministic engine — over a fake video source, so the whole path is
proven without a GPU, weights or a media backend:

    grab_frame -> runner (worker thread) -> build_production_pose -> mark_pose

The fake source stands in only for Qt Multimedia, which M4 already verified
against a real clip; everything between the frame and the keyframe is real code.
"""

from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.ai.pose_runner import PoseExtractionRunner
from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointData,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)
from aimation_actor.core.services import key_frames


class _FakeSource(QObject):
    """A headless video source that hands back a known frame."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, frame: FrameImage | None = None) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.seeks: list[tuple[int, float]] = []
        self.grabs = 0
        self._frame = _frame() if frame is None else frame

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None:
        self.seeks.append((frame, fps))

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        self.grabs += 1
        if self._frame is None:
            return None
        return CapturedFrame(image=self._frame, frame_index=None)


class _Engine:
    """A deterministic engine: reports a fixed hip height, and can be made to fail."""

    def __init__(
        self,
        *,
        z: float = 140.0,
        error: Exception | None = None,
        projected: dict[str, list[float]] | None = None,
    ) -> None:
        self.calls: list[int] = []
        self._z = z
        self._error = error
        self._projected = projected

    def _report(self) -> WorldPose:
        return WorldPose(
            translation=Vector3(z=self._z),
            rotations={"Pelvis": Quaternion.identity()},
            projected=self._projected,
        )

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        self.calls.append(frame_index)
        if self._error is not None:
            raise self._error
        return self._report()


class _SlowEngine(_Engine):
    """Blocks until released, to prove the UI thread is not waiting on it."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.started = threading.Event()
        self.release = threading.Event()

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        self.calls.append(frame_index)
        self.started.set()
        assert self.release.wait(timeout=5.0), "the test never released the engine"
        return self._report()


def _frame() -> FrameImage:
    return FrameImage(width=2, height=2, rgb=bytes(12))


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="Spine_1", parent="Pelvis"),
        )
    )


@pytest.fixture
def rigged(qtbot, source: _FakeSource):
    """Build a controller wired to a real runner (and clean the thread up after)."""
    runners: list[PoseExtractionRunner] = []

    def build(
        engine,
        video: _FakeSource | None = None,
        *,
        state: TimelineState | None = None,
    ) -> CaptureController:
        runner = PoseExtractionRunner(engine)
        runners.append(runner)
        return CaptureController(
            video if video is not None else source,
            state if state is not None else TimelineState(skeleton=_skeleton(), fps=24.0),
            extractor=runner,
        )

    yield build

    for runner in runners:
        runner.shutdown()


@pytest.fixture
def source() -> _FakeSource:
    return _FakeSource()


def _load(source: _FakeSource, duration_ms: int = 1000) -> None:
    source.media_loaded.emit(24.0, duration_ms)


def test_marking_wires_the_frame_through_to_a_production_key(qtbot, source, rigged) -> None:
    # The whole point of M5: the marked frame becomes a real, remapped key.
    engine = _Engine(z=140.0)
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(15)

    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)

    assert engine.calls == [15]  # exactly one frame, batch 1 (FR-CAP-05)
    assert source.grabs == 1  # one bitmap, on demand (S8)
    key = next(k for k in controller.state.keyframes if k.frame == 15)
    # Pelvis height is the extraction's, mapped onto the rig (FR-CAP-06): 140-100.
    assert key.pose["Pelvis"].translation == Vector3(z=40.0)
    assert set(key.pose) == set(_skeleton().names())


def test_the_ui_is_not_waiting_on_the_engine(qtbot, source, rigged) -> None:
    # NFR-02: mark_current returns while the engine is still working.
    engine = _SlowEngine(z=140.0)
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(5)

    controller.mark_current()

    assert engine.started.wait(timeout=5.0)
    assert controller.has_key(5) is False  # not yet: the work is still running
    engine.release.set()
    qtbot.waitUntil(lambda: controller.has_key(5), timeout=5000)


def test_a_result_lands_on_its_own_frame_after_the_playhead_moved(qtbot, source, rigged) -> None:
    # S5: attribution follows the request, not the playhead. Otherwise a slow
    # inference would silently key the wrong frame.
    engine = _SlowEngine(z=140.0)
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(15)

    controller.mark_current()
    assert engine.started.wait(timeout=5.0)
    controller.go_to_frame(30)  # the animator keeps working while it thinks
    engine.release.set()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)

    assert key_frames(controller.state) == (15,)
    assert controller.has_key(30) is False


def test_a_second_mark_while_extracting_is_refused(qtbot, source, rigged) -> None:
    # S4: batch 1. The refusal is reported, and nothing is keyed for it.
    # Navigation is NOT refused mid-extraction: the answer is attributed to
    # the frame it started from, so scrubbing cannot strand it. Only the
    # second K is refused.
    engine = _SlowEngine(z=140.0)
    controller = rigged(engine)
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(15)

    controller.mark_current()
    assert engine.started.wait(timeout=5.0)
    controller.go_to_frame(16)  # allowed: the pane follows the animator
    controller.mark_current()  # while the first is still running

    assert len(failures) == 1
    assert "Cannot mark" in failures[0]
    assert controller.frame == 16  # the scrub was honored, not refused
    assert engine.calls == [15]  # the refused frame never reached the engine
    engine.release.set()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)
    assert key_frames(controller.state) == (15,)


def test_a_failed_extraction_keeps_prior_keys_and_writes_none(qtbot, source, rigged) -> None:
    # S6 / FR-CAP-07: non-fatal, prior keys survive, no key at the failed frame.
    engine = _Engine(z=120.0)
    controller = rigged(engine)
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(4)
    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(4), timeout=5000)

    engine._error = RuntimeError("weights not found")  # the engine breaks
    controller.go_to_frame(9)
    controller.mark_current()
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    assert key_frames(controller.state) == (4,)  # the earlier key survived
    assert "Pose extraction failed at frame 9" in failures[0]
    assert "weights not found" in failures[0]
    assert controller.has_key(9) is False


def test_marking_without_an_engine_reports_and_writes_no_key(qtbot, source) -> None:
    # S7: the M4 neutral placeholder is retired. A pose nobody computed must not
    # reach the FBX export.
    controller = CaptureController(source, TimelineState(skeleton=_skeleton(), fps=24.0))
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(3)

    controller.mark_current()

    assert failures == ["No pose engine is configured, so no pose can be extracted."]
    assert key_frames(controller.state) == ()


def test_a_frame_the_player_cannot_give_is_reported(qtbot, rigged) -> None:
    # S8: no frame, no extraction, and the reason is named (NFR-03).
    silent = _FakeSource()
    silent._frame = None
    controller = rigged(_Engine(z=140.0), silent)
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.open_video("clip.mp4")
    _load(silent)
    controller.go_to_frame(2)

    controller.mark_current()

    assert failures == ["Could not read the frame at the playhead."]
    assert key_frames(controller.state) == ()


def test_a_result_from_a_clip_that_is_no_longer_open_is_discarded(qtbot, source, rigged) -> None:
    # Async ordering: a slow result must never be written onto a different clip's
    # fresh timeline.
    engine = _SlowEngine(z=140.0)
    controller = rigged(engine)
    controller.open_video("first.mp4")
    _load(source)
    controller.go_to_frame(15)
    controller.mark_current()
    assert engine.started.wait(timeout=5.0)

    controller.open_video("second.mp4")  # a new clip, and an empty timeline
    _load(source)
    failures: list[str] = []
    controller.failed.connect(failures.append)
    engine.release.set()
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    assert key_frames(controller.state) == ()  # nothing leaked onto the new clip
    assert "no longer open" in failures[0]


# -- the video overlay's per-key projections (pose-video-overlay S1, S4) ----- #

_PROJECTION = {"Pelvis": (640.0, 360.0), "Spine_1": (640.0, 300.0)}


def test_a_captured_projection_reaches_the_overlay_for_its_frame(qtbot, source, rigged) -> None:
    engine = _Engine(z=140.0, projected=_PROJECTION)
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(15)

    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)

    snapshot = controller.overlay_snapshot_at(15)
    assert snapshot is not None
    segments, dots = snapshot
    assert ((640.0, 360.0), (640.0, 300.0)) in {tuple(s[:2]) for s in segments}
    assert (640.0, 360.0) in {dot[0] for dot in dots}
    # S4: before the first capture there is nothing to draw...
    assert controller.overlay_snapshot_at(10) is None
    # ... and after it the figure holds until the NEXT capture (stepped).
    assert controller.overlay_snapshot_at(90) is snapshot


def test_a_second_capture_steps_the_overlay_from_its_own_frame(qtbot, source, rigged) -> None:
    first = {"Pelvis": (600.0, 360.0), "Spine_1": (600.0, 300.0)}
    second = {"Pelvis": (700.0, 360.0), "Spine_1": (700.0, 300.0)}
    engine = _SequenceEngine(z=140.0, projections=[first, second])
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source, duration_ms=4000)  # 96 frames: both captures fit the range

    controller.go_to_frame(15)
    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)
    # The runner frees itself through its own queued event: wait for it, or the
    # second mark would hit the batch-1 refusal (a race a human never hits).
    qtbot.waitUntil(lambda: not controller.extraction_busy, timeout=5000)
    controller.go_to_frame(40)
    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(40), timeout=5000)

    first_snapshot = controller.overlay_snapshot_at(15)
    second_snapshot = controller.overlay_snapshot_at(40)
    assert first_snapshot is not None and second_snapshot is not None
    assert first_snapshot is not second_snapshot
    # S4: between the captures the FIRST figure keeps holding.
    assert controller.overlay_snapshot_at(39) is first_snapshot


def test_reloading_the_clip_discards_the_overlay_snapshots(qtbot, source, rigged) -> None:
    engine = _Engine(z=140.0, projected=_PROJECTION)
    controller = rigged(engine)
    controller.open_video("first.mp4")
    _load(source)
    controller.go_to_frame(15)
    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)

    controller.open_video("second.mp4")
    _load(source)
    qtbot.waitUntil(lambda: not controller.has_key(15))
    assert controller.overlay_snapshot_at(15) is None


def test_a_pose_without_projection_marks_a_key_without_a_snapshot(qtbot, source, rigged) -> None:
    engine = _Engine(z=140.0)  # an engine that reports no projected joints
    controller = rigged(engine)
    controller.open_video("clip.mp4")
    _load(source)
    controller.go_to_frame(15)

    controller.mark_current()
    qtbot.waitUntil(lambda: controller.has_key(15), timeout=5000)

    assert controller.overlay_snapshot_at(15) is None  # no invented geometry
    assert controller.overlay_availability() == "unavailable"


class _SequenceEngine(_Engine):
    """Hands out a queue of one projection per capture (a camera that drifts)."""

    def __init__(self, *, z: float, projections: list[dict[str, list[float]]]) -> None:
        super().__init__(z=z)
        self._z_queue = z
        self._queue = list(projections)

    def _report(self) -> WorldPose:
        projected = self._queue.pop(0) if self._queue else {}
        return WorldPose(
            translation=Vector3(z=self._z_queue),
            rotations={"Pelvis": Quaternion.identity()},
            projected=projected,
        )
