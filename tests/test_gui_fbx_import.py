"""Tests for the FBX import action and timeline adoption (FR-IMP-04).

The pipeline's second half: the animator refines the exported FBX in
Blender/Maya and re-imports it here (plan §3 step 2). The user's product
decision (2026-10-28): the imported timeline REPLACES the session's, asking
for confirmation first when captured keys exist; a failed read leaves the
session untouched (NFR-03). Capture-only bookkeeping (overlay snapshots,
depth calibration) does not survive the replacement — the imported keys never
came from those captures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
    WorldPose,
)


class _FakeSource(QObject):
    """A headless video source: records opens, always has a frame to grab."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self._frame = FrameImage(width=1, height=1, rgb=bytes(3))

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None: ...

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        return CapturedFrame(image=self._frame, frame_index=None)


class _ConstantEngine:
    """A deterministic engine so marking a key needs no GPU."""

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        return WorldPose(translation=Vector3(z=140.0), rotations={})


class _MemoryStore:
    def __init__(self) -> None:
        self.paths: tuple[str, ...] = ()

    def load(self) -> tuple[str, ...]:
        return self.paths

    def save(self, paths) -> None:
        self.paths = tuple(paths)


class _ImportingExporter:
    """An IOPort seam whose ``load`` returns a canned state (or raises)."""

    def __init__(self, state: TimelineState | None = None, error: Exception | None = None) -> None:
        self.state = state
        self.error = error
        self.loaded: list[Path] = []

    def load(self, path: Path) -> TimelineState:
        self.loaded.append(path)
        if self.error is not None:
            raise self.error
        assert self.state is not None
        return self.state

    def save(self, state: TimelineState, path: Path) -> None: ...


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )


def _pose() -> dict[str, JointPose]:
    return {"Pelvis": JointPose(rotation=Quaternion.identity())}


def _imported() -> TimelineState:
    """The refined FBX as the adapter converts it: its own rig, keys and range."""
    return TimelineState(
        skeleton=_skeleton(),
        keyframes=(Keyframe(frame=3, pose=_pose()), Keyframe(frame=7, pose=_pose())),
        fps=30.0,
        frame_start=3,
        frame_end=7,
    )


def _controller() -> tuple[CaptureController, _FakeSource]:
    source = _FakeSource()
    controller = CaptureController(
        source,
        TimelineState(skeleton=_skeleton(), fps=24.0, frame_end=47),
    )
    controller.open_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)  # 48 frames: the range is 0..47
    return controller, source


@pytest.fixture
def window(qtbot) -> tuple[MainWindow, _FakeSource]:
    source = _FakeSource()
    main = MainWindow(
        source=source,
        skeleton=_skeleton(),
        engine=_ConstantEngine(),
        recents=_MemoryStore(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(main)
    return main, source


def _load_two_seconds(main: MainWindow, source: _FakeSource) -> None:
    main.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)


def _mark_frame_zero(main: MainWindow, qtbot) -> None:
    main.action_mark.trigger()
    qtbot.waitUntil(lambda: main.controller.has_key(0), timeout=5000)


def _choose(monkeypatch, value) -> None:
    """Point the open dialog at a canned answer."""
    monkeypatch.setattr(
        "aimation_actor.adapters.gui.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *args, **kwargs: value),
    )


# -- the controller adoption ---------------------------------------------------- #


def test_adopt_imported_replaces_the_timeline_with_the_imported_one() -> None:
    controller, _ = _controller()
    imported = _imported()
    events: list[str] = []
    controller.timeline_changed.connect(lambda: events.append("timeline"))
    controller.pose_changed.connect(lambda _pose: events.append("pose"))
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    assert controller.adopt_imported(imported) is True

    assert controller.state is imported
    assert "timeline" in events and "pose" in events
    assert "Imported 2" in statuses[-1]


def test_adopt_imported_resets_capture_only_bookkeeping() -> None:
    # The imported keys were never captured, so the overlay snapshots and the
    # clip's depth calibration do not belong to the new timeline.
    controller, _ = _controller()
    controller._projections[5] = (("held",), ())
    controller._root_origin = Vector3()
    controller._depth_scale = 2.5

    assert controller.adopt_imported(_imported()) is True

    assert controller.overlay_snapshot_at(5) is None
    assert controller._root_origin is None
    assert controller._depth_scale == 1.0


def test_adopt_imported_clamps_the_playhead_into_the_new_range() -> None:
    controller, _ = _controller()
    controller.go_to_frame(40)

    assert controller.adopt_imported(_imported()) is True

    assert controller.frame == 7  # frame_end of the imported range


def test_adopt_imported_refuses_while_a_fill_is_in_flight() -> None:
    controller, _ = _controller()
    before = controller.state
    controller._fill_active = True
    failures: list[str] = []
    controller.failed.connect(failures.append)

    assert controller.adopt_imported(_imported()) is False

    assert controller.state is before
    assert "gap fill" in failures[0]


# -- the window action ------------------------------------------------------------ #


def test_the_file_menu_offers_import_fbx_with_ctrl_i(window) -> None:
    main, _ = window

    assert main.action_import.shortcut() == QKeySequence("Ctrl+I")
    assert "Import FBX" in main.action_import.text()


def test_importing_a_refined_fbx_replaces_the_timeline_after_confirmation(
    qtbot, monkeypatch, window
) -> None:
    main, source = window
    _load_two_seconds(main, source)
    _mark_frame_zero(main, qtbot)
    asks: list[int] = []
    main._confirm_replace = lambda count: asks.append(count) or True
    main.exporter = _ImportingExporter(_imported())  # type: ignore[assignment]

    _choose(monkeypatch, ("refined.fbx", "Binary FBX (*.fbx)"))
    main.action_import.trigger()

    assert asks == [1]  # it warned about the one captured key
    assert main.controller.state.frame_end == 7
    assert main.controller.state.frames() == (3, 7)
    assert "Imported 2" in main.statusBar().currentMessage()


def test_declining_the_confirmation_keeps_the_captured_timeline(
    qtbot, monkeypatch, window
) -> None:
    main, source = window
    _load_two_seconds(main, source)
    _mark_frame_zero(main, qtbot)
    before = main.controller.state
    main._confirm_replace = lambda _count: False
    main.exporter = _ImportingExporter(_imported())  # type: ignore[assignment]

    _choose(monkeypatch, ("refined.fbx", "Binary FBX (*.fbx)"))
    main.action_import.trigger()

    assert main.controller.state is before
    assert "cancelled" in main.statusBar().currentMessage().lower()


def test_an_import_over_an_empty_session_does_not_ask(
    monkeypatch, window
) -> None:
    main, _ = window
    asked: list[int] = []
    main._confirm_replace = lambda count: asked.append(count) or True
    main.exporter = _ImportingExporter(_imported())  # type: ignore[assignment]

    _choose(monkeypatch, ("refined.fbx", "Binary FBX (*.fbx)"))
    main.action_import.trigger()

    assert asked == []  # nothing to lose, nothing to confirm
    assert main.controller.state.frame_end == 7


def test_a_failed_import_leaves_the_session_usable(qtbot, monkeypatch, window) -> None:
    main, source = window
    _load_two_seconds(main, source)
    _mark_frame_zero(main, qtbot)
    before = main.controller.state
    main.exporter = _ImportingExporter(error=RuntimeError("not an FBX"))  # type: ignore[assignment]

    _choose(monkeypatch, ("broken.fbx", "Binary FBX (*.fbx)"))
    main.action_import.trigger()

    assert main.controller.state is before
    assert "Import failed: not an FBX" in main.statusBar().currentMessage()


def test_import_without_a_configured_reader_reports_the_gap(
    monkeypatch, window
) -> None:
    main, _ = window
    assert main.exporter is None
    _choose(monkeypatch, ("refined.fbx", "Binary FBX (*.fbx)"))

    main.action_import.trigger()

    assert "no FBX reader" in main.statusBar().currentMessage()


def test_cancelling_the_file_dialog_changes_nothing(monkeypatch, window) -> None:
    main, _ = window
    before = main.controller.state
    main.exporter = _ImportingExporter(_imported())  # type: ignore[assignment]
    assert main.exporter is not None
    exported_loaded_before = len(main.exporter.loaded)

    _choose(monkeypatch, ("", "Binary FBX (*.fbx)"))
    main.action_import.trigger()

    assert main.controller.state is before
    assert len(main.exporter.loaded) == exported_loaded_before
