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
  whenever nothing is in flight, hidden again on a new clip.
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

    def open(self, path: str) -> None:
        pass

    def play(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def seek_frame(self, frame: int, fps: float) -> None:
        pass

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        return CapturedFrame(
            image=FrameImage(width=1, height=1, rgb=bytes(3)),
            frame_index=self.frame_index,
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
    source.frame_index = 0

    window.controller.mark_current()
    qtbot.waitUntil(lambda: window.controller.extraction_busy)
    assert not window.progress.isHidden()
    assert window.progress.maximum() == window.progress.minimum() == 0

    engine.release.set()
    qtbot.waitUntil(lambda: window.progress.isHidden())
