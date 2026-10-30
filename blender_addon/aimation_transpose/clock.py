"""The preview clock: frame arithmetic with no ``bpy`` and no wall clock.

The viewer's playback owns a clock that is independent of the animator's
timeline (S1), so the only thing worth testing is the arithmetic: which frame
should be shown ``elapsed`` seconds after the play button was pressed.
"""

from __future__ import annotations

__all__ = ["frame_at"]


def frame_at(
    now: float,
    started_at: float,
    start_frame: int,
    fps: float,
    first: int,
    last: int,
) -> int:
    """The frame the preview shows ``now`` seconds after playback started.

    Playback wraps inside ``[first, last]`` so a capture loops while the
    animator watches it. A non-positive ``fps`` or an inverted range keeps the
    starting frame instead of dividing by zero (S9).
    """
    span = last - first + 1
    if span <= 0:
        return first
    if fps <= 0.0:
        return start_frame
    elapsed = max(0.0, now - started_at)
    steps = int(elapsed * fps)
    return first + (start_frame - first + steps) % span
