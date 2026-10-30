"""The preview's playback timer (S1).

The viewer owns a clock that is independent of the animator's timeline: the
timer advances ``scene.preview_frame`` on the *working* scene, and the frame
update callback mirrors that number into the preview scene. Nothing here
touches ``bpy.context.scene``, so the animator can scrub their own timeline
while the capture keeps playing in its own window.

The arithmetic lives in :mod:`clock`, which is ``bpy``-free and covered by the
repository's pytest run.
"""

from __future__ import annotations

import time

import bpy

from . import clock

__all__ = ["is_playing", "reset", "start", "stop"]

#: Never tick slower than this, so a 5 fps capture still feels alive when the
#: animator drags the slider mid-playback.
_MAX_TICK_SECONDS = 1.0 / 60.0

_playing_owner: str | None = None
_started_at = 0.0
_start_frame = 0


def is_playing() -> bool:
    """Whether the timer is currently registered."""
    return bpy.app.timers.is_registered(_tick)


def start(owner) -> None:
    """Start (or restart) advancing ``owner``'s preview from its current frame."""
    global _playing_owner, _started_at, _start_frame
    _playing_owner = owner.name
    _started_at = time.monotonic()
    _start_frame = owner.preview_frame
    if not is_playing():
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=False)


def stop() -> None:
    """Unregister the timer. Safe to call when playback is already stopped."""
    global _playing_owner
    _playing_owner = None
    if is_playing():
        bpy.app.timers.unregister(_tick)


def reset(owner) -> None:
    """Stop the clock whenever the capture under it is replaced or removed."""
    owner.preview_playing = False
    stop()


def _tick():
    """Advance one step, or unregister by returning ``None``.

    The timer looks its owner scene up by name on every tick instead of holding
    a ``Scene`` reference: a closed ``.blend`` must not keep the old scene alive,
    and playback must die honestly when that scene is gone (S9).
    """
    owner = bpy.data.scenes.get(_playing_owner) if _playing_owner else None
    if owner is None or not owner.preview_playing:
        return None

    first = owner.capture_first
    last = owner.capture_last
    if last <= first:
        owner.preview_playing = False
        return None

    fps = owner.capture_fps
    frame = clock.frame_at(time.monotonic(), _started_at, _start_frame, fps, first, last)
    if frame != owner.preview_frame:
        owner.preview_frame = frame
    return min(_MAX_TICK_SECONDS, 1.0 / fps) if fps > 0.0 else _MAX_TICK_SECONDS
