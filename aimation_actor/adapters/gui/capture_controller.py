"""The capture controller: the timeline, the playhead and the shortcuts' behavior.

This is the GUI's brain, and it holds no domain math: key management and the
neutral pose come from ``core.services`` (NFR-01), so the widget layer only
renders what the controller reports.

It drives the video through a small seam — the ``VideoSource`` protocol below —
so the capture behavior is testable without a media backend, and it never reads
or decodes media itself: the player streams and reports (FR-CAP-02).

State rules (see ``odd/tasks/m4-capture-gui.md``):

- a timeline holds at most one key per frame, and marking overwrites (FR-CAP-07);
- the playhead lives here, not in ``TimelineState``: the core API takes the frame
  as a parameter;
- the frame rate follows the clip when the player reports one, and keeps the
  timeline's default (24) otherwise (FR-CAP-03);
- the position the player reports only moves the playhead during playback, so the
  echo of our own seek cannot bounce it.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from aimation_actor.core.models import JointPose, TimelineState
from aimation_actor.core.services import (
    clamp_frame,
    find_key,
    key_frames,
    mark_pose,
    neutral_pose,
    next_key_frame,
    previous_key_frame,
    remove_pose,
)

__all__ = ["CaptureController", "VideoSource"]

_NO_CLIP = "Open a reference video before marking golden poses."


class VideoSource(Protocol):
    """What the controller needs from a video player.

    The player owns streaming and decoding (FR-CAP-02); the controller owns the
    timeline. A source must expose these methods and the signals the controller
    connects to: ``media_loaded(float, int)`` (fps, duration in ms; a frame rate
    of ``0`` means the backend does not report one), ``position_changed(int)``
    (ms), ``playback_changed(bool)`` and ``failed(str)``.
    """

    def open(self, path: str) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None: ...


class CaptureController(QObject):
    """Owns the timeline, the playhead and the capture shortcuts' behavior.

    The timeline — and with it the rig the poses are expressed on — belongs to the
    caller: the controller never invents one, so a session cannot end up marking
    poses on a rig nobody loaded.
    """

    media_changed = Signal()
    frame_changed = Signal(int)
    timeline_changed = Signal()
    pose_changed = Signal(object)
    playback_changed = Signal(bool)
    status_changed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        source: VideoSource,
        state: TimelineState,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._state = state
        self._frame = clamp_frame(self._state, self._state.frame_start)
        self._video_path: Path | None = None
        self._pending_path: Path | None = None
        self._playing = False

        source.media_loaded.connect(self._on_media_loaded)
        source.position_changed.connect(self._on_position_changed)
        source.playback_changed.connect(self._on_playback_changed)
        source.failed.connect(self._on_source_failed)

    # -- reported state ---------------------------------------------------- #

    @property
    def state(self) -> TimelineState:
        """The current timeline; frozen, so every change replaces it."""
        return self._state

    @property
    def frame(self) -> int:
        """The current playhead frame."""
        return self._frame

    @property
    def video_path(self) -> Path | None:
        """The clip currently loaded, or ``None``."""
        return self._video_path

    @property
    def has_media(self) -> bool:
        """Whether a clip is loaded and its timeline is usable."""
        return self._video_path is not None

    @property
    def is_playing(self) -> bool:
        """Whether the player is currently playing."""
        return self._playing

    @property
    def total_frames(self) -> int:
        """How many frames the range spans, at least one."""
        return max(1, self._state.frame_end - self._state.frame_start + 1)

    def has_key(self, frame: int | None = None) -> bool:
        """Whether ``frame`` (default: the playhead) carries a golden pose."""
        target = self._frame if frame is None else frame
        return find_key(self._state, target) is not None

    def key_count(self) -> int:
        """How many golden poses the timeline holds."""
        return len(key_frames(self._state))

    def current_pose(self) -> dict[str, JointPose]:
        """The pose for the playhead: its key, or the neutral pose (plan §3.B)."""
        keyframe = find_key(self._state, self._frame)
        if keyframe is None:
            return neutral_pose(self._state.skeleton)
        return dict(keyframe.pose)

    def status(self) -> str:
        """A one-line, actionable description of the capture state (NFR-03)."""
        if self._video_path is None:
            return "No video loaded."
        keyed = "keyed" if self.has_key() else "no key"
        poses = "golden pose" if self.key_count() == 1 else "golden poses"
        return (
            f"{self._video_path.name} — frame {self._frame} / {self.total_frames}"
            f" · {self._state.fps:g} fps · {self.key_count()} {poses} · {keyed}"
        )

    # -- media (FR-CAP-01, FR-CAP-03) -------------------------------------- #

    def open_video(self, path: str) -> None:
        """Ask the player to load ``path``; the timeline follows its answer.

        The path only becomes the loaded clip once the player confirms it, so a
        failed open leaves whatever was loaded before intact (FR-CAP-01).
        """
        self._pending_path = Path(path)
        self.status_changed.emit(f"Loading {self._pending_path.name}…")
        self._source.open(path)

    def _on_media_loaded(self, reported_fps: float, duration_ms: int) -> None:
        """Adopt the clip's frame rate and range, and start a fresh timeline."""
        self._video_path = self._pending_path
        self._pending_path = None
        fps = reported_fps if reported_fps > 0.0 else self._state.fps
        total = max(1, int(math.floor(duration_ms / 1000.0 * fps)))
        # Keys belong to the clip that was loaded when they were marked, so a new
        # clip starts an empty timeline; the rig itself is not clip data.
        self._state = replace(
            self._state,
            keyframes=(),
            fps=fps,
            frame_start=0,
            frame_end=total - 1,
        )
        self._frame = 0
        self.media_changed.emit()
        self.timeline_changed.emit()
        self.frame_changed.emit(self._frame)
        self.pose_changed.emit(self.current_pose())
        self._emit_status()

    def _on_source_failed(self, message: str) -> None:
        """Report a player failure; the loaded clip and its keys stay usable."""
        self._pending_path = None
        self.failed.emit(message)
        self._emit_status(actionable=message)

    # -- playhead (FR-CAP-04, plan §3.A) ----------------------------------- #

    def go_to_frame(self, frame: int) -> None:
        """Clamp ``frame``, seek the player and report the new playhead."""
        target = clamp_frame(self._state, frame)
        self._frame = target
        self._source.seek_frame(target, self._state.fps)
        self._emit_frame()

    def step(self, delta: int) -> None:
        """Advance or rewind exactly ``delta`` frames, clamped to the range."""
        self.go_to_frame(self._frame + delta)

    def jump_to_key(self, direction: int) -> None:
        """Jump to the neighbouring golden pose; stays put when there is none."""
        if direction == 0:
            return
        if direction > 0:
            target = next_key_frame(self._state, self._frame)
        else:
            target = previous_key_frame(self._state, self._frame)
        if target is None:
            return
        self.go_to_frame(target)

    def toggle_playback(self) -> None:
        """Play or pause, following the player's reported state."""
        if self._playing:
            self._source.pause()
        else:
            self._source.play()

    def _on_playback_changed(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        self.playback_changed.emit(playing)
        self._emit_status()

    def _on_position_changed(self, position_ms: int) -> None:
        """Follow playback: the playhead tracks the player while it plays."""
        if not self._playing:
            return  # the echo of an explicit seek must not move the playhead
        target = clamp_frame(self._state, int(math.floor(position_ms / 1000.0 * self._state.fps)))
        if target == self._frame:
            return
        self._frame = target
        self._emit_frame()

    # -- keys (FR-CAP-07, plan §3.A) --------------------------------------- #

    def mark_current(self) -> None:
        """Mark the playhead with a golden pose, replacing any key there.

        Until GVHMR extracts a real pose (M5), the key carries the neutral pose,
        which M5 then overwrites on the same frame.
        """
        if not self.has_media:
            self.failed.emit(_NO_CLIP)
            self._emit_status(actionable=_NO_CLIP)
            return
        self._state = mark_pose(self._state, self._frame, neutral_pose(self._state.skeleton))
        self.timeline_changed.emit()
        self.pose_changed.emit(self.current_pose())
        self._emit_status()

    def remove_current(self) -> None:
        """Drop the golden pose at the playhead; an empty frame is a no-op."""
        updated = remove_pose(self._state, self._frame)
        if updated is self._state:
            return
        self._state = updated
        self.timeline_changed.emit()
        self.pose_changed.emit(self.current_pose())
        self._emit_status()

    # -- reporting --------------------------------------------------------- #

    def _emit_frame(self) -> None:
        self.frame_changed.emit(self._frame)
        self.pose_changed.emit(self.current_pose())
        self._emit_status()

    def _emit_status(self, actionable: str | None = None) -> None:
        status = self.status()
        if actionable is not None:
            status = f"{actionable} — {status}"
        self.status_changed.emit(status)
