"""The capture controller: the timeline, the playhead and the shortcuts' behavior.

This is the GUI's brain, and it holds no domain math: key management and the
neutral pose come from ``core.services`` (NFR-01), so the widget layer only
renders what the controller reports.

It drives the video through a small seam — the ``VideoSource`` protocol below —
so the capture behavior is testable without a media backend, and it never reads
or decodes media itself: the player streams and reports (FR-CAP-02).

Marking a golden pose is an **asynchronous** request (M5): the engine runs off the
UI thread, so the key appears a moment after ``K`` is pressed, on the frame it was
extracted from — not on wherever the playhead has moved to.

State rules (see ``odd/tasks/m4-capture-gui.md``, ``odd/tasks/m5-pose-extraction.md``):

- a timeline holds at most one key per frame, and marking overwrites (FR-CAP-07);
- the playhead lives here, not in ``TimelineState``: the core API takes the frame
  as a parameter;
- the frame rate follows the clip when the player reports one, and keeps the
  timeline's default (24) otherwise (FR-CAP-03);
- the position the player reports only moves the playhead during playback, so the
  echo of our own seek cannot bounce it;
- a frame whose pose was never extracted gains **no** key: a failed extraction
  keeps the prior keys and reports (FR-CAP-07), and a result that belongs to a
  clip which is no longer open is discarded rather than written onto the new one.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointPose,
    Skeleton,
    TimelineState,
    WorldPose,
)
from aimation_actor.core.services import (
    build_production_pose,
    clamp_frame,
    find_key,
    key_frames,
    mark_pose,
    neutral_pose,
    next_key_frame,
    previous_key_frame,
    remove_pose,
)

__all__ = ["CaptureController", "PoseExtractor", "VideoSource"]

_NO_CLIP = "Open a reference video before marking golden poses."
_NO_ENGINE = "No pose engine is configured, so no pose can be extracted."
_NO_FRAME = "Could not read the frame at the playhead."
_BUSY = "Still extracting the previous frame; try again when it finishes."
_STALE = "Discarded a pose extracted for the clip that is no longer open."


class VideoSource(Protocol):
    """What the controller needs from a video player.

    The player owns streaming and decoding (FR-CAP-02); the controller owns the
    timeline. A source must expose these methods and the signals the controller
    connects to: ``media_loaded(float, int)`` (fps, duration in ms; a frame rate
    of ``0`` means the backend does not report one), ``position_changed(int)``
    (ms), ``frame_shown(int)`` (the index of a delivered frame, when the source
    can prove it from the frame's own timestamps and the clip's frame rate),
    ``playback_changed(bool)`` and ``failed(str)``.

    ``frame_shown`` exists because the timeline cannot trust position alone: the
    backend reports changes far less often than it delivers frames, so a playhead
    driven by position lags the pane. A source that can index its frames emits
    this and the controller follows the frames instead.
    """

    def open(self, path: str) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def seek_frame(self, frame: int, fps: float) -> None: ...

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        """The frame on screen with the frame it belongs to, or ``None``.

        A source returns the frame only when it really belongs to the position it
        was asked for: a seek is asynchronous, and handing over the previous
        position's frame would extract the pose of a frame the animator is not
        looking at. ``None`` is therefore expected right after a scrub — the
        animator retries once the video shows the new frame — and not only when
        no clip is loaded.

        The returned ``frame_index`` is what makes the key trustworthy: the
        timeline follows the backend's position events, which are far rarer than
        frames, so after a playback the playhead can lag the pane. ``None`` means
        the source cannot establish the index (no timestamps, unknown frame rate)
        and the caller resolves it from its own playhead.
        """
        ...


class PoseExtractor(Protocol):
    """What the controller needs from an off-thread pose extractor.

    The extractor owns the isolation (NFR-02): ``start`` returns as soon as the
    work is handed off, and the result arrives later through ``extracted`` or
    ``failed``. A request that cannot be served — one already in flight — is
    refused by ``start`` returning ``False``, so the controller never has to
    guess whether the engine is busy.
    """

    def start(self, frame_index: int, image: FrameImage) -> bool: ...


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
        *,
        extractor: PoseExtractor | None = None,
        skeleton_source: Callable[[], Skeleton | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._state = state
        self._skeleton_source = skeleton_source
        self._frame = clamp_frame(self._state, self._state.frame_start)
        self._video_path: Path | None = None
        self._pending_path: Path | None = None
        self._playing = False
        # Whether the source has proven it can index the frames it delivers. It
        # is per clip, because it depends on the clip's own metadata.
        self._frames_are_indexed = False
        self._extractor = extractor
        # Any in-flight extraction belongs to the clip it was started against, so
        # "which clip" is tracked as a generation that a load bumps.
        self._generation = 0
        self._extraction_generation: int | None = None

        source.media_loaded.connect(self._on_media_loaded)
        source.position_changed.connect(self._on_position_changed)
        source.frame_shown.connect(self._on_frame_shown)
        source.playback_changed.connect(self._on_playback_changed)
        source.failed.connect(self._on_source_failed)

        if extractor is not None:
            extractor.extracted.connect(self._on_pose_extracted)
            extractor.failed.connect(self._on_pose_failed)

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
        # A new clip invalidates any extraction still running against the old one.
        self._generation += 1
        self._extraction_generation = None
        # Indexing depends on this clip's own metadata, so it is re-proved here.
        self._frames_are_indexed = False
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
        self._report(message)

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
        """Follow playback: the playhead tracks the player while it plays.

        Once the source has proven it can index its frames, the frames own the
        playhead and this is ignored: position events arrive far less often than
        frames, so following them would walk the timeline back behind the frame
        on screen — the animator would mark a pose and see a neighbouring frame
        number. Position stays the fallback for a clip that cannot be indexed.
        """
        if not self._playing:
            return  # the echo of an explicit seek must not move the playhead
        if self._frames_are_indexed:
            return
        target = clamp_frame(self._state, int(math.floor(position_ms / 1000.0 * self._state.fps)))
        if target == self._frame:
            return
        self._frame = target
        self._emit_frame()

    def _on_frame_shown(self, frame_index: int) -> None:
        """Follow the frame that was just delivered to the pane (S13).

        This is the only source of truth the timeline can trust while playing:
        the frame knows which frame it is, and the backend's position events do
        not. A frame delivered while paused (a seek, or the priming nudge) must
        not move the playhead — the animator's own navigation owns it then.
        """
        self._frames_are_indexed = True
        if not self._playing:
            return
        target = clamp_frame(self._state, frame_index)
        if target == self._frame:
            return
        self._frame = target
        self._emit_frame()

    # -- keys (FR-CAP-07, plan §3.A) --------------------------------------- #

    def mark_current(self) -> None:
        """Extract the pose at the playhead and write it as a golden pose.

        The request is **asynchronous** (FR-CAP-05, NFR-02): the engine runs off
        the UI thread, so this returns before the pose exists and the key appears
        when the result arrives. Nothing is written when the request cannot be
        served — a frame whose pose was never extracted must not gain a key
        (FR-CAP-07).
        """
        if not self.has_media:
            self._report(_NO_CLIP)
            return
        if self._extractor is None:
            self._report(_NO_ENGINE)
            return

        captured = self._source.grab_frame(self._state.fps)
        if captured is None:
            self._report(_NO_FRAME)
            return

        # The key belongs to the frame the animator is looking at, not to where
        # the playhead happens to be: while the player plays, position events
        # arrive far less often than frames, so the timeline lags the pane by a
        # frame or three. The source proves the index from the frame's own
        # timestamps; when it cannot, the playhead is the best answer there is.
        target = self._frame
        if captured.frame_index is not None:
            target = clamp_frame(self._state, captured.frame_index)
            if target != self._frame:
                self._frame = target
                self._emit_frame()

        # Claim the extraction *before* handing it over: an extractor is free to
        # answer synchronously, and its result must not look stale when it does.
        # A refusal keeps whichever claim was already in force — stomping it would
        # discard the result that is still in flight.
        previous_claim = self._extraction_generation
        self._extraction_generation = self._generation
        if not self._extractor.start(target, captured.image):
            self._extraction_generation = previous_claim
            self._report(_BUSY)
            return

        self._emit_status(actionable=f"Extracting the pose at frame {target}…")

    def _on_pose_extracted(self, frame_index: int, pose: WorldPose) -> None:
        """Write the extracted pose onto the frame it was extracted from (S5).

        The playhead may have moved on since the request: the result is attributed
        to its own frame, never to wherever the animator is now looking.
        """
        if self._is_stale():
            self._report(_STALE)
            return
        self._extraction_generation = None
        if not self._ensure_rig(frame_index):
            return
        built = build_production_pose(pose, self._state.skeleton)
        self._state = mark_pose(self._state, frame_index, built)
        self.timeline_changed.emit()
        if frame_index == self._frame:
            self.pose_changed.emit(self.current_pose())
        self._emit_status(actionable=f"Extracted the pose at frame {frame_index}.")

    def _ensure_rig(self, frame_index: int) -> bool:
        """Adopt the engine's template rig before the first extraction lands (T13).

        The production skeleton's bind offsets are real body-model data no caller
        may invent — the engine reports them with its ready line, so the rig is
        built the first time it is available and stays for the session (loading
        another clip keeps it; ``TimelineState.replace`` never drops the
        skeleton). A rig that is still unavailable is a typed, non-fatal
        failure: nothing is marked on a skeleton the tool does not know.
        """
        if self._state.skeleton.joints:
            return True
        adopted: Skeleton | None = None
        problem: Exception | None = None
        if self._skeleton_source is not None:
            try:
                adopted = self._skeleton_source()
            except Exception as error:  # noqa: BLE001 - the report needs the reason
                problem = error
        if adopted is None:
            reason = (
                f"the engine's template is unusable: {type(problem).__name__}: {problem}"
                if problem is not None
                else "the engine reports no bind offsets yet"
            )
            self._report(
                f"Pose extracted at frame {frame_index}, but no production rig "
                f"is available ({reason}); nothing was marked."
            )
            return False
        self._state = replace(self._state, skeleton=adopted)
        return True

    def _on_pose_failed(self, frame_index: int, message: str) -> None:
        """Report a failed extraction; the session and prior keys survive (FR-CAP-07)."""
        if self._is_stale():
            self._report(_STALE)
            return
        self._extraction_generation = None
        self._report(f"Pose extraction failed at frame {frame_index}: {message}")

    def _is_stale(self) -> bool:
        """Whether the finishing extraction belongs to a clip no longer open."""
        return self._extraction_generation != self._generation

    def _report(self, message: str) -> None:
        """Surface a failure the way the window shows it (NFR-03)."""
        self.failed.emit(message)
        self._emit_status(actionable=message)

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
