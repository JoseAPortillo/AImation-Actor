"""Tests for the off-thread inbetweening runner (M6 T4 · FR-GEN-02, NFR-02).

``InbetweeningPort`` is blocking by contract, so the GUI must never call it
directly: a diffusion fill takes seconds and would freeze the window. This
runner mirrors the pose-extraction runner's two rules:

- **batch size 1.** At most one fill is ever in flight; a second request is
  refused, not queued.
- **non-fatal failure.** An engine's exception is caught inside the worker,
  turned into a message and reported. It never escapes into the Qt event loop.
"""

from __future__ import annotations

import threading

import pytest

from aimation_actor.adapters.ai.inbetween_runner import InbetweeningRunner
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
)


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main"),
        )
    )


def _timeline() -> TimelineState:
    pose = {"Pelvis": JointPose(rotation=Quaternion.identity())}
    keys = tuple(Keyframe(frame=frame, pose=pose) for frame in (1, 4))
    return TimelineState(
        skeleton=_skeleton(), keyframes=keys, fps=24.0, frame_end=10
    )


def _filled() -> TimelineState:
    pose = {"Pelvis": JointPose(rotation=Quaternion.identity())}
    keys = tuple(Keyframe(frame=frame, pose=pose) for frame in range(1, 5))
    return TimelineState(
        skeleton=_skeleton(), keyframes=keys, fps=24.0, frame_end=10
    )


class _Engine:
    """A deterministic engine that reports what it was asked to fill."""

    def __init__(
        self,
        *,
        filled: TimelineState | None = None,
        error: Exception | None = None,
    ) -> None:
        self.timelines: list[TimelineState] = []
        self.guides: list[dict[int, JointPose] | object] = []
        self._filled = _filled() if filled is None else filled
        self._error = error
        self.finished = threading.Event()

    def inbetween(
        self, timeline: TimelineState, guides: dict[int, JointPose] | object = None
    ) -> TimelineState:
        self.timelines.append(timeline)
        self.guides.append(guides)
        self.finished.set()
        if self._error is not None:
            raise self._error
        return self._filled


class _SlowEngine(_Engine):
    """Blocks until released, so a second request can be attempted mid-fill."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.started = threading.Event()

    def inbetween(
        self, timeline: TimelineState, guides: dict[int, JointPose] | object = None
    ) -> TimelineState:
        self.timelines.append(timeline)
        self.guides.append(guides)
        self.started.set()
        assert self.release.wait(timeout=5.0), "the test never released the engine"
        self.finished.set()
        return self._filled


class _DisposableEngine(_Engine):
    """An engine that owns out-of-process resources: it offers ``shutdown``."""

    def __init__(self) -> None:
        super().__init__()
        self.released = False

    def shutdown(self) -> None:
        self.released = True


@pytest.fixture
def runner_factory(qtbot):  # noqa: ARG001 - pytest-qt owns the QApplication
    created: list[InbetweeningRunner] = []

    def build(engine) -> InbetweeningRunner:
        runner = InbetweeningRunner(engine)
        created.append(runner)
        return runner

    yield build

    for runner in created:
        runner.shutdown()


def test_starting_returns_before_the_engine_finishes(runner_factory) -> None:
    # NFR-02: the request cannot wait for the diffusion sampling, or the window
    # freezes for seconds.
    engine = _SlowEngine()
    runner = runner_factory(engine)

    started = runner.start(_timeline())

    assert started is True
    assert engine.started.wait(timeout=5.0), "the engine never ran"
    assert runner.busy is True  # still in flight: start() did not block on it
    engine.release.set()
    assert engine.finished.wait(timeout=5.0)


def test_a_second_request_while_one_runs_is_refused(runner_factory) -> None:
    # Batch size 1: a second fill must not pile up GPU work behind the first.
    engine = _SlowEngine()
    runner = runner_factory(engine)
    runner.start(_timeline())
    assert engine.started.wait(timeout=5.0)

    refused = runner.start(_timeline())

    assert refused is False
    assert len(engine.timelines) == 1  # the second timeline was never handed over
    engine.release.set()
    assert engine.finished.wait(timeout=5.0)


def test_guides_reach_the_engine_intact(runner_factory, qtbot) -> None:
    # S6: the controller hands captured poses over as guides; the runner is
    # only transport, so they must arrive as passed, never re-shaped.
    engine = _Engine()
    runner = runner_factory(engine)
    guides = {5: JointPose(rotation=Quaternion.identity())}

    runner.start(_timeline(), guides=guides)
    qtbot.waitUntil(lambda: engine.finished.is_set(), timeout=5000)

    assert engine.guides == [guides]


def test_a_result_is_the_timeline_the_engine_returned(runner_factory, qtbot) -> None:
    engine = _Engine()
    runner = runner_factory(engine)
    results: list[TimelineState] = []
    runner.filled.connect(results.append)
    requested = _timeline()

    assert runner.start(requested) is True
    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

    assert results[0] is engine._filled  # the payload, not a re-wrap of it
    assert engine.timelines == [requested]  # the requested timeline was issued


def test_the_runner_reports_when_it_is_free_again(runner_factory, qtbot) -> None:
    engine = _Engine()
    runner = runner_factory(engine)
    busy: list[bool] = []
    runner.busy_changed.connect(busy.append)

    runner.start(_timeline())
    qtbot.waitUntil(lambda: runner.busy is False, timeout=5000)

    assert busy == [True, False]


def test_an_engine_failure_is_reported_and_never_raised(runner_factory, qtbot) -> None:
    # FR-GEN-03: a failed fill is non-fatal, and it must not escape into the Qt
    # event loop; the timeline keeps its keys.
    engine = _Engine(error=RuntimeError("the CondMDI checkpoint is missing"))
    runner = runner_factory(engine)
    failures: list[str] = []
    runner.failed.connect(failures.append)

    runner.start(_timeline())
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    assert failures == ["the CondMDI checkpoint is missing"]
    assert runner.busy is False


def test_a_bare_exception_is_still_named(runner_factory, qtbot) -> None:
    # ``str(RuntimeError())`` is empty: the report must still say something.
    engine = _Engine(error=RuntimeError())
    runner = runner_factory(engine)
    failures: list[str] = []
    runner.failed.connect(failures.append)

    runner.start(_timeline())
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    assert failures == ["RuntimeError"]


def test_shutdown_releases_the_engine(runner_factory, qtbot) -> None:
    # Teardown: a persistent out-of-process engine (its checkpoint loaded once)
    # must terminate when the window closes. The runner owns the engine's
    # lifecycle at teardown: the window knows nothing about processes.
    engine = _DisposableEngine()
    runner = runner_factory(engine)

    runner.start(_timeline())
    qtbot.waitUntil(lambda: engine.finished.is_set(), timeout=5000)
    runner.shutdown()

    assert engine.released is True
    assert runner.busy is False


def test_shutdown_releases_the_engine_even_without_work_in_flight(runner_factory, qtbot) -> None:
    engine = _DisposableEngine()
    runner = runner_factory(engine)

    runner.shutdown()

    assert engine.released is True
