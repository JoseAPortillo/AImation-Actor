"""Tests for the capture window (S4, S6, S8, S9, S12).

Real playback and pixel output stay manual checks. What is pinned here is the
wiring the specs describe: which key does what, and that the video pane, the
timeline and the 3D pane all follow one time indicator (plan §3.B).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal
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
from aimation_actor.core.services import build_production_pose


class _ConstantEngine:
    """A deterministic engine, so the window's wiring is checked without a GPU."""

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        return WorldPose(translation=Vector3(z=140.0), rotations={})


class _FakeSource(QObject):
    """A headless video source: it records what it was asked to do."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.played = 0
        self.paused = 0
        self.seeks: list[tuple[int, float]] = []
        self.grabs = 0
        self._frame = FrameImage(width=1, height=1, rgb=bytes(3))

    def open(self, path: str) -> None:
        self.opened.append(path)

    def play(self) -> None:
        self.played += 1

    def pause(self) -> None:
        self.paused += 1

    def seek_frame(self, frame: int, fps: float) -> None:
        self.seeks.append((frame, fps))

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        self.grabs += 1
        return CapturedFrame(image=self._frame, frame_index=None)


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
def window(qtbot, source: _FakeSource) -> MainWindow:
    window = MainWindow(source=source, skeleton=_skeleton(), engine=_ConstantEngine())
    qtbot.addWidget(window)
    return window


def _load_two_seconds(window: MainWindow, source: _FakeSource) -> None:
    """Load a clip: 2000 ms at 24 fps is 48 frames, so the range is 0..47."""
    window.load_video("clip.mp4")
    source.media_loaded.emit(24.0, 2000)


def test_the_window_puts_the_video_beside_the_viewport(window: MainWindow) -> None:
    # plan §3.B: a split-view interface.
    assert window.splitter.orientation() == Qt.Orientation.Horizontal
    assert window.splitter.count() == 2
    assert window.splitter.widget(1) is window.viewport


def test_a_window_without_a_rig_says_so_in_the_3d_pane(qtbot, source: _FakeSource) -> None:
    # M4 ships before the production skeleton exists (that is M5's job), so the
    # pane has to name that blank instead of looking like a failed load (NFR-03).
    window = MainWindow(source=source)
    qtbot.addWidget(window)

    assert "No rig" in window.viewport.notice_label.text()


def test_the_shortcuts_are_the_ones_the_plan_names(window: MainWindow) -> None:
    # plan §3.A / S4: the exact key bindings, not an approximation.
    assert window.action_play_pause.shortcut() == QKeySequence("Space")
    assert window.action_step_back.shortcut() == QKeySequence("Left")
    assert window.action_step_forward.shortcut() == QKeySequence("Right")
    assert window.action_mark.shortcut() == QKeySequence("K")
    assert window.action_remove_key.shortcut() == QKeySequence("Delete")
    assert window.action_next_key.shortcut() == QKeySequence("Shift+Right")
    assert window.action_previous_key.shortcut() == QKeySequence("Shift+Left")


def test_the_status_reports_the_loaded_clip(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    report = window.statusBar().currentMessage()
    assert "clip.mp4" in report
    assert "48" in report


def test_the_timeline_and_the_viewport_share_the_playhead(
    window: MainWindow, source: _FakeSource
) -> None:
    # plan §3.B: both panes are linked to the same time indicator.
    _load_two_seconds(window, source)

    window.action_step_forward.trigger()

    assert window.controller.frame == 1
    assert window.timeline.frame == 1
    assert source.seeks[-1][0] == 1
    # Frame 1 carries no key, so the pane shows the rig in its neutral pose.
    assert window.viewport.segments != ()


def test_space_plays_and_pauses(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    window.action_play_pause.trigger()
    assert source.played == 1

    source.playback_changed.emit(True)
    window.action_play_pause.trigger()
    assert source.paused == 1


def test_the_arrow_keys_step_one_frame_at_a_time(window: MainWindow, source: _FakeSource) -> None:
    _load_two_seconds(window, source)

    window.action_step_forward.trigger()
    window.action_step_forward.trigger()
    window.action_step_back.trigger()

    assert window.controller.frame == 1
    assert window.controller.total_frames == 48


def test_k_marks_the_playhead_and_delete_removes_it(
    qtbot, window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()

    window.action_mark.trigger()
    # The pose is extracted off the UI thread, so the key lands a moment later
    # (M5, NFR-02) — but it lands on the frame that was marked.
    qtbot.waitUntil(lambda: window.controller.has_key(1), timeout=5000)
    assert window.timeline.key_strip.keys == (1,)

    window.action_remove_key.trigger()
    assert not window.controller.has_key(1)
    assert window.timeline.key_strip.keys == ()


def test_the_subject_distance_setting_writes_the_controller(window: MainWindow) -> None:
    """M8 S8: the GUI surface for the clip's depth-calibration distance.

    The spin starts at the controller's 3 m default and forwards every change
    to ``controller.subject_distance_m``, which ``_compute_depth_scale`` reads
    when the first captured frame locks the clip's calibration.
    """
    assert window.subject_distance.value() == pytest.approx(3.0)

    window.subject_distance.setValue(2.5)
    assert window.controller.subject_distance_m == pytest.approx(2.5)


def test_the_subject_distance_locks_after_the_first_key_and_frees_on_a_new_clip(
    qtbot, window: MainWindow, source: _FakeSource
) -> None:
    # Once per clip: the scale is fixed at the first captured frame, so a
    # mid-clip change would be a silent no-op — the GUI disables the setting
    # instead, and a freshly loaded clip re-arms it.
    _load_two_seconds(window, source)
    assert window.subject_distance.isEnabled()

    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(0), timeout=5000)
    assert not window.subject_distance.isEnabled()

    _load_two_seconds(window, source)
    assert window.subject_distance.isEnabled()


def test_shift_arrows_jump_between_golden_poses(
    qtbot, window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)
    window.controller.go_to_frame(10)
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(10), timeout=5000)

    window.controller.go_to_frame(30)
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(30), timeout=5000)

    window.controller.go_to_frame(20)
    window.action_next_key.trigger()
    assert window.controller.frame == 30

    window.action_previous_key.trigger()
    assert window.controller.frame == 10


def test_a_window_without_an_inbetween_engine_names_the_gap(
    qtbot, source: _FakeSource
) -> None:
    """Without an inbetween engine, ``G`` reports what is missing (NFR-03)."""
    window_no_filler = MainWindow(
        source=source, skeleton=_skeleton(), engine=_ConstantEngine()
    )
    qtbot.addWidget(window_no_filler)
    _load_two_seconds(window_no_filler, source)
    window_no_filler.action_fill_inbetweens.trigger()
    assert "No inbetweening engine" in window_no_filler.statusBar().currentMessage()
    assert window_no_filler.filler is None
    assert window_no_filler.action_fill_inbetweens.shortcut() == QKeySequence("G")


def test_g_runs_the_fill_off_the_ui_thread_and_reports_the_outcome(
    qtbot, source: _FakeSource
) -> None:
    class _IdentityFiller:
        requests: list = []

        def inbetween(self, timeline, guides=None):
            # The S6/T9 gather output travels with the timeline (joined keys,
            # one guide per interior frame); the identity filler ignores it.
            _IdentityFiller.requests.append((timeline, guides))
            return timeline

    window = MainWindow(
        source=source,
        skeleton=_skeleton(),
        engine=_ConstantEngine(),
        inbetween_engine=_IdentityFiller(),
    )
    qtbot.addWidget(window)
    _load_two_seconds(window, source)

    # Two golden poses: without them the controller refuses before the engine.
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(0), timeout=5000)
    window.controller.go_to_frame(10)
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(10), timeout=5000)

    window.action_fill_inbetweens.trigger()
    qtbot.waitUntil(
        lambda: "Generated" in window.statusBar().currentMessage(), timeout=5000
    )

    assert _IdentityFiller.requests  # the timeline reached the engine
    requested, guides = _IdentityFiller.requests[-1]
    assert requested.keyframes == window.controller.state.keyframes
    guides_at = build_production_pose(
        WorldPose(translation=Vector3(z=140.0), rotations={}), _skeleton()
    )
    assert guides == {frame: guides_at for frame in range(1, 10)}  # 0..10 is dense
    assert "Generated" in window.statusBar().currentMessage()


def test_the_open_action_hands_the_path_to_the_controller(
    window: MainWindow, source: _FakeSource
) -> None:
    window.load_video("clip.mp4")

    assert source.opened == ["clip.mp4"]
    assert window.action_open.shortcut() == QKeySequence("Ctrl+O")


def test_a_failed_open_is_reported_and_the_capture_stays_usable(
    window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)

    source.failed.emit("Cannot decode clip.mp4.")

    assert "Cannot decode clip.mp4." in window.statusBar().currentMessage()
    assert window.controller.has_media  # the loaded clip survives (FR-CAP-01)

    window.action_step_forward.trigger()  # and the session keeps working
    assert window.controller.frame == 1


class _RecordingExporter:
    """A seam exporter: it records exactly what the window asked it to write."""

    def __init__(self) -> None:
        self.saved: list[tuple[object, Path]] = []

    def save(self, state, path) -> None:
        self.saved.append((state, path))


class _FailingExporter:
    """A writer that always fails, to prove the failure is non-fatal."""

    def save(self, state, path) -> None:
        raise RuntimeError("disk full")


def _choose(monkeypatch, value) -> None:
    """Point the save dialog at a canned answer."""
    monkeypatch.setattr(
        "aimation_actor.adapters.gui.main_window.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: value),
    )


def test_ctrl_e_exports_the_approved_timeline(
    qtbot, monkeypatch, window: MainWindow, source: _FakeSource
) -> None:
    exporter = _RecordingExporter()
    window.exporter = exporter
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(1), timeout=5000)

    state = window.controller.state
    _choose(monkeypatch, ("out.fbx", "Binary FBX (*.fbx)"))

    window.action_export.trigger()

    assert exporter.saved == [(state, Path("out.fbx"))]
    assert "out.fbx" in window.statusBar().currentMessage()


def test_the_export_action_lives_in_the_file_menu(window: MainWindow) -> None:
    assert window.action_export.shortcut() == QKeySequence("Ctrl+E")


def test_an_empty_timeline_refuses_to_export(
    monkeypatch, window: MainWindow, source: _FakeSource
) -> None:
    exporter = _RecordingExporter()
    window.exporter = exporter
    _load_two_seconds(window, source)  # media loaded, but no Golden Pose yet
    _choose(monkeypatch, ("out.fbx", "Binary FBX (*.fbx)"))

    window.action_export.trigger()

    assert exporter.saved == []
    assert "no Golden Pose" in window.statusBar().currentMessage()


def test_a_failed_write_is_reported_non_fatally(
    qtbot, monkeypatch, window: MainWindow, source: _FakeSource
) -> None:
    window.exporter = _FailingExporter()
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(1), timeout=5000)
    _choose(monkeypatch, ("out.fbx", "Binary FBX (*.fbx)"))

    window.action_export.trigger()  # must not raise

    assert "disk full" in window.statusBar().currentMessage()
    assert window.controller.has_media  # the session stays usable


def test_a_cancelled_dialog_saves_nothing(
    qtbot, monkeypatch, window: MainWindow, source: _FakeSource
) -> None:
    exporter = _RecordingExporter()
    window.exporter = exporter
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(1), timeout=5000)
    _choose(monkeypatch, ("", ""))

    window.action_export.trigger()

    assert exporter.saved == []
    assert window.statusBar().currentMessage() != ""


def test_export_without_a_writer_reports_the_gap(
    qtbot, monkeypatch, window: MainWindow, source: _FakeSource
) -> None:
    _load_two_seconds(window, source)
    window.action_step_forward.trigger()
    window.action_mark.trigger()
    qtbot.waitUntil(lambda: window.controller.has_key(1), timeout=5000)
    _choose(monkeypatch, ("out.fbx", "Binary FBX (*.fbx)"))

    window.action_export.trigger()  # no exporter configured (defaults)

    assert "no FBX writer" in window.statusBar().currentMessage()
