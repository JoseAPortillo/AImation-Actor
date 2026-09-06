"""In-between generation and enrichment math for the animation domain (§12.5).

A deterministic, stateless, pure-stdlib enrichment stage that consumes a
:class:`~NeutralMotion` and produces an enriched copy. Slice 1 (PR1) covers the
domain *timing* math only:

- :class:`InbetweenParams` — validated, frozen parameters (VALIDATE).
- :func:`_ease` — monotonic easing curves with f(0)=0 and f(1)=1 (EASING).
- :func:`_resample` — keyframe-exact cubic/linear upsample with easing fused
  into the per-interval timing, upsample-only (RESAMPLE).

Later slices add rotation continuity filtering, tangent smoothing, and the
public :func:`enrich_motion` pipeline (PR2). No numpy/scipy — the domain
guardrail ("domain is pure", AGENTS.md §3.1) mirrors the temporal-cleanup
precedent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion

#: Valid interpolation methods.
_VALID_INTERPOLATION = frozenset({"linear", "cubic"})
#: Valid easing curves.
_VALID_EASING = frozenset({"none", "ease-in", "ease-out", "ease-in-out"})

DEFAULT_INTERPOLATION_METHOD: str = "cubic"
DEFAULT_TARGET_FPS: float = 30.0
DEFAULT_EASING: str = "none"
DEFAULT_EULER_FILTER: bool = True
DEFAULT_TANGENT_SMOOTHING: float = 0.0


def _value_error(message: str) -> ValueError:
    """Build a consistently-worded :class:`ValueError`."""
    return ValueError(message)


@dataclass(frozen=True)
class InbetweenParams:
    """Validated parameters for the in-between enrichment stage.

    Attributes:
        interpolation_method: ``"linear"`` or ``"cubic"`` (default ``"cubic"``).
        target_fps: Positive frame rate to upsample onto (default ``30``).
        easing: ``"none"``, ``"ease-in"``, ``"ease-out"`` or ``"ease-in-out"``
            (default ``"none"``).
        euler_filter: Whether to canonicalize rotation continuity
            (default ``True``; unused by slice 1 resampling).
        tangent_smoothing: Smoothing intensity in ``[0, 1]`` (default ``0.0``;
            unused by slice 1 resampling).

    Raises:
        ValueError: If any field is an invalid enum, out of range, or a
            non-positive frame rate.
    """

    interpolation_method: str = DEFAULT_INTERPOLATION_METHOD
    target_fps: float = DEFAULT_TARGET_FPS
    easing: str = DEFAULT_EASING
    euler_filter: bool = DEFAULT_EULER_FILTER
    tangent_smoothing: float = DEFAULT_TANGENT_SMOOTHING

    def __post_init__(self) -> None:
        if self.interpolation_method not in _VALID_INTERPOLATION:
            raise _value_error(
                f"interpolation_method must be one of {sorted(_VALID_INTERPOLATION)}, "
                f"got {self.interpolation_method!r}"
            )
        if self.easing not in _VALID_EASING:
            raise _value_error(
                f"easing must be one of {sorted(_VALID_EASING)}, got {self.easing!r}"
            )
        if not isinstance(self.euler_filter, bool):
            raise _value_error(f"euler_filter must be a bool, got {self.euler_filter!r}")
        if not 0.0 <= self.tangent_smoothing <= 1.0:
            raise _value_error(
                f"tangent_smoothing must be in [0, 1], got {self.tangent_smoothing!r}"
            )
        if not self.target_fps > 0:
            raise _value_error(f"target_fps must be positive, got {self.target_fps!r}")


# --------------------------------------------------------------------------- #
# Easing (EASING) — monotonic, f(0)=0, f(1)=1
# --------------------------------------------------------------------------- #


def _ease(t: float, easing: str) -> float:
    """Map a normalized interval position ``t`` in ``[0,1]`` through an easing curve.

    Each curve is monotonic with f(0)=0 and f(1)=1, so keyframe values stay
    exact at their timeline positions. ``"none"`` is the identity.
    """
    if easing == "none":
        return t
    if easing == "ease-in":
        return t * t
    if easing == "ease-out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if easing == "ease-in-out":
        return 3.0 * t * t - 2.0 * t * t * t
    raise _value_error(f"unknown easing {easing!r}")


# --------------------------------------------------------------------------- #
# Cubic-Hermite helpers (RESAMPLE)
# --------------------------------------------------------------------------- #


def _catmull_rom_tangents(values: list[float]) -> list[float]:
    """Per-vertex Catmull-Rom tangents; one-sided at the ends.

    Values are indexed by normalized position ``i`` (integer). The tangent at
    vertex ``i`` is ``(v[i+1] - v[i-1]) / 2`` with one-sided first differences
    at the end vertices.
    """
    n = len(values)
    if n == 1:
        return [0.0]
    tangents = [0.0] * n
    tangents[0] = values[1] - values[0]
    for i in range(1, n - 1):
        tangents[i] = (values[i + 1] - values[i - 1]) / 2.0
    tangents[n - 1] = values[n - 1] - values[n - 2]
    return tangents


def _hermite_value(p0: float, m0: float, p1: float, m1: float, u: float) -> float:
    """Evaluate a cubic-Hermite interpolant at eased position ``u`` in [0,1]."""
    u2 = u * u
    u3 = u2 * u
    h00 = 2.0 * u3 - 3.0 * u2 + 1.0
    h10 = u3 - 2.0 * u2 + u
    h01 = -2.0 * u3 + 3.0 * u2
    h11 = u3 - u2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def _interp_value(
    values: list[float],
    tangents: list[float],
    method: str,
    index: int,
    u: float,
) -> float:
    """Evaluate the interpolant for interval ``[index, index+1]`` at eased ``u``."""
    if method == "linear":
        return values[index] + (values[index + 1] - values[index]) * u
    return _hermite_value(
        values[index], tangents[index], values[index + 1], tangents[index + 1], u
    )


# --------------------------------------------------------------------------- #
# Resampling (RESAMPLE)
# --------------------------------------------------------------------------- #


def _resample(
    motion: NeutralMotion,
    target_fps: float,
    method: str = DEFAULT_INTERPOLATION_METHOD,
    easing: str = DEFAULT_EASING,
) -> NeutralMotion:
    """Upsample ``motion`` onto the ``target_fps`` grid; pass through otherwise.

    Args:
        motion: A :class:`NeutralMotion` document (immutable).
        target_fps: Frame rate to upsample onto (must exceed ``meta.fps``
            to trigger resampling; otherwise passthrough).
        method: ``"cubic"`` (cubic-Hermite) or ``"linear"``.
        easing: One of the easing curves from :func:`_ease`, fused into the
            per-interval timing.

    Returns:
        A new :class:`NeutralMotion` with resampled frames on the target grid,
        or ``motion`` unchanged when no upsample is warranted (single frame or
        ``target_fps <= meta.fps``). ``meta.fps`` and ``duration_frames`` are
        updated whenever resampling occurs.
    """
    n_in = len(motion.frames)
    if n_in <= 1 or target_fps <= motion.meta.fps:
        return motion

    source_fps = motion.meta.fps
    span = (n_in - 1) / source_fps
    n_out = int(span * target_fps) + 1
    if n_out < 2:
        return motion

    first_time = motion.frames[0].time
    bones = list(motion.frames[0].pose.transforms.keys())
    n_src = n_in - 1

    # Per-bone translation tracks and their Catmull-Rom tangents.
    tracks = {
        bone: [f.pose.transforms[bone].translation for f in motion.frames] for bone in bones
    }
    tangents = {
        (bone, axis): _catmull_rom_tangents([t[axis] for t in tracks[bone]])
        for bone in bones
        for axis in range(3)
    }

    frames: list[Frame] = []
    for k in range(n_out):
        xi = (k / (n_out - 1)) * n_src if n_out > 1 else 0.0
        index = math.floor(xi)
        index = min(max(index, 0), n_src - 1)
        local = xi - index
        u = _ease(local, easing)
        transforms: dict[str, Transform3D] = {}
        for bone in bones:
            vals = (
                _interp_value(
                    [t[0] for t in tracks[bone]],
                    tangents[(bone, 0)],
                    method,
                    index,
                    u,
                ),
                _interp_value(
                    [t[1] for t in tracks[bone]],
                    tangents[(bone, 1)],
                    method,
                    index,
                    u,
                ),
                _interp_value(
                    [t[2] for t in tracks[bone]],
                    tangents[(bone, 2)],
                    method,
                    index,
                    u,
                ),
            )
            orig = motion.frames[0].pose.transforms[bone]
            transforms[bone] = Transform3D(
                translation=vals,
                rotation=orig.rotation,
                scale=orig.scale,
            )
        frames.append(
            Frame(
                frame=k + 1,
                time=first_time + k / target_fps,
                pose=Pose(transforms=transforms),
                confidence=None,
            )
        )

    meta = motion.meta.model_copy(update={"fps": float(target_fps), "duration_frames": n_out})
    return motion.model_copy(update={"frames": frames, "meta": meta})
