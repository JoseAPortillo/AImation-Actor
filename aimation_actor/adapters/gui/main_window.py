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

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from aimation_actor.adapters.ai.pose_runner import PoseExtractionRunner
from aimation_actor.adapters.gui.capture_controller import CaptureController, VideoSource
from aimation_actor.adapters.gui.timeline_bar import TimelineBar
from aimation_actor.adapters.gui.video_player import VideoPlayer
from aimation_actor.adapters.gui.viewport_3d import SkeletonViewport
from aimation_actor.core.models import JointPose, Skeleton, TimelineState
from aimation_actor.ports.ai_port import AIPort

__all__ = ["MainWindow"]

_VIDEO_FILTER = "Reference video (*.mp4 *.mov)"
_DEFAULT_FPS = 24.0


class MainWindow(QMainWindow):
    """The animator's capture surface: video, 3D preview, timeline, shortcuts."""

    def __init__(
        self,
        *,
        source: VideoSource | None = None,
        skeleton: Skeleton | None = None,
        engine: AIPort | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the window.

        ``source``, ``skeleton`` and ``engine`` exist so a caller can supply the
        player, the rig and the pose engine; the defaults are the real player, an
        **empty rig**, and **no engine**, because until M5 supplies the production
        skeleton and the HMR2.0 adapter there are none to load, and the window will
        not invent them. Without an engine, ``K`` reports that it cannot extract
        rather than writing a pose nobody computed.
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

        self.extractor = None if engine is None else PoseExtractionRunner(engine, self)
        self.controller = CaptureController(player, state, self, extractor=self.extractor)
        self.viewport = SkeletonViewport(self)
        self.timeline = TimelineBar(self)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self._video_pane)
        self.splitter.addWidget(self.viewport)
        self.splitter.setSizes([640, 640])

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.timeline)
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

        self._shortcuts = (
            self.action_play_pause,
            self.action_step_back,
            self.action_step_forward,
            self.action_mark,
            self.action_remove_key,
            self.action_previous_key,
            self.action_next_key,
        )
        for action in self._shortcuts:
            self.addAction(action)

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.action_open)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

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

    # -- following the controller ------------------------------------------ #

    def _connect(self) -> None:
        self.timeline.frame_requested.connect(self.controller.go_to_frame)
        self.controller.frame_changed.connect(self.timeline.set_frame)
        self.controller.pose_changed.connect(self._on_pose_changed)
        self.controller.timeline_changed.connect(self._refresh_timeline)
        self.controller.media_changed.connect(self._on_media_changed)
        self.controller.status_changed.connect(self.statusBar().showMessage)
        # Show the starting pose right away: a pane that only fills in after the
        # first event would look broken on an empty session.
        self._on_pose_changed(self.controller.current_pose())

    def _on_pose_changed(self, pose: Mapping[str, JointPose]) -> None:
        # The controller already resolves an unkeyed frame to the neutral pose
        # (plan §3.B, "Display on Empty Frames"), so the pane just draws it.
        self.viewport.set_pose(self.controller.state.skeleton, pose)

    def _refresh_timeline(self) -> None:
        state = self.controller.state
        self.timeline.set_timeline(
            frame_start=state.frame_start,
            frame_end=state.frame_end,
            fps=state.fps,
        )
        self.timeline.set_keys(state.frames())

    def _on_media_changed(self) -> None:
        self._refresh_timeline()
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
        super().closeEvent(event)

