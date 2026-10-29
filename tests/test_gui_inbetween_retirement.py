"""Tests for the inbetweening UI retirement (pipeline redesign, 2026-10-29).

The maintainer's decision: the generative fill only makes sense AFTER the
animator refines the sparse export in Blender (retarget → edit → re-import),
never on the raw captures that refinement is about to replace. The window
therefore loses the Inbetweens menu and the ``G`` action — while the whole
machine behind it stays injected and green: controller, runner, adapter,
worker, guides, pinning. Re-positioning the feature later is one menu line,
not a rebuild; these pins are what prove both halves of that promise.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointData,
    Skeleton,
    Vector3,
    WorldPose,
)


class _FakeSource(QObject):
    """A headless video source with one constant frame to grab."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._frame = FrameImage(width=1, height=1, rgb=bytes(3))

    def open(self, path: str) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None: ...

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        return CapturedFrame(image=self._frame, frame_index=None)


class _ConstantEngine:
    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        return WorldPose(translation=Vector3(z=140.0), rotations={})


class _IdentityFiller:
    requests: list = []

    def inbetween(self, timeline, guides=None):
        _IdentityFiller.requests.append((timeline, guides))
        return timeline


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main"),
        )
    )


@pytest.fixture
def window(qtbot):
    source = _FakeSource()
    main = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(main)
    main.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)
    return main, source


# -- the retired surface ------------------------------------------------------ #


def test_the_window_has_no_inbetweens_menu(window) -> None:
    main, _ = window
    titles = [action.text() for action in main.menuBar().actions()]

    assert not any("inbetween" in title.lower() for title in titles)


def test_the_window_has_no_fill_action(window) -> None:
    main, _ = window

    assert not hasattr(main, "action_fill_inbetweens")


def test_g_is_not_bound_to_anything(window) -> None:
    # The retirement must not leave a dangling shortcut: G asks for nothing.
    main, _ = window
    sequences = {
        action.shortcut()
        for action in main.actions()
        if action.shortcut() != QKeySequence()
    }

    assert QKeySequence("G") not in sequences


# -- the machinery that survives ---------------------------------------------- #


def test_the_controller_still_owns_a_working_fill(qtbot) -> None:
    # Parked, not deleted: calling the documented entry point still runs the
    # whole pipeline (guards included) and hands the timeline to the engine —
    # with no menu anywhere near it.
    source = _FakeSource()
    main = MainWindow(
        source=source,
        skeleton=_skeleton(),
        engine=_ConstantEngine(),
        inbetween_engine=_IdentityFiller(),
    )
    qtbot.addWidget(main)
    main.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)
    controller = main.controller
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    controller.fill_inbetweens()  # the two-key guard still lives in the controller
    assert any("at least two golden poses" in message for message in statuses)

    main.action_mark.trigger()
    qtbot.waitUntil(lambda: controller.has_key(0), timeout=5000)
    controller.go_to_frame(10)
    main.action_mark.trigger()
    qtbot.waitUntil(lambda: controller.has_key(10), timeout=5000)

    controller.fill_inbetweens()
    qtbot.waitUntil(lambda: bool(_IdentityFiller.requests), timeout=5000)

    requested, _guides = _IdentityFiller.requests[-1]
    assert requested.keyframes == controller.state.keyframes
