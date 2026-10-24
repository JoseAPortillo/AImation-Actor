"""Tests for the controller's inbetween generation (M6 T4 · FR-GEN-01, FR-GEN-02, FR-GEN-03).

The fill is an **asynchronous** request, like marking: the engine runs off the
UI thread, the result is adopted only if it still belongs to the open clip, and
a failure is non-fatal — the keys survive (S1 hard constraints, FR-GEN-01).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)


class _FakeSource(QObject):
    """The video-source seam, in memory."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.seeks: list[tuple[int, float]] = []

    def open(self, path: str) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None:
        self.seeks.append((frame, fps))

    def grab_frame(self, fps: float):  # noqa: ANN201 - seams return domain or None
        return None


class _FakeInbetweener(QObject):
    """The inbetweening seam: records the request; the test scripts the outcome."""

    filled = Signal(object)
    failed = Signal(str)

    def __init__(self, result: TimelineState | None = None) -> None:
        super().__init__()
        self.requests: list[tuple[TimelineState, dict[int, dict[str, JointPose]] | None]] = []
        self.refuse = False
        self.result = result

    def start(
        self, timeline: TimelineState, guides: dict[int, dict[str, JointPose]] | None = None
    ) -> bool:
        if self.refuse:
            return False
        self.requests.append((timeline, guides))
        return True


class _FakeExtractor(QObject):
    """Unused by these tests; the controller accepts both engines."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def start(self, frame_index: int, image) -> bool:  # noqa: ANN001
        return False


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main"),
        )
    )


def _pose() -> dict:
    return {"Pelvis": JointPose(rotation=Quaternion.identity())}


def _keys(*frames: int) -> tuple[Keyframe, ...]:
    return tuple(Keyframe(frame=frame, pose=_pose()) for frame in frames)


def _timeline() -> TimelineState:
    # Adjacent keys: a deliberately guide-free plan, so the T4 contract tests
    # (hand-off, adoption, refusals) run without the gather machinery; the
    # spaced and dense guide plans have their own file.
    return TimelineState(
        skeleton=_skeleton(), keyframes=_keys(1, 2), fps=24.0, frame_end=10
    )


def _filled() -> TimelineState:
    return TimelineState(
        skeleton=_skeleton(), keyframes=_keys(1, 2, 3, 4), fps=24.0, frame_end=10
    )


def _root_pose(x: float) -> dict[str, JointPose]:
    return {
        "Main": JointPose(
            rotation=Quaternion.identity(), translation=Vector3(x=x)
        ),
        "Pelvis": JointPose(rotation=Quaternion.identity()),
    }


def test_a_fill_adopted_smooths_interior_root_jitter_and_keeps_keys() -> None:
    """M8 S5: the filled rows' ``Main`` translation is jitter-reduced before
    adoption, and the original keys keep their exact captured values."""
    value = 30.0
    source = _FakeSource()
    extractor = _FakeExtractor()
    filler = _FakeInbetweener(
        result=TimelineState(
            skeleton=_skeleton(),
            keyframes=(
                Keyframe(frame=1, pose=_root_pose(0.0)),
                Keyframe(frame=12, pose=_root_pose(0.0)),
            )
            + tuple(
                Keyframe(frame=frame, pose=_root_pose(value if frame % 2 else -value))
                for frame in range(2, 12)
            ),
            fps=24.0,
            frame_end=20,
        )
    )
    controller = CaptureController(
        source,
        TimelineState(skeleton=_skeleton(), keyframes=_keys(1, 12), fps=24.0, frame_end=20),
        extractor=extractor,
        inbetweener=filler,
    )
    controller.fill_inbetweens()

    filler.filled.emit(filler.result)

    poses = {kf.frame: kf.pose for kf in controller.state.keyframes}
    assert poses[1]["Main"].translation.x == 0.0  # keys untouched
    assert poses[12]["Main"].translation.x == 0.0
    worst = max(abs(poses[frame]["Main"].translation.x) for frame in range(2, 12))
    assert worst <= value / 2


@pytest.fixture
def source() -> _FakeSource:
    return _FakeSource()


@pytest.fixture
def extractor() -> _FakeExtractor:
    return _FakeExtractor()


@pytest.fixture
def controller(source: _FakeSource, extractor: _FakeExtractor) -> CaptureController:
    state = _timeline()
    return CaptureController(source, state, extractor=extractor)


def _with_filler(
    controller: CaptureController, filler: _FakeInbetweener
) -> tuple[CaptureController, _FakeInbetweener]:
    return controller, filler


def test_filling_hands_the_timeline_to_the_engine_and_adopts_the_result(
    qtbot, source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener(result=_filled())
    controller = CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=filler
    )
    changed: list[int] = []
    controller.timeline_changed.connect(lambda: changed.append(1))
    poses: list[int] = []
    controller.pose_changed.connect(lambda _pose: poses.append(1))

    controller.fill_inbetweens()
    filler.filled.emit(filler.result)

    assert len(filler.requests) == 1
    # The timeline at request time — the original sparse one, before adoption.
    requested, _guides = filler.requests[0]
    assert requested.keyframes == _keys(1, 2)
    assert len(controller.state.keyframes) == 4  # 1..4: every gap frame now keyed
    assert changed and poses  # both the bar and the 3D pane follow the result


def test_filling_needs_at_least_two_keys(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener()
    lone = TimelineState(
        skeleton=_skeleton(), keyframes=_keys(1), fps=24.0, frame_end=10
    )
    controller = CaptureController(
        source, lone, extractor=extractor, inbetweener=filler
    )
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert filler.requests == []  # nothing was ever handed over
    assert reports and "two golden poses" in reports[-1]


def test_filling_without_an_engine_reports_and_attempts_nothing(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    controller = CaptureController(source, _timeline(), extractor=extractor)
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert "No inbetweening engine" in (
        reports[-1] if reports else controller.status()
    )


def test_a_refused_fill_reports_the_engine_is_busy(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener()
    filler.refuse = True
    controller = CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=filler
    )
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert filler.requests == []
    assert reports and "already being generated" in reports[-1]


def test_a_failed_fill_is_reported_and_the_keys_survive(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener()
    controller = CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=filler
    )
    failures: list[str] = []
    controller.failed.connect(failures.append)
    state_before = controller.state

    controller.fill_inbetweens()
    filler.failed.emit("the CondMDI checkpoint is missing")

    assert failures and "CondMDI checkpoint" in failures[-1]
    assert controller.state is state_before  # S1: the keys survive a failure


def test_inbetweens_for_a_replaced_clip_are_discarded(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener(result=_filled())
    controller = CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=filler
    )
    failures: list[str] = []
    controller.failed.connect(failures.append)
    controller.fill_inbetweens()  # the claim is in flight; emission is scripted

    source.media_loaded.emit(24.0, 5000)  # a new clip bumps the generation
    filler.filled.emit(filler.result)  # the stale result lands now

    assert controller.state is not filler.result
    # A fresh clip starts an EMPTY timeline (FR-CAP-03); the stale fill must
    # not have rewritten it with the previous clip's keys.
    assert controller.state.keyframes == ()
    assert failures and "no longer open" in failures[-1]


def test_a_successful_fill_reports_what_it_generated(
    source: _FakeSource, extractor: _FakeExtractor
) -> None:
    filler = _FakeInbetweener(result=_filled())
    controller = CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=filler
    )
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()
    filler.filled.emit(filler.result)

    assert any("2 inbetween" in report for report in reports)
