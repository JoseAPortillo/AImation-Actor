"""The capture window: split view, timeline and shortcuts (plan §3.B, §3.A).

The window is the composition root of the capture UI. It builds the player, the
3D pane and the scrubber, and wires all three to one ``CaptureController``, which
owns the timeline and the playhead. Nothing here decides anything about the
timeline: it shows what the controller reports and forwards what the user asks
for, which is what keeps the shortcut behavior testable without a window on
screen.

The key bindings are the plan's §3.A list. ``Ctrl+O`` is added on top because
"open a reference video" (FR-CAP-01) needs a way in, and the plan reserves no
key for it.

Failures are reported in the status bar rather than a modal dialog. The plan
treats a failed mark or a damaged clip as non-fatal with the session still
usable (S5, NFR-03), and a modal box would block a session that can continue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from aimation_actor.adapters.ai.inbetween_runner import InbetweeningRunner
from aimation_actor.adapters.ai.pose_runner import PoseExtractionRunner
from aimation_actor.adapters.gui.capture_controller import CaptureController, VideoSource
from aimation_actor.adapters.gui.timeline_bar import TimelineBar
from aimation_actor.adapters.gui.video_player import VideoPlayer
from aimation_actor.adapters.gui.viewport_3d import SkeletonViewport
from aimation_actor.core.models import JointPose, Skeleton, TimelineState
from aimation_actor.ports.ai_port import AIPort, InbetweeningPort
from aimation_actor.ports.io_port import IOPort

__all__ = ["MainWindow"]

_VIDEO_FILTER = "Reference video (*.mp4 *.mov)"
_FBX_FILTER = "Binary FBX (*.fbx)"
_DEFAULT_FPS = 24.0


class MainWindow(QMainWindow):
    """The animator's capture surface: video, 3D preview, timeline, shortcuts."""

    def __init__(
        self,
        *,
        source: VideoSource | None = None,
        skeleton: Skeleton | None = None,
        engine: AIPort | None = None,
        skeleton_source: Callable[[], Skeleton | None] | None = None,
        inbetween_engine: InbetweeningPort | None = None,
        exporter: IOPort | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the window.

        ``source``, ``skeleton``, ``engine`` and ``skeleton_source`` exist so a
        caller can supply the player, the rig, the pose engine and where a rig
        comes from when there is not one yet; the defaults are the real player,
        an **empty rig**, and **no engine**. ``inbetween_engine`` supplies the
        generative engines the same way: without one, ``G`` reports what is
        missing rather than refusing silently. The composition root
        (``build_window``) injects the real engines — capture and inbetweening
        by name through the Model Factory (FR-GEN-02) — and a ``skeleton_source``
        that builds the production rig from the capture engine's own template
        report: the skeleton is real body-model data, adopted at the first
        successful extraction — never invented here. Without an engine or a rig
        source, ``K`` reports what is missing rather than writing a pose nobody
        computed. ``exporter`` (FR-GEN-04) is the FBX writer behind ``Ctrl+E``:
        without one, exporting reports the gap rather than writing nothing.
        """
        super().__init__(parent)
        self.setWindowTitle("AImation Actor")
        self.resize(1280, 800)

        state = TimelineState(
            skeleton=skeleton if skeleton is not None else Skeleton(joints=()),
            fps=_DEFAULT_FPS,
        )
        player = VideoPlayer() if source is None else source
        self._video_pane: QWidget = (
            player if isinstance(player, QWidget) else QLabel("No video pane.", self)
        )
        # The skeleton overlay rides on the real player's video surface; a
        # headless source pane has none (pose-video-overlay T3).
        self._video_overlay = player.overlay if isinstance(player, VideoPlayer) else None

        self.extractor = None if engine is None else PoseExtractionRunner(engine, self)
        self.filler = (
            None if inbetween_engine is None else InbetweeningRunner(inbetween_engine, self)
        )
        self.controller = CaptureController(
            player,
            state,
            self,
            extractor=self.extractor,
            skeleton_source=skeleton_source,
            inbetweener=self.filler,
        )
        self.exporter = exporter
        self.viewport = SkeletonViewport(self)
        self.timeline = TimelineBar(self)
        self._build_distance_control()

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self._video_pane)
        self.splitter.addWidget(self.viewport)
        self.splitter.setSizes([640, 640])

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.splitter, 1)
        self._build_progress_bar()
        bottom = QHBoxLayout()
        bottom.addWidget(self.timeline, 1)
        bottom.addWidget(self._distance_label)
        bottom.addWidget(self.subject_distance)
        layout.addLayout(bottom)
        # The bar owns the strip below the time slider: wide, unmissable, and
        # not competing with the timeline row's controls for space.
        layout.addWidget(self.progress)
        self.setCentralWidget(central)

        self._build_actions()
        self._connect()
        self.statusBar().showMessage(self.controller.status())

    # -- the ways in -------------------------------------------------------- #

    def load_video(self, path: str) -> None:
        """Hand ``path`` to the controller; the dialog-free entry point."""
        self.controller.open_video(path)

    def open_video_dialog(self) -> None:
        """Ask the animator for a clip and load it."""
        chosen, _ = QFileDialog.getOpenFileName(self, "Open reference video", "", _VIDEO_FILTER)
        if chosen:
            self.load_video(chosen)

    def _build_actions(self) -> None:
        self.action_open = self._action("&Open Video…", "Ctrl+O", self.open_video_dialog)
        self.action_play_pause = self._action(
            "Play / pause", "Space", self.controller.toggle_playback
        )
        self.action_step_back = self._action("Previous frame", "Left", self._step_back)
        self.action_step_forward = self._action("Next frame", "Right", self._step_forward)
        self.action_mark = self._action("Mark Golden Pose", "K", self.controller.mark_current)
        self.action_remove_key = self._action(
            "Remove Golden Pose", "Delete", self.controller.remove_current
        )
        self.action_previous_key = self._action(
            "Jump to previous key", "Shift+Left", self._previous_key
        )
        self.action_next_key = self._action("Jump to next key", "Shift+Right", self._next_key)
        self.action_fill_inbetweens = self._action(
            "Fill Gaps (Generate Inbetweens)", "G", self.controller.fill_inbetweens
        )
        self.action_export = self._action(
            "Export &FBX…", "Ctrl+E", self.export_fbx
        )

        self._shortcuts = (
            self.action_play_pause,
            self.action_step_back,
            self.action_step_forward,
            self.action_mark,
            self.action_remove_key,
            self.action_previous_key,
            self.action_next_key,
            self.action_fill_inbetweens,
            self.action_export,
        )
        for action in self._shortcuts:
            self.addAction(action)

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_export)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        inbetweens_menu = self.menuBar().addMenu("&Inbetweens")
        inbetweens_menu.addAction(self.action_fill_inbetweens)

    def _action(self, text: str, shortcut: str, slot) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _step_back(self) -> None:
        self.controller.step(-1)

    def _step_forward(self) -> None:
        self.controller.step(1)

    def _previous_key(self) -> None:
        self.controller.jump_to_key(-1)

    def _next_key(self) -> None:
        self.controller.jump_to_key(1)

    def export_fbx(self) -> None:
        """Write the approved timeline to an FBX file (FR-GEN-04,S2 refusals).

        The same conventions as the blocking export: binary FBX, keys only at
        the marked frames, and the ``frame_start``/``frame_end`` range the
        import established. Every refusal is a status-bar message — the session
        never dies because an export could not happen (NFR-03).
        """
        if not self.controller.state.keyframes:
            self.statusBar().showMessage(
                "Nothing to export: there is no Golden Pose yet (press K)."
            )
            return
        if self.exporter is None:
            self.statusBar().showMessage(
                "Cannot export: no FBX writer is configured in this build."
            )
            return
        video = self.controller.video_path
        default_name = f"{video.stem}.fbx" if video is not None else "export.fbx"
        path_text, _chosen_filter = QFileDialog.getSaveFileName(
            self,
            "Export FBX",
            default_name,
            _FBX_FILTER,
        )
        if not path_text:
            self.statusBar().showMessage("Export cancelled.")
            return
        path = Path(path_text)
        try:
            self.exporter.save(self.controller.state, path)
        except Exception as exc:  # a bad disk/filename must not kill the session
            self.statusBar().showMessage(f"Export failed: {exc}")
            return
        keys = len(self.controller.state.keyframes)
        self.statusBar().showMessage(f"Exported {keys} Golden Pose(s) to {path}.")

    # -- following the controller ------------------------------------------ #

    def _build_distance_control(self) -> None:
        """Build the subject-distance control (M8 S8).

        It writes ``controller.subject_distance_m``, which the controller
        reads once per clip when its first captured frame fixes the depth
        scale; once that happens the control disables itself (a mid-clip
        change would be a silent no-op) until the next clip load re-arms it.
        """
        self._distance_label = QLabel("Subject distance", self)
        self.subject_distance = QDoubleSpinBox(self)
        self.subject_distance.setSuffix(" m")
        self.subject_distance.setDecimals(1)
        self.subject_distance.setSingleStep(0.1)
        self.subject_distance.setRange(0.5, 50.0)
        self.subject_distance.setValue(self.controller.subject_distance_m)
        self.subject_distance.setToolTip(
            "Camera-to-subject distance at the first captured frame. It "
            "calibrates the clip's relative depth once, at the first Golden "
            "Pose, and stays fixed until a new clip is loaded."
        )
        self.subject_distance.valueChanged.connect(self._on_distance_changed)

    def _on_distance_changed(self, value: float) -> None:
        """Forward the animator's distance to the controller."""
        self.controller.subject_distance_m = value

    def _build_progress_bar(self) -> None:
        """Build the capture progress bar (GUI progress feature).

        One bar for everything off-thread: determinate while the gather
        collects guides between Golden Poses, indeterminate while the engine
        generates (or a solo extraction cold-starts), and hidden whenever
        nothing is in flight. It owns the strip directly below the time
        slider, where the eye already follows the playhead.
        """
        self.progress = QProgressBar(self)
        self.progress.setTextVisible(False)
        self.progress.hide()

    def _on_guide_progress(self, done: int, total: int) -> None:
        """Show the gather's determinate range, or the engine's full-tilt move."""
        self.progress.show()
        if total > 0 and done < total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            # ``done == total``: the gathering ended and the engine is filling;
            # ``total == 0``: a keys-only fill from the start. Both swim.
            self.progress.setRange(0, 0)

    def _refresh_progress(self, *_ignored: object) -> None:
        """Re-derive the bar from the controller's own state.

        Runs on every status change (adoption, failure, a report), on the
        timeline refresh a new clip causes, and on both runners' busy
        announcements: the controller is asked, not guessed at, so any path
        that ends the work ends the bar with it. Nothing here disables user
        input — a fill survives scrubbing by design (the gather re-seeks its
        guides); only the controller refuses the mutations that would strand
        it (``K``/``Delete`` mid-fill).
        """
        if self.controller.fill_active:
            self.progress.show()
            return
        if self.controller.extraction_busy:
            # A lone Golden-Pose extraction in flight: no gather to count, so
            # the bar swims until the runner frees up.
            self.progress.show()
            self.progress.setRange(0, 0)
            return
        self.progress.hide()

    def _on_runner_busy_changed(self, *_ignored: object) -> None:
        """Fold a batch-1 runner's busy announcements into the bar."""
        self._refresh_progress()

    def _connect(self) -> None:
        self.timeline.frame_requested.connect(self.controller.go_to_frame)
        self.controller.frame_changed.connect(self.timeline.set_frame)
        self.controller.frame_changed.connect(self._refresh_overlay)
        self.controller.pose_changed.connect(self._on_pose_changed)
        self.controller.timeline_changed.connect(self._refresh_timeline)
        self.controller.media_changed.connect(self._on_media_changed)
        self.controller.status_changed.connect(self.statusBar().showMessage)
        self.controller.status_changed.connect(self._refresh_progress)
        self.controller.guide_progress.connect(self._on_guide_progress)
        if self.extractor is not None:
            self.extractor.busy_changed.connect(self._on_runner_busy_changed)
        if self.filler is not None:
            self.filler.busy_changed.connect(self._on_runner_busy_changed)
        # Show the starting pose right away: a pane that only fills in after the
        # first event would look broken on an empty session.
        self._on_pose_changed(self.controller.current_pose())

    def _on_pose_changed(self, pose: Mapping[str, JointPose]) -> None:
        # The controller already resolves an unkeyed frame to the neutral pose
        # (plan §3.B, "Display on Empty Frames"), so the pane just draws it.
        self.viewport.set_pose(self.controller.state.skeleton, pose)

    def _refresh_overlay(self, frame: int) -> None:
        """The overlay figure for the playhead: the last capture at or before it.

        The controller already froze each capture's own projection (S1); the
        window only replays the one the playhead holds (S4). A pane without
        the real player (a headless source) has no overlay to refresh.
        """
        if self._video_overlay is None:
            return
        self._video_overlay.set_snapshot(self.controller.overlay_snapshot_at(frame))

    def _refresh_timeline(self) -> None:
        state = self.controller.state
        self.timeline.set_timeline(
            frame_start=state.frame_start,
            frame_end=state.frame_end,
            fps=state.fps,
        )
        self.timeline.set_keys(state.frames())
        # The depth calibration locks at the first capture and resets on a new
        # clip: both moments arrive through this slot, so it is the one place
        # the distance control's enabled state needs refreshing (M8 S8).
        self.subject_distance.setEnabled(not self.controller.depth_calibrated)
        self._refresh_progress()

    def _on_media_changed(self) -> None:
        self._refresh_timeline()
        # A fresh clip has no captures yet: the overlay must not carry the
        # previous clip's figure over.
        self._refresh_overlay(self.controller.frame)
        clip = self.controller.video_path
        self.setWindowTitle("AImation Actor" if clip is None else f"AImation Actor — {clip.name}")

    # -- teardown ----------------------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's naming, not ours
        """Stop a running extraction before the window goes away.

        A ``QThread`` destroyed while its work is still running aborts the
        process, so the worker is asked to stop and waited on here. The wait is
        the one place a blocking moment is the honest choice: the alternative is
        a crash on close.
        """
        if self.extractor is not None:
            self.extractor.shutdown()
        if self.filler is not None:
            self.filler.shutdown()
        super().closeEvent(event)

