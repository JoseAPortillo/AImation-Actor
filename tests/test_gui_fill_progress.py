"""The capture progress bar contract (GUI progress feature).

Extraction and inbetweening run off the UI thread; the only live feedback
today is the text of the status bar, which an animator watching the viewport
can miss. The contract pinned here:

- the controller reports gather progress through ``guide_progress(done,
  total)`` — the plan length announced at fill start, one emit per gathered
  guide, and the engine fill announced at hand-off;
- the fill lifecycle is queryable (``fill_active``) and so is the batch-1
  runner (``extraction_busy``);
- the window maps that onto one bar: determinate while guides gather,
  indeterminate while the engine works or a solo extraction runs, hidden
  whenever nothing is in flight, hidden again on a new clip;
- a fill must SURVIVE user input, not block it: scrubbing, stepping and
  playback stay fully live while a fill runs — the gather re-seeks its own
  target on every retry and the hand-off returns the decoder to the
  playhead — while the mutations that would genuinely break the process
  (``K`` stealing the batch-1 slot or colliding with the guide plan,
  ``Delete`` rewriting the keys the hand-off reads) are refused at the
  controller boundary.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import (
    CaptureController,
    guide_frames_between,
)
from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointData,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)

# ---------------------------------------------------------------- controller #


class _FakeSource(QObject):
    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.frame_index: int | None = None
        self._shown: int | None = None
        self.plays = 0
        self.paused = 0
        self.seeks: list[tuple[int, float]] = []

    def open(self, path: str) -> None:
        pass

    def play(self) -> None:
        self.plays += 1

    def pause(self) -> None:
        self.paused += 1

    def seek_frame(self, frame: int, fps: float) -> None:
        # The pane follows the seek: whoever seeks last owns what is proven.
        self.seeks.append((frame, fps))
        self._shown = frame

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        proven = self.frame_index if self.frame_index is not None else self._shown
        return CapturedFrame(
            image=FrameImage(width=1, height=1, rgb=bytes(3)),
            frame_index=proven,
        )


class _FakeExtractor(QObject):
    """Answers every request synchronously, like the harnesses already do."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.refuse = False

    def start(self, frame_index: int, image: FrameImage) -> bool:
        if self.refuse:
            return False
        self.extracted.emit(
            frame_index,
            WorldPose(translation=Vector3(z=140.0), rotations={}),
        )
        return True


class _FakeInbetweener(QObject):
    """Accepts the hand-off and never answers (the fill stays in flight)."""

    filled = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.starts: list[dict] = []

    def start(self, timeline: TimelineState, guides=None) -> bool:
        self.starts.append((timeline, guides))
        return True


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )


def _fill_controller() -> tuple[CaptureController, _FakeSource, _FakeExtractor,
                               _FakeInbetweener]:
    """A controller whose fill machinery exists (extractor + inbetweener)."""
    source = _FakeSource()
    extractor = _FakeExtractor()
    inbetweener = _FakeInbetweener()
    state = TimelineState(skeleton=_skeleton(), fps=24.0, frame_start=0, frame_end=0)
    controller = CaptureController(
        source, state, extractor=extractor, inbetweener=inbetweener
    )
    controller.open_video("progress.mp4")
    source.media_loaded.emit(24.0, 5000)  # frames 0..119
    return controller, source, extractor, inbetweener


def _mark_two_keys(controller: CaptureController, source: _FakeSource) -> None:
    source.frame_index = 0
    controller.mark_current()
    source.frame_index = 60
    controller.mark_current()


def test_the_fill_announces_the_plan_and_every_gathered_guide() -> None:
    """Gather progress: plan length at start, one emit per gathered guide."""
    controller, source, _, _ = _fill_controller()
    _mark_two_keys(controller, source)
    plan = guide_frames_between((0, 60), 24.0)
    total = len(plan)
    assert total >= 1  # a wide gap carries a non-empty gather plan
    emissions: list[tuple[int, int]] = []
    controller.guide_progress.connect(
        lambda done, count: emissions.append((done, count))
    )
    source.frame_index = None  # the gather's grabs answer unindexed, usable

    controller.fill_inbetweens()

    assert emissions == [(0, total)] + [
        (done, total) for done in range(1, total + 1)
    ] + [(total, total)]
    assert controller.fill_active is True


def test_a_degraded_gather_announces_the_engine_fill() -> None:
    """Keys-only degradation still flips the bar to the engine's fill."""
    controller, source, extractor, _ = _fill_controller()
    _mark_two_keys(controller, source)
    total = len(guide_frames_between((0, 60), 24.0))
    emissions: list[tuple[int, int]] = []
    controller.guide_progress.connect(
        lambda done, count: emissions.append((done, count))
    )
    extractor.refuse = True
    source.frame_index = None  # grabs answer unindexed, usable

    controller.fill_inbetweens()

    assert emissions == [(0, total), (total, total)]
    assert controller.fill_active is True


def test_adopting_the_fill_ends_the_contract() -> None:
    controller, source, extractor, inbetweener = _fill_controller()
    _mark_two_keys(controller, source)
    extractor.refuse = True
    controller.fill_inbetweens()
    assert controller.fill_active is True

    inbetweener.filled.emit(controller.state)

    assert controller.fill_active is False


def test_extraction_busy_reads_the_runner_in_flight() -> None:
    """The batch-1 runner owns this state; a fake without it reads idle."""
    controller, _, extractor, _ = _fill_controller()
    assert controller.extraction_busy is False
    extractor.busy = True
    assert controller.extraction_busy is True


def test_a_new_clip_ends_an_in_flight_fill() -> None:
    """The gather cannot survive its clip: the bar must honor that at once."""
    controller, source, extractor, _ = _fill_controller()
    _mark_two_keys(controller, source)
    extractor.refuse = True
    controller.fill_inbetweens()
    assert controller.fill_active is True

    controller.open_video("replaced.mp4")
    source.media_loaded.emit(24.0, 5000)

    assert controller.fill_active is False


# ------------------------------------------------- interruption immunity #


class _DeferredExtractor(QObject):
    """Answers only when the test advances it: the gather really pauses
    between guides, so user input can land mid-gather."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.pending: list[int] = []

    def start(self, frame_index: int, image: FrameImage) -> bool:
        self.pending.append(frame_index)
        return True

    def answer(self) -> None:
        frame_index = self.pending.pop(0)
        self.extracted.emit(
            frame_index,
            WorldPose(translation=Vector3(z=140.0), rotations={}),
        )


def _deferred_fill_controller() -> tuple[
    CaptureController, _FakeSource, _DeferredExtractor, _FakeInbetweener
]:
    source = _FakeSource()
    extractor = _DeferredExtractor()
    inbetweener = _FakeInbetweener()
    state = TimelineState(skeleton=_skeleton(), fps=24.0, frame_start=0, frame_end=0)
    controller = CaptureController(
        source, state, extractor=extractor, inbetweener=inbetweener
    )
    controller.open_video("scrub-during-fill.mp4")
    source.media_loaded.emit(24.0, 5000)  # frames 0..119
    return controller, source, extractor, inbetweener


def _mark_pair(controller: CaptureController, source: _FakeSource,
               extractor: _DeferredExtractor) -> None:
    source.frame_index = 0
    controller.mark_current()
    extractor.answer()
    source.frame_index = 60
    controller.mark_current()
    extractor.answer()


def test_scrubbing_and_playing_never_interrupt_a_fill_in_flight() -> None:
    """The user keeps full control of the timeline while a fill runs: a scrub
    mid-gather only delays the guide it raced with — each extraction result is
    attributed to the frame it started from, never to the current playhead —
    and the fill hands off and completes anyway."""
    controller, source, extractor, inbetweener = _deferred_fill_controller()
    _mark_pair(controller, source, extractor)
    plan = guide_frames_between((0, 60), 24.0)
    total = len(plan)
    assert total >= 2  # the interleaving below needs more than one guide
    source.frame_index = None  # unindexed grabs are usable after the seek

    emissions: list[tuple[int, int]] = []
    controller.guide_progress.connect(
        lambda done, count: emissions.append((done, count))
    )

    controller.fill_inbetweens()
    assert extractor.pending == [plan[0]]  # the gather waits on guide 1

    # The animator touches everything the fill must survive.
    controller.go_to_frame(10)
    assert controller.frame == 10
    controller.toggle_playback()
    assert source.plays == 1

    # The gather finishes its paused guide and everything after it.
    while extractor.pending:
        extractor.answer()

    assert emissions == [(0, total)] + [
        (done, total) for done in range(1, total + 1)
    ] + [(total, total)]  # the hand-off re-announces the finished gather
    assert inbetweener.starts  # handed off: the process the user started ran
    assert controller.fill_active is True
    # The pane belongs to the animator again: the hand-off returned the
    # decoder to the frame the playhead shows.
    assert source.seeks[-1] == (10, 24.0)


def test_guide_retry_re_seeks_its_own_target() -> None:
    """The retry is what a user scrub races with: re-seeking makes the race
    delay the guide, never strand it."""
    controller, source, extractor, _ = _deferred_fill_controller()
    _mark_pair(controller, source, extractor)
    plan = guide_frames_between((0, 60), 24.0)
    source.frame_index = None
    controller.fill_inbetweens()
    assert extractor.pending == [plan[0]]

    # The user dragged the pane onto frame 10 while the gather waited.
    controller.go_to_frame(10)
    source.frame_index = 10  # the pane still proves the USER's frame

    controller._retry_guide_grab()  # the 50 ms retry tick

    assert source.seeks[-1] == (plan[0], 24.0)  # the retry re-seeks the guide
    assert extractor.pending == [plan[0]]  # and never adopts the user's frame
    source.frame_index = None  # now the pane has followed the seek (proves 14)

    controller._retry_guide_grab()  # the next tick

    assert extractor.pending == [plan[0], plan[0]]  # and re-requests the guide


def test_marking_refuses_while_a_fill_is_in_flight() -> None:
    """A stolen batch-1 slot or a key that collides with the guide plan would
    break the fill in flight: K is part of the locked surface, not only the
    scrubber."""
    controller, source, extractor, _ = _fill_controller()
    _mark_two_keys(controller, source)
    extractor.refuse = True
    controller.fill_inbetweens()
    assert controller.fill_active is True
    refusals: list[str] = []
    controller.failed.connect(refusals.append)

    source.frame_index = 70
    controller.mark_current()

    assert controller.key_count() == 2  # nothing was marked
    assert len(refusals) == 1
    assert "Cannot mark" in refusals[0]


def test_marking_refuses_while_an_extraction_is_in_flight() -> None:
    """The lock covers the real runner's busy window, not just the gather."""
    controller, source, extractor, _ = _fill_controller()
    refusals: list[str] = []
    controller.failed.connect(refusals.append)
    extractor.busy = True
    source.frame_index = 3

    controller.mark_current()

    assert controller.key_count() == 0
    assert len(refusals) == 1
    assert "Cannot mark" in refusals[0]


def test_removing_refuses_while_a_fill_is_in_flight() -> None:
    """A removal now would change the keys the hand-off reads and be silently
    overwritten when the fill lands."""
    controller, source, extractor, _ = _fill_controller()
    _mark_two_keys(controller, source)  # playhead lands on keyed frame 60
    extractor.refuse = True
    controller.fill_inbetweens()
    assert controller.fill_active is True
    refusals: list[str] = []
    controller.failed.connect(refusals.append)

    controller.remove_current()

    assert controller.key_count() == 2
    assert len(refusals) == 1
    assert "Cannot remove" in refusals[0]


# -------------------------------------------------------------------- window #


class _ConstantEngine:
    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        return WorldPose(translation=Vector3(z=140.0), rotations={})


class _HoldingEngine:
    """An engine that never answers until released: a cold-start stand-in."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        self.release.wait(timeout=10.0)
        return WorldPose(translation=Vector3(z=140.0), rotations={})


def _window_source() -> _FakeSource:
    return _FakeSource()


def _load_two_seconds(window: MainWindow, source: _FakeSource) -> None:
    window.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)


def test_the_window_starts_with_the_progress_hidden(qtbot) -> None:
    source = _window_source()
    window = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(window)
    assert window.progress is not None
    assert window.progress.isHidden()

    _load_two_seconds(window, source)
    assert window.progress.isHidden()  # a loaded idle clip keeps it hidden


def test_guide_progress_wires_the_bar_in_the_bottom_row(qtbot) -> None:
    source = _window_source()
    window = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(window)
    _load_two_seconds(window, source)

    window.controller.guide_progress.emit(1, 3)
    assert not window.progress.isHidden()
    assert window.progress.maximum() == 3
    assert window.progress.value() == 1

    window.controller.guide_progress.emit(3, 3)
    # done == total means the gather ended and the engine fills: indeterminate
    assert window.progress.maximum() == window.progress.minimum() == 0


def test_a_keys_only_fill_announces_an_indeterminate_bar(qtbot) -> None:
    source = _window_source()
    window = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(window)
    window.controller.guide_progress.emit(0, 0)
    assert not window.progress.isHidden()
    assert window.progress.maximum() == window.progress.minimum() == 0


def test_a_new_clip_hides_the_bar_again(qtbot) -> None:
    source = _window_source()
    window = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(window)
    _load_two_seconds(window, source)
    window.controller.guide_progress.emit(0, 2)
    assert not window.progress.isHidden()

    window.load_video("other.mp4")
    source.media_loaded.emit(24.0, 2000)
    assert window.progress.isHidden()


def test_a_solo_extraction_shows_an_indeterminate_bar(qtbot) -> None:
    """A cold-start ``K`` press: the runner is busy with no gather running."""
    source = _window_source()
    engine = _HoldingEngine()
    window = MainWindow(source=source, skeleton=_skeleton(), engine=engine)
    qtbot.addWidget(window)
    _load_two_seconds(window, source)
    assert window.timeline.isEnabled()  # idle: the scrubber answers
    source.frame_index = 0

    window.controller.mark_current()
    qtbot.waitUntil(lambda: window.controller.extraction_busy)
    assert not window.progress.isHidden()
    assert window.progress.maximum() == window.progress.minimum() == 0
    # The extraction owns the engine, not the UI: the animator keeps the
    # timeline. Only K/Delete are refused meanwhile, by the controller.
    assert window.timeline.isEnabled()
    assert window.action_step_forward.isEnabled()

    engine.release.set()
    qtbot.waitUntil(lambda: window.progress.isHidden())
    assert window.timeline.isEnabled()


class _BlockingFillEngine:
    """An inbetweening engine that never answers until released."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def inbetween(self, timeline: TimelineState, guides=None) -> TimelineState:
        self.release.wait(timeout=10.0)
        return timeline


def test_the_timeline_stays_live_while_a_fill_is_in_flight(qtbot) -> None:
    """A fill must survive user input, not block it: the scrubber keeps
    answering, and the gather's re-seek retries make a mid-gather scrub a
    delay, never a cancellation."""
    source = _window_source()
    engine = _BlockingFillEngine()
    window = MainWindow(
        source=source,
        skeleton=_skeleton(),
        engine=_ConstantEngine(),
        inbetween_engine=engine,
    )
    qtbot.addWidget(window)
    _load_two_seconds(window, source)

    source.frame_index = 0
    window.controller.mark_current()
    qtbot.waitUntil(lambda: window.controller.key_count() == 1)
    source.frame_index = 60
    window.controller.mark_current()
    qtbot.waitUntil(lambda: window.controller.key_count() == 2)

    source.frame_index = None  # the gather's grabs answer unindexed, usable
    window.controller.fill_inbetweens()
    qtbot.waitUntil(lambda: window.controller.fill_active)

    # The animator drives the timeline through the widget path while the fill
    # runs; the controller must accept it.
    before = len(source.seeks)
    window.timeline.slider.setValue(12)  # frame_requested -> go_to_frame
    assert window.controller.frame == 12
    assert len(source.seeks) > before  # and the decoder really followed
    assert window.timeline.isEnabled()
    assert window.action_step_forward.isEnabled()
    assert window.action_play_pause.isEnabled()
    # K is the one mutation that would break the fill: refused, not frozen.
    refusals: list[str] = []
    window.controller.failed.connect(refusals.append)
    window.controller.mark_current()
    assert refusals and "Cannot mark" in refusals[0]
    assert window.controller.key_count() == 2

    engine.release.set()
    qtbot.waitUntil(lambda: not window.controller.fill_active)
    assert window.timeline.isEnabled()  # adopted: everything still answers
