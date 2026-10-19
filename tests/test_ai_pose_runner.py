"""Tests for the off-thread pose runner (M5 S3, S4, S6 · NFR-02, FR-CAP-05).

What matters here is the isolation and the two rules it enforces:

- the UI is never blocked, so ``start`` must return before the engine finishes;
- at most one extraction is in flight, so a second request is refused;
- an engine failure is reported, never raised into the Qt event loop.
"""

from __future__ import annotations

import threading

import pytest

from aimation_actor.adapters.ai.pose_runner import PoseExtractionRunner
from aimation_actor.core.models import FrameImage, Quaternion, Vector3, WorldPose


def _frame() -> FrameImage:
    return FrameImage(width=2, height=2, rgb=bytes(2 * 2 * 3))


def _pose(z: float = 100.0) -> WorldPose:
    return WorldPose(translation=Vector3(z=z), rotations={"Pelvis": Quaternion.identity()})


class _Engine:
    """A deterministic engine that reports what it was asked to extract."""

    def __init__(self, *, pose: WorldPose | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[int, FrameImage]] = []
        self._pose = _pose() if pose is None else pose
        self._error = error
        self.finished = threading.Event()

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        self.calls.append((frame_index, image))
        self.finished.set()
        if self._error is not None:
            raise self._error
        return self._pose


class _SlowEngine(_Engine):
    """Blocks until released, so a second request can be attempted mid-flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.started = threading.Event()

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        self.calls.append((frame_index, image))
        self.started.set()
        assert self.release.wait(timeout=5.0), "the test never released the engine"
        self.finished.set()
        return self._pose


class _DisposableEngine(_Engine):
    """An engine that owns out-of-process resources: it offers ``shutdown``."""

    def __init__(self) -> None:
        super().__init__()
        self.released = False

    def shutdown(self) -> None:
        self.released = True


@pytest.fixture
def runner_factory(qtbot):  # noqa: ARG001 - pytest-qt owns the QApplication
    created: list[PoseExtractionRunner] = []

    def build(engine) -> PoseExtractionRunner:
        runner = PoseExtractionRunner(engine)
        created.append(runner)
        return runner

    yield build

    for runner in created:
        runner.shutdown()


def test_starting_returns_before_the_engine_finishes(runner_factory) -> None:
    # NFR-02: the request cannot wait for the inference, or the window freezes.
    engine = _SlowEngine()
    runner = runner_factory(engine)

    started = runner.start(7, _frame())

    assert started is True
    assert engine.started.wait(timeout=5.0), "the engine never ran"
    assert runner.busy is True  # still in flight: start() did not block on it
    engine.release.set()
    assert engine.finished.wait(timeout=5.0)


def test_a_second_request_while_one_runs_is_refused(runner_factory) -> None:
    # S4 / plan §4: batch size 1. A held key must not pile up GPU work.
    engine = _SlowEngine()
    runner = runner_factory(engine)
    runner.start(7, _frame())
    assert engine.started.wait(timeout=5.0)

    refused = runner.start(8, _frame())

    assert refused is False
    assert len(engine.calls) == 1  # the second frame was never handed over
    engine.release.set()
    assert engine.finished.wait(timeout=5.0)


def test_a_result_carries_the_frame_it_was_extracted_from(runner_factory, qtbot) -> None:
    engine = _Engine(pose=_pose(z=123.0))
    runner = runner_factory(engine)
    results: list[tuple[int, WorldPose]] = []
    runner.extracted.connect(lambda frame, pose: results.append((frame, pose)))

    assert runner.start(42, _frame()) is True
    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

    frame_index, pose = results[0]
    assert frame_index == 42  # attributed to its own frame, not to "now"
    assert pose.translation.z == pytest.approx(123.0)
    assert engine.calls[0][0] == 42


def test_the_runner_reports_when_it_is_free_again(runner_factory, qtbot) -> None:
    engine = _Engine()
    runner = runner_factory(engine)
    busy: list[bool] = []
    runner.busy_changed.connect(busy.append)

    runner.start(1, _frame())
    qtbot.waitUntil(lambda: runner.busy is False, timeout=5000)

    assert busy == [True, False]


def test_an_engine_failure_is_reported_and_never_raised(runner_factory, qtbot) -> None:
    # S6 / FR-CAP-07: a failed extraction is non-fatal, and it must not escape
    # into the Qt event loop.
    engine = _Engine(error=RuntimeError("GVHMR weights are not available"))
    runner = runner_factory(engine)
    failures: list[tuple[int, str]] = []
    runner.failed.connect(lambda frame, message: failures.append((frame, message)))

    runner.start(9, _frame())
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    frame_index, message = failures[0]
    assert frame_index == 9
    assert message == "GVHMR weights are not available"
    assert runner.busy is False


def test_a_bare_exception_is_still_named(runner_factory, qtbot) -> None:
    # ``str(RuntimeError())`` is empty: the report must still say something.
    engine = _Engine(error=RuntimeError())
    runner = runner_factory(engine)
    failures: list[str] = []
    runner.failed.connect(lambda _frame, message: failures.append(message))

    runner.start(0, _frame())
    qtbot.waitUntil(lambda: len(failures) == 1, timeout=5000)

    assert failures == ["RuntimeError"]


def test_shutdown_releases_the_engine(runner_factory, qtbot) -> None:
    # FR-CAP-05, teardown: a persistent out-of-process engine (its checkpoint
    # loaded once) must terminate when the window closes. The runner owns the
    # engine's lifecycle at teardown: the window knows nothing about processes.
    engine = _DisposableEngine()
    runner = runner_factory(engine)

    runner.start(0, _frame())
    qtbot.waitUntil(lambda: engine.finished.is_set(), timeout=5000)
    runner.shutdown()

    assert engine.released is True
    assert runner.busy is False


def test_shutdown_releases_the_engine_even_without_work_in_flight(runner_factory, qtbot) -> None:
    engine = _DisposableEngine()
    runner = runner_factory(engine)

    runner.shutdown()

    assert engine.released is True
