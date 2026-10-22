"""The controller's guide gathering for the fill (M6 T8, S6).

Before the fill starts, the capture frames between the keys condition the
engine: the controller extracts guide poses through the existing HMR2 runner
machinery (batch-1, off the UI thread), one guide every ~12 engine samples
and at most 8 per gap (S6), and hands them over with the timeline. Guides
are **not** keys: the keys win, and a guide that cannot be extracted or a
missing capture engine degrades the fill to keys-only — a typed status, not
a new failure class.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import (
    CaptureController,
    guide_frames_between,
)
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)
from aimation_actor.core.services import build_production_pose

# --------------------------------------------------------------------------- #
# Guide spacing (S6: every ~12 engine samples, at most 8 per gap)
# --------------------------------------------------------------------------- #


def test_guides_are_spaced_a_dozen_engine_samples() -> None:
    # 12 engine samples at the 20 fps motion clock -> ~14.4 timeline frames
    # at 24 fps; the candidates start one spacing after the key.
    assert guide_frames_between((0, 34), fps=24.0) == [14, 28]


def test_guides_span_several_gaps_in_order() -> None:
    assert guide_frames_between((0, 15, 30), fps=24.0) == [14, 29]


def test_guides_per_gap_are_capped() -> None:
    guides = guide_frames_between((0, 200), fps=24.0)
    assert len(guides) <= 8
    assert guides == [14, 42, 70, 98, 126, 154, 182]  # evenly thinned, in order


def test_a_gap_narrower_than_the_spacing_gets_no_guides() -> None:
    assert guide_frames_between((0, 5), fps=24.0) == []


# --------------------------------------------------------------------------- #
# The gathering flow
# --------------------------------------------------------------------------- #


class _GuideSource(QObject):
    """The video-source seam for guide gathering: seek puts a frame on screen."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.seeks: list[tuple[int, float]] = []
        # The frame the pane really shows after the last seek (synchronous
        # backend); ``None`` while the seek is still delivering, like a real one.
        self.onscreen: int | None = None
        self.deferred: int = 0  # how many seeks still answer after a delay

    def open(self, path: str) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None:
        self.seeks.append((frame, fps))
        if self.deferred > 0:
            self.deferred -= 1
            self.onscreen = None
        else:
            self.onscreen = frame

    def grab_frame(self, fps: float):
        # noqa: ANN201 - seams return domain or None
        if self.onscreen is None:
            return None
        from aimation_actor.core.models import CapturedFrame, FrameImage

        return CapturedFrame(
            image=FrameImage(width=1, height=1, rgb=bytes(3)),
            frame_index=self.onscreen,
        )


class _GuideExtractor(QObject):
    """The extraction seam for guides: by default it answers on the spot."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[int, object]] = []
        self.refuse = False
        self.failure: str | None = None
        self.auto_reply = True  # scripts the answer inside start(), like tests above
        self._hip_height = 140.0

    def _world_pose(self) -> WorldPose:
        return WorldPose(translation=Vector3(z=self._hip_height), rotations={})

    def start(self, frame_index: int, image) -> bool:  # noqa: ANN001
        self.requests.append((frame_index, image))
        if self.refuse:
            return False
        if self.failure is not None:
            self.failed.emit(frame_index, self.failure)
            return True
        if self.auto_reply:
            self.extracted.emit(frame_index, self._world_pose())
        return True

    def complete(self, frame_index: int, *, fail: bool = False) -> None:
        """Deliver a queued extraction's result later (a slow engine)."""
        if fail:
            self.failed.emit(frame_index, "the checkpoint could not load")
        else:
            self.extracted.emit(frame_index, self._world_pose())


class _GuideInbetweener(QObject):
    """The inbetweening seam: records the request; the test scripts the outcome."""

    filled = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[TimelineState, dict[int, dict[str, JointPose]] | None]] = []
        self.refuse = False

    def start(
        self, timeline: TimelineState, guides: dict[int, dict[str, JointPose]] | None = None
    ) -> bool:
        if self.refuse:
            return False
        self.requests.append((timeline, guides))
        return True


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )


def _pose() -> dict:
    return {"Pelvis": JointPose(rotation=Quaternion.identity())}


def _timeline() -> TimelineState:
    keys = (Keyframe(frame=0, pose=_pose()), Keyframe(frame=34, pose=_pose()))
    return TimelineState(skeleton=_skeleton(), keyframes=keys, fps=24.0, frame_end=40)


def _build_controller(
    source: _GuideSource,
    extractor: _GuideExtractor | None,
    inbetweener: _GuideInbetweener,
) -> CaptureController:
    return CaptureController(
        source, _timeline(), extractor=extractor, inbetweener=inbetweener
    )


# --------------------------------------------------------------------------- #
# Gathering: the happy path
# --------------------------------------------------------------------------- #


def test_a_fill_extracts_guides_and_hands_them_to_the_engine() -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)

    controller.fill_inbetweens()

    assert source.seeks == [(14, 24.0), (28, 24.0)]  # the guide plan, in order
    assert [frame for frame, _image in extractor.requests] == [14, 28]
    expected = build_production_pose(
        WorldPose(translation=Vector3(z=140.0), rotations={}), _skeleton()
    )
    assert len(filler.requests) == 1
    timeline, guides = filler.requests[0]
    assert timeline.keyframes == _timeline().keyframes  # the sparse one, unchanged
    assert guides == {14: expected, 28: expected}
    # Guides are not keys: the timeline still holds exactly the two keys.
    assert len(controller.state.keyframes) == 2


def test_no_capture_engine_fills_keys_only() -> None:
    source = _GuideSource()
    filler = _GuideInbetweener()
    controller = _build_controller(source, None, filler)
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert source.seeks == []  # nothing was captured on demand
    assert len(filler.requests) == 1
    assert filler.requests[0][1] is None


def test_a_refused_extraction_degrades_to_keys_only() -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    extractor.refuse = True
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert source.seeks == [(14, 24.0)]  # the first guide was attempted
    assert len(filler.requests) == 1
    assert filler.requests[0][1] is None
    assert any("golden poses" in report for report in reports)


def test_a_failed_extraction_degrades_to_keys_only() -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    extractor.failure = "the HMR2 checkpoint is missing"
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)

    controller.fill_inbetweens()

    assert len(filler.requests) == 1
    assert filler.requests[0][1] is None


def test_a_slow_engine_that_fails_degrades_to_keys_only(qtbot) -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    extractor.auto_reply = False
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)

    controller.fill_inbetweens()
    assert filler.requests == []  # still gathering

    extractor.complete(14, fail=True)

    qtbot.waitUntil(lambda: len(filler.requests) == 1, timeout=1000)
    assert filler.requests[0][1] is None


def test_a_clip_replaced_mid_gather_discards_the_fill(qtbot) -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    extractor.auto_reply = False
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    controller.fill_inbetweens()
    source.media_loaded.emit(24.0, 5000)  # a new clip bumps the generation
    extractor.complete(14)  # the stale guide extraction lands now

    assert filler.requests == []  # the fill never started
    assert failures and "no longer open" in failures[-1]


def test_a_second_fill_while_gathering_is_refused(qtbot) -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    extractor.auto_reply = False
    filler = _GuideInbetweener()
    controller = _build_controller(source, extractor, filler)
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()
    requested = len(extractor.requests)
    controller.fill_inbetweens()

    assert len(extractor.requests) == requested  # the second request did nothing
    assert filler.requests == []
    assert any("already being generated" in report for report in reports)

    extractor.complete(14)  # the original gather keeps flowing
    qtbot.waitUntil(lambda: len(extractor.requests) == 2, timeout=1000)
    extractor.complete(28)
    qtbot.waitUntil(lambda: len(filler.requests) == 1, timeout=1000)
    assert [frame for frame, _ in extractor.requests] == [14, 28]


def test_a_gathered_fill_refused_by_the_engine_frees_the_seam(qtbot) -> None:
    source = _GuideSource()
    extractor = _GuideExtractor()
    filler = _GuideInbetweener()
    filler.refuse = True
    controller = _build_controller(source, extractor, filler)
    reports: list[str] = []
    controller.status_changed.connect(reports.append)

    controller.fill_inbetweens()

    assert filler.requests == []
    assert any("already being generated" in report for report in reports)
    # The seam must be free afterwards: a new fill is accepted.
    filler.refuse = False
    controller.fill_inbetweens()
    qtbot.waitUntil(lambda: len(filler.requests) == 1, timeout=1000)
