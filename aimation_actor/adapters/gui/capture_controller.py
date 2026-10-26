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

from PySide6.QtCore import QObject, QTimer, Signal

from aimation_actor.core.foot_contacts import FOOT_JOINTS
from aimation_actor.core.foot_ik import pin_foot_contacts
from aimation_actor.core.models import (
    CapturedFrame,
    FrameImage,
    JointPose,
    Skeleton,
    TimelineState,
    Vector3,
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
    smooth_root_trajectory,
)

__all__ = ["CaptureController", "Inbetweener", "PoseExtractor", "VideoSource"]

_NO_CLIP = "Open a reference video before marking golden poses."
_NO_ENGINE = "No pose engine is configured, so no pose can be extracted."
_NO_FRAME = "Could not read the frame at the playhead."
_BUSY = "Still extracting the previous frame; try again when it finishes."
_STALE = "Discarded a pose extracted for the clip that is no longer open."
_NO_INBETWEENER = "No inbetweening engine is configured, so gaps cannot be filled."
_NO_KEYS = "Mark at least two golden poses before filling the gaps."
_INBETWEEN_BUSY = "Inbetweens are already being generated; try again when it finishes."
_INBETWEENS_STALE = "Discarded generated inbetweens for the clip that is no longer open."

# S6's guide track: one capture guide every ~12 engine samples. The 20 fps
# motion clock is the inbetween engine's (HumanML3D); at 24 fps a guide every
# ~14.4 timeline frames, rounded to 14.
#
# T9: a narrow gap is not spaced - every interior frame is captured, because
# a gap whose guides cover the whole interior is filled straight from the
# capture and never reaches the engine at all.
_GUIDE_SPACING_SAMPLES = 12
_MOTION_FPS = 20.0
_DENSE_CAPTURE_MAX_FRAMES = 24  # interior frames of a gap captured one by one
_GUIDE_CAP = 8  # per gap (S6), already small against the ~70 s fill
_GUIDE_GRAB_TRIES = 30  # post-seek grabs (~1.5 s) before giving up on a frame
_GUIDE_GRAB_INTERVAL_MS = 50


def guide_frames_between(keys: tuple[int, ...], fps: float) -> list[int]:
    """The timeline frames whose capture conditions the fill (S6, T9).

    A gap spanning at most ``_DENSE_CAPTURE_MAX_FRAMES + 1`` timeline frames
    (24 interior frames) is dense: every frame strictly inside it becomes a
    capture candidate, the spacing and the cap bypassed - that gap's fill is
    the capture itself. Wider gaps keep the spaced plan: one frame every
    ``_GUIDE_SPACING_SAMPLES`` motion-clock samples, at most ``_GUIDE_CAP``
    guides per gap after even thinning. The keys win by construction: no
    candidate can land on one.
    """
    spacing = max(1, round(_GUIDE_SPACING_SAMPLES * fps / _MOTION_FPS))
    out: list[int] = []
    for left, right in zip(keys, keys[1:], strict=False):
        interior = range(left + 1, right)
        if len(interior) <= _DENSE_CAPTURE_MAX_FRAMES:
            out.extend(interior)
            continue
        candidates = range(left + spacing, right, spacing)
        if len(candidates) > _GUIDE_CAP:
            stride = -(-len(candidates) // _GUIDE_CAP)  # ceil: at most _GUIDE_CAP
            candidates = candidates[::stride]
        out.extend(candidates)
    return out


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


class Inbetweener(Protocol):
    """What the controller needs from an off-thread inbetweening engine.

    The same isolation contract as ``PoseExtractor``, one timeline at a time:
    ``start`` hands the whole timeline over and returns immediately; the filled
    timeline arrives later through ``filled`` and a failure through ``failed``
    (M6 T4). A request that cannot be served is refused by ``start`` returning
    ``False``.

    ``guides`` carries the capture poses between the keys (S6), mapped by
    timeline frame; ``None`` stands for keys-only conditioning — the engine
    must treat both the same way, the guides never replacing the keys.
    """

    def start(
        self, timeline: TimelineState, guides: dict[int, dict[str, JointPose]] | None = None
    ) -> bool: ...


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
    # Progress mapping for a gap fill (GUI progress feature): ``done`` guides
    # gathered out of ``total`` planned. ``done == total`` (or ``total == 0``,
    # a keys-only fill) means the gathering is over and the engine is working.
    guide_progress = Signal(int, int)

    def __init__(
        self,
        source: VideoSource,
        state: TimelineState,
        parent: QObject | None = None,
        *,
        extractor: PoseExtractor | None = None,
        skeleton_source: Callable[[], Skeleton | None] | None = None,
        inbetweener: Inbetweener | None = None,
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
        self._inbetweener = inbetweener
        self._inbetween_generation: int | None = None
        self._root_origin: Vector3 | None = None
        # M8 S8: the animator's real distance to the subject at the first
        # captured key, in metres; it calibrates the depth channel once per
        # clip (the camera-space estimate carries a ~30x focal assumption).
        self.subject_distance_m = 3.0
        self._depth_scale = 1.0
        # M7: the pre-fill human keys the pin pass must detect contacts from.
        # After a fill the generated rows are indistinguishable from keys, so
        # the frame list is captured at request time and consumed at adoption.
        self._fill_original_keys: tuple[int, ...] = ()
        # Any in-flight extraction belongs to the clip it was started against, so
        # "which clip" is tracked as a generation that a load bumps.
        self._generation = 0
        self._extraction_generation: int | None = None
        # S6 gathering: guides for the fill in flight, plus the state machine
        # that extracts them one frame at a time before the fill is handed off.
        self._guides: dict[int, dict[str, JointPose]] = {}
        self._guide_queue: list[int] = []
        self._guide_pending: int | None = None  # a guide extraction in flight
        self._guide_attempts = 0
        self._guide_busy_waits = 0  # start refusals of the gather, bounded
        self._guide_timer: QTimer | None = None
        self._fill_active = False
        # The plan length of the fill in flight: the total the progress signal
        # reports against. Zero outside a fill.
        self._guide_total = 0

        source.media_loaded.connect(self._on_media_loaded)
        source.position_changed.connect(self._on_position_changed)
        source.frame_shown.connect(self._on_frame_shown)
        source.playback_changed.connect(self._on_playback_changed)
        source.failed.connect(self._on_source_failed)

        if extractor is not None:
            extractor.extracted.connect(self._on_pose_extracted)
            extractor.failed.connect(self._on_pose_failed)
            # T9: a batch-1 runner is still finishing its own thread when the
            # gathered sequence requests the next guide right away (dense gaps
            # make this the rule, not the exception). A runner that announces
            # its freedom lets the gather resume instead of degrading.
            freed = getattr(extractor, "busy_changed", None)
            if freed is not None:
                freed.connect(self._on_extractor_freed)
                self._extractor_has_free_signal = True
            else:
                self._extractor_has_free_signal = False
        else:
            self._extractor_has_free_signal = False

        if inbetweener is not None:
            inbetweener.filled.connect(self._on_inbetweens_filled)
            inbetweener.failed.connect(self._on_inbetweens_failed)

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
    def depth_calibrated(self) -> bool:
        """Whether this clip's depth calibration is already fixed (M8 S8).

        The scale is computed once, against ``subject_distance_m`` at the
        first captured frame (``_build_production_pose``), and then holds for
        the whole clip; loading a new clip resets it. A GUI setting for the
        distance disables itself once this turns true, because changing it
        mid-clip would silently do nothing.
        """
        return self._root_origin is not None

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

    @property
    def fill_active(self) -> bool:
        """Whether a gap fill is in flight: gathering guides or generating."""
        return self._fill_active

    @property
    def extraction_busy(self) -> bool:
        """Whether the capture engine still holds an extraction in flight.

        Read straight off the batch-1 runner; a source without the runner
        protocol (no ``busy``) reads idle rather than inventing state.
        """
        return bool(getattr(self._extractor, "busy", False))

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
        # A fill gathered for the replaced clip cannot survive it either: its
        # stranded results are refused by the generation checks anyway, so
        # retire the gather state here instead of letting it run on (and the
        # progress bar claim work the old fill will never finish).
        self._fill_active = False
        self._guide_queue = []
        self._guide_pending = None
        self._guide_total = 0
        # Indexing depends on this clip's own metadata, so it is re-proved here.
        self._frames_are_indexed = False
        self._root_origin = None
        self._depth_scale = 1.0
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

    def _navigation_lock(self) -> str | None:
        """Why playhead work is refused right now, or ``None`` when free.

        The guide gather re-seeks the decoder itself, frame by frame, and a
        solo extraction's answer belongs to the frame it started from: a
        scrub or a play sweep over the clip while either runs fights that
        work and can strand it — the same reason the window locks the
        scrubber widget. The guard lives here, at the playhead owner, so no
        entry point (the arrows, key jumps, a programmatic request) slips
        past the widget-level lock.
        """
        if self._fill_active:
            return "Cannot navigate: a gap fill is gathering its frames."
        if self.extraction_busy:
            return "Cannot navigate: a Golden Pose extraction is in flight."
        return None

    def go_to_frame(self, frame: int) -> None:
        """Clamp ``frame``, seek the player and report the new playhead."""
        locked = self._navigation_lock()
        if locked is not None:
            self._report(locked)
            return
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
        locked = self._navigation_lock()
        if locked is not None:
            self._report(locked)
            return
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

        A result claimed as a guide (S6) never becomes a key: it joins the
        gather buffer and the sequence continues.
        """
        if self._guide_pending is not None and self._fill_active:
            self._extraction_generation = None
            pending = self._guide_pending
            self._guide_pending = None
            self._guide_attempts = 0
            if self._inbetween_generation != self._generation:
                self._abandon_fill(_INBETWEENS_STALE)
                return
            if frame_index != pending:
                self._degrade_to_keys_only("the guide extraction answered another frame")
                return
            if not self._ensure_rig(pending):
                self._degrade_to_keys_only("no production rig for the guides")
                return
            built = self._build_production_pose(pose)
            self._guides[pending] = built
            if self._guide_queue and self._guide_queue[0] == pending:
                self._guide_queue.pop(0)
            self.guide_progress.emit(len(self._guides), self._guide_total)
            self._advance_guides()
            return

        if self._is_stale():
            self._report(_STALE)
            return
        self._extraction_generation = None
        if not self._ensure_rig(frame_index):
            return
        built = self._build_production_pose(pose)
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

    def _build_production_pose(self, pose: WorldPose) -> dict[str, JointPose]:
        """Apply the first captured root position as this clip's origin.

        M8 S8: the depth channel of camera-space translation carries HMR2's
        telephoto focal assumption (~30x), so relative depth is calibrated
        once per clip against the animator's known subject distance at the
        first key. Lateral and vertical channels self-calibrate through the
        projection (the focal cancels) and stay untouched; an origin without
        a credible depth keeps the historical 1:1 behavior (S4).
        """
        if self._root_origin is None:
            self._root_origin = pose.root_translation
            self._depth_scale = self._compute_depth_scale(pose.root_translation)
        origin = self._root_origin
        scale = self._depth_scale
        relative = Vector3(
            x=pose.root_translation.x - origin.x,
            y=(pose.root_translation.y - origin.y) * scale,
            z=pose.root_translation.z - origin.z,
        )
        return build_production_pose(
            replace(pose, root_translation=relative), self._state.skeleton
        )

    def _compute_depth_scale(self, origin: Vector3) -> float:
        """cm-per-cm factor mapping the estimated depth span onto metres.

        ``origin.y`` is ``+tz * 100`` in camera metres (domain depth grows
        away from the camera, along the canonical ``-Y`` facing's back); a
        first frame that did not report a physical distance (missing, zero,
        or below a half metre — inside which the weak-perspective fit is
        meaningless) gets no calibration rather than a fabricated one.
        """
        tz_first_m = origin.y / 100.0
        if not math.isfinite(tz_first_m) or tz_first_m < 0.5:
            return 1.0
        return self.subject_distance_m / tz_first_m

    def _on_pose_failed(self, frame_index: int, message: str) -> None:
        """Report a failed extraction; the session and prior keys survive (FR-CAP-07)."""
        if self._guide_pending is not None and self._fill_active:
            self._extraction_generation = None
            self._guide_pending = None
            self._guide_attempts = 0
            if self._inbetween_generation != self._generation:
                self._abandon_fill(_INBETWEENS_STALE)
                return
            self._degrade_to_keys_only(f"guide extraction failed: {message}")
            return
        if self._is_stale():
            self._report(_STALE)
            return
        self._extraction_generation = None
        self._report(f"Pose extraction failed at frame {frame_index}: {message}")

    def _abandon_fill(self, message: str) -> None:
        """Drop a fill still gathered for a clip that is no longer open (S6)."""
        self._fill_active = False
        self._inbetween_generation = None
        self._fill_original_keys = ()
        self._guide_queue = []
        self._guide_pending = None
        self._guide_attempts = 0
        self._report(message)

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

    # -- generated inbetweens (M6 T4, FR-GEN-01..03) ------------------------ #

    def fill_inbetweens(self) -> None:
        """Generate the missing frames between the timeline's golden poses.

        The request is **asynchronous** (the runner owns the isolation): the
        engine fills off the UI thread and the result is adopted only when it
        lands, if it still belongs to the open clip. A failure is non-fatal:
        the keys survive untouched (S1, FR-GEN-01) and so does the session.

        When a capture engine is available, the capture between the keys first
        becomes guides (S6): frame by frame, extracted through the same
        batch-1 machinery, then handed over attached to the request. Guides
        are never required — any extraction problem degrades to keys-only
        without a new failure class.
        """
        if self._inbetweener is None:
            self._report(_NO_INBETWEENER)
            return
        frames = key_frames(self._state)
        if len(frames) < 2:
            self._report(_NO_KEYS)
            return
        if self._fill_active:
            self._report(_INBETWEEN_BUSY)
            return
        # The pin pass detects planted contacts from the pre-fill keys (M7);
        # remember them now — post-fill they are no longer recoverable.
        self._fill_original_keys = tuple(frames)

        self._guides = {}
        self._guide_queue = (
            guide_frames_between(frames, self._state.fps)
            if self._extractor is not None
            else []
        )
        self._guide_attempts = 0
        self._guide_busy_waits = 0
        # Claim the fill up front: guide results arriving later must not look
        # stale for the clip that is still open; _hand_off keeps the claim
        # when it finally hands the request over.
        self._inbetween_generation = self._generation
        self._fill_active = True
        self._guide_total = len(self._guide_queue)
        # Progress contract: announce the plan before the first guide moves, so
        # the bar shows a determinate range even while the gather is still 0/N.
        self.guide_progress.emit(0, self._guide_total)
        self._advance_guides()

    def _advance_guides(self) -> None:
        """Extract the next queued guide, or hand the fill over (S6)."""
        target = self._guide_queue[0] if self._guide_queue else None
        if target is None:
            self._hand_off()
            return
        self._guide_attempts = 0
        self._source.seek_frame(target, self._state.fps)
        captured = self._source.grab_frame(self._state.fps)
        self._request_guide_extraction(target, captured)

    def _request_guide_extraction(
        self, target: int, captured: CapturedFrame | None
    ) -> None:
        """Start one guide's extraction, or wait for the frame to arrive."""
        usable = captured is not None and captured.frame_index in (None, target)
        if not usable:
            self._schedule_guide_retry(target)
            return
        # Claim the extraction like marking does; a guide's result must not
        # look stale for the same reason a key's cannot.
        previous_claim = self._extraction_generation
        self._extraction_generation = self._generation
        self._guide_pending = target
        self._guide_attempts = 0
        assert self._extractor is not None  # the queue exists only with an engine
        if not self._extractor.start(target, captured.image):
            self._extraction_generation = previous_claim
            self._guide_pending = None
            if self._extractor_has_free_signal:
                self._guide_busy_waits += 1
                if self._guide_busy_waits > _GUIDE_GRAB_TRIES:
                    self._degrade_to_keys_only("the extractor is busy")
                # else: the runner keeps announcing state; the gather resumes
                # in _on_extractor_freed when it frees up.
                return
            self._degrade_to_keys_only("the extractor is busy")
        else:
            self._guide_busy_waits = 0  # the wait paid off: a continuous gather

    def _on_extractor_freed(self, busy: bool) -> None:
        """Resume a guide gather paused on a busy batch-1 runner (T9)."""
        if busy or not self._fill_active or self._guide_pending is not None:
            return
        if not self._guide_queue or self._inbetween_generation != self._generation:
            return
        self._advance_guides()

    def _schedule_guide_retry(self, target: int) -> None:
        """The seek is asynchronous: give the pane a moment, then try again."""
        self._guide_attempts += 1
        if self._guide_attempts > _GUIDE_GRAB_TRIES:
            self._degrade_to_keys_only("the frame could not be captured")
            return
        if self._guide_timer is None:
            self._guide_timer = QTimer(self)
            self._guide_timer.setSingleShot(True)
            self._guide_timer.timeout.connect(self._retry_guide_grab)
        self._guide_timer.start(_GUIDE_GRAB_INTERVAL_MS)

    def _retry_guide_grab(self) -> None:
        if not self._guide_queue or self._inbetween_generation != self._generation:
            return
        target = self._guide_queue[0]
        self._request_guide_extraction(target, self._source.grab_frame(self._state.fps))

    def _degrade_to_keys_only(self, reason: str) -> None:
        """Stop gathering; the fill continues from the keys alone (S6)."""
        self._guide_queue = []
        self._guide_pending = None
        self._hand_off(
            actionable=(
                f"Capture guides unavailable ({reason}); "
                f"generating from the golden poses only…"
            )
        )

    def _hand_off(self, actionable: str | None = None) -> None:
        """Start the inbetweening runner with the gathered guides attached."""
        if not self._fill_active:
            return
        guides = self._guides or None
        frames = key_frames(self._state)
        # Claim the fill *before* handing it over, exactly like extraction: an
        # engine may answer synchronously, and its result must not look stale
        # when it does.
        previous_claim = self._inbetween_generation
        self._inbetween_generation = self._generation
        assert self._inbetweener is not None
        if not self._inbetweener.start(self._state, guides=guides):
            self._inbetween_generation = previous_claim
            self._fill_active = False
            self._report(_INBETWEEN_BUSY)
            return

        # The gathering phase is over (whatever guides exist are the request's
        # now); announce it so the bar can drop into its engine-fill mode.
        self.guide_progress.emit(self._guide_total, self._guide_total)
        if guides is None:
            self._emit_status(
                actionable=actionable
                or f"Filling the gaps between {len(frames)} golden poses…"
            )
        else:
            self._emit_status(
                actionable=f"Extracted {len(guides)} capture guides; "
                f"filling between {len(frames)} golden poses…"
            )

    def _on_inbetweens_filled(self, filled: TimelineState) -> None:
        """Adopt the engine's filled timeline; keys are guaranteed untouched.

        The result is discarded when the clip it was generated for is no longer
        open: the previous clip's keys must not rewrite a replacement's
        timeline, for the same reason an extraction result is (M5, S5).

        Before adopting, the pin pass (M7, FR-IK-01) holds the planted contacts
        the pre-fill keys agree on — detection needs those keys, which is why
        pinning runs here, not at export time. Pinning never blocks adoption:
        a skeleton without complete leg chains degrades it with a note.
        """
        if self._inbetween_generation != self._generation:
            self._report(_INBETWEENS_STALE)
            return
        self._inbetween_generation = None
        self._fill_active = False
        before = len(key_frames(self._state))
        # M8 S5: the engine output carries the captured/decoded root
        # trajectory; damp its frame-to-frame jitter before anything else uses
        # it, while the original keys keep their exact captured values.
        filled = smooth_root_trajectory(filled, self._fill_original_keys)[0]
        corrected, pin_note = self._pin_filled(filled)
        self._state = corrected
        self.timeline_changed.emit()
        self.pose_changed.emit(self.current_pose())
        self._emit_status(
            actionable=(
                f"Generated {len(key_frames(filled)) - before} inbetween frames "
                f"between {before} golden poses.{pin_note}"
            )
        )

    def _pin_filled(self, filled: TimelineState) -> tuple[TimelineState, str]:
        """Pin planted contacts on the filled timeline; never fail the fill.

        Returns the corrected state and a status-note suffix (possibly empty).
        A skeleton without the foot joints, or with a broken leg chain, is a
        typed degradation: the fill is adopted unpinned and the note says why.
        """
        keys = self._fill_original_keys
        self._fill_original_keys = ()
        if not keys:
            return filled, ""
        names = {joint.name for joint in filled.skeleton.joints}
        required = {name for pair in FOOT_JOINTS for name in pair}
        missing = sorted(required - names)
        if missing:
            return filled, f" Foot pinning skipped (no joints: {', '.join(missing)})."
        try:
            pinned, report = pin_foot_contacts(
                filled,
                keys,
                preserve_original_keys=False,
                ground_contacts=True,
            )
        except ValueError as error:
            # e.g. an incomplete leg chain (a joint's parent is missing).
            return filled, f" Foot pinning skipped ({error})."
        if not report.spans_pinned:
            return pinned, ""
        note = (
            f" Pinned {report.frames_corrected} contact frame(s) across "
            f"{len(report.spans_pinned)} span(s) ({', '.join(report.feet_pinned)})."
        )
        if report.clamped:
            note += f" Reach clamped for {', '.join(report.clamped)}."
        return pinned, note

    def _on_inbetweens_failed(self, message: str) -> None:
        """Report a failed fill; the keys survive untouched (FR-GEN-03)."""
        if self._inbetween_generation != self._generation:
            self._report(_INBETWEENS_STALE)
            return
        self._inbetween_generation = None
        self._fill_active = False
        self._fill_original_keys = ()
        self._report(f"Inbetween generation failed: {message}")

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
