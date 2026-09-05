"""In-between generation and enrichment math for the animation domain (§12.5).

A deterministic, stateless, pure-stdlib enrichment stage that consumes a
:class:`~NeutralMotion` and produces an enriched copy. Slice 1 (PR1) covered the
domain *timing* math:

- :class:`InbetweenParams` — validated, frozen parameters (VALIDATE).
- :func:`_ease` — monotonic easing curves with f(0)=0 and f(1)=1 (EASING).
- :func:`_resample` — keyframe-exact cubic/linear upsample with easing fused
  into the per-interval timing, upsample-only (RESAMPLE); rotations are
  interpolated with shortest-arc slerp (ROT).

Slice 2 (PR2) adds the domain *trajectory* math:

- :func:`_slerp` — sign-canonicalized shortest-arc interpolation with an
  anti-NaN nlerp fallback near antipodal pairs (ROT).
- :func:`_apply_rotation_filter` — post-pass sign canonicalization of each
  joint's rotation track (ROT).
- :func:`_apply_tangent_smooth` — centered-box smoothing, translation axes
  only (SMOOTH).
- :func:`enrich_motion` — the fixed-stage public pipeline
  resample → rotation → smooth with ``validate_invariants()`` last (ORDER).

No numpy/scipy — the domain guardrail ("domain is pure", AGENTS.md §3.1)
mirrors the temporal-cleanup precedent.
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
            q0 = motion.frames[index].pose.transforms[bone].rotation
            q1 = motion.frames[index + 1].pose.transforms[bone].rotation
            transforms[bone] = Transform3D(
                translation=vals,
                rotation=_slerp(q0, q1, u),
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


# --------------------------------------------------------------------------- #
# Quaternion helpers (ROT) — shortest-arc interpolation, anti-NaN fallback
# --------------------------------------------------------------------------- #

#: Threshold beyond which slerp degenerates (nearly parallel quaternions);
#: the division by ``sin(theta)`` would lose precision / produce NaN.
_SLERP_EPS: float = 1e-6


def _quat_dot(
    qa: tuple[float, float, float, float], qb: tuple[float, float, float, float]
) -> float:
    """Dot product of two quaternions ``(w, x, y, z)``."""
    return qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3]


def _quat_negate(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Negate a quaternion (``-q`` encodes the same rotation as ``q``)."""
    return (-q[0], -q[1], -q[2], -q[3])


def _quat_normalize(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Rescale ``q`` to unit norm; a zero quaternion stays zero."""
    norm = math.sqrt(_quat_dot(q, q))
    if norm == 0.0:
        return q
    inv = 1.0 / norm
    return (q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv)


def _slerp(
    q0: tuple[float, float, float, float],
    q1: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    """Spherical interpolation between two unit quaternions along the short arc.

    The far endpoint is sign-canonicalized first (``-q`` is the same rotation as
    ``q``): when the pair's dot product is negative the second endpoint is
    flipped, so the interpolation follows the short arc. Near-parallel pairs
    (``|dot| > 1 - 1e-6``, i.e. ``sin(theta) < 1e-6``) use normalized linear
    interpolation instead of slerp to avoid dividing by ~zero (anti-NaN). The
    result is a unit quaternion; endpoints are reproduced exactly at ``t=0``
    and ``t=1``.
    """
    # Canonicalize pre-interpolation: flip the far endpoint onto the short arc.
    dot = _quat_dot(q0, q1)
    if dot < 0.0:
        q1 = _quat_negate(q1)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))  # clamp float noise

    if dot > 1.0 - _SLERP_EPS:
        # Nearly parallel: nlerp — no acos/sin division, hence no NaN.
        blend = (
            q0[0] + t * (q1[0] - q0[0]),
            q0[1] + t * (q1[1] - q0[1]),
            q0[2] + t * (q1[2] - q0[2]),
            q0[3] + t * (q1[3] - q0[3]),
        )
        return _quat_normalize(blend)

    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    if sin_theta < _SLERP_EPS:  # numerical guard; unreachable after clamp
        blend = (
            q0[0] + t * (q1[0] - q0[0]),
            q0[1] + t * (q1[1] - q0[1]),
            q0[2] + t * (q1[2] - q0[2]),
            q0[3] + t * (q1[3] - q0[3]),
        )
        return _quat_normalize(blend)

    w0 = math.sin((1.0 - t) * theta) / sin_theta
    w1 = math.sin(t * theta) / sin_theta
    return (
        w0 * q0[0] + w1 * q1[0],
        w0 * q0[1] + w1 * q1[1],
        w0 * q0[2] + w1 * q1[2],
        w0 * q0[3] + w1 * q1[3],
    )


def _canonicalize_rotation_track(
    track: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """Running-sign canonicalization: consecutive quaternions keep positive dot.

    Each rotation is compared against the previously canonicalized one; if the
    dot is negative the current rotation is flipped (``-q`` == ``q``). This is
    the post-interpolation pass that clears residual sign discontinuities left
    between resampled intervals.
    """
    out: list[tuple[float, float, float, float]] = []
    for rotation in track:
        if out and _quat_dot(out[-1], rotation) < 0.0:
            rotation = _quat_negate(rotation)
        out.append(rotation)
    return out


def _apply_rotation_filter(motion: NeutralMotion, enabled: bool) -> NeutralMotion:
    """Canonicalize each joint's rotation track; no-op when ``enabled=False``.

    After resampling, interval-local slerp may leave sign discontinuities at
    shared source keys (each interval canonicalizes its own far endpoint). This
    post-pass walks every joint's rotation track and flips any sample whose dot
    with the previous one is negative, so every consecutive pair ends with a
    positive dot product. With ``enabled=False`` (``euler_filter=false``) the
    rotations pass through unchanged.
    """
    if not enabled:
        return motion

    bones = _joints_of(motion)
    canonical = {
        bone: _canonicalize_rotation_track([_rotation_of(f, bone) for f in motion.frames])
        for bone in bones
    }
    frames: list[Frame] = []
    for i, frame in enumerate(motion.frames):
        transforms = {
            name: transform.model_copy(update={"rotation": canonical[name][i]})
            for name, transform in frame.pose.transforms.items()
        }
        frames.append(frame.model_copy(update={"pose": Pose(transforms=transforms)}))
    return motion.model_copy(update={"frames": frames})


def _joints_of(motion: NeutralMotion) -> list[str]:
    """The ordered joint names present in the first frame's pose."""
    if not motion.frames:
        return []
    return list(motion.frames[0].pose.transforms.keys())


def _rotation_of(frame: Frame, bone: str) -> tuple[float, float, float, float]:
    """The bone's rotation quaternion in ``frame``."""
    return frame.pose.transforms[bone].rotation


# --------------------------------------------------------------------------- #
# Tangent smoothing (SMOOTH) — centered box, translation axes only
# --------------------------------------------------------------------------- #


def _apply_tangent_smooth(motion: NeutralMotion, intensity: float) -> NeutralMotion:
    """Smooth per-joint translation trajectories with a centered box filter.

    The box window is ``1 + round(intensity * 9)`` (even results rounded down
    to the nearest odd width, so the box is perfectly centered): ``intensity=0``
    is the identity (window 1) and the smoothing magnitude is non-decreasing
    with the parameter. Every output sample is the mean of exactly ``window``
    inbound samples (the window is bounded by repeating the edge value), so the
    filter is variance-reducing on the trajectory's jitter. The filter is
    applied per translation axis only — rotations are left untouched
    (norm-drift risk; explicit design decision). Returns ``motion`` unchanged
    when ``intensity <= 0``.
    """
    if intensity <= 0.0:
        return motion

    window = 1 + round(intensity * 9)
    if window % 2 == 0:
        window -= 1  # centered boxes are odd-width; round even windows down
    radius = window // 2
    n_frames = len(motion.frames)
    bones = _joints_of(motion)

    def _box1d(values: list[float], i: int) -> float:
        """Mean of the centered ``window``-wide neighborhood of ``values[i]``."""
        total = 0.0
        for j in range(-radius, radius + 1):
            idx = min(max(i + j, 0), n_frames - 1)
            total += values[idx]
        return total / window

    # Per-bone per-axis smoothed tracks via a clamped centered-box average.
    smoothed: dict[str, list[tuple[float, float, float]]] = {}
    for bone in bones:
        track = [f.pose.transforms[bone].translation for f in motion.frames]
        smoothed[bone] = [
            (
                _box1d([t[0] for t in track], i),
                _box1d([t[1] for t in track], i),
                _box1d([t[2] for t in track], i),
            )
            for i in range(n_frames)
        ]

    frames: list[Frame] = []
    for i, frame in enumerate(motion.frames):
        transforms = {
            name: transform.model_copy(update={"translation": smoothed[name][i]})
            for name, transform in frame.pose.transforms.items()
        }
        frames.append(frame.model_copy(update={"pose": Pose(transforms=transforms)}))
    return motion.model_copy(update={"frames": frames})


# --------------------------------------------------------------------------- #
# Public pipeline (ORDER) — fixed stage order, stateless and deterministic
# --------------------------------------------------------------------------- #


def enrich_motion(
    motion: NeutralMotion, params: InbetweenParams | None = None
) -> NeutralMotion:
    """Apply the full enrichment pipeline to ``motion``.

    Stages run in the fixed order resample → (fused) easing → rotation filter →
    tangent smoothing:

    1. :func:`_resample` upsamples onto the target-fps grid with easing fused
       into the per-interval timing and shortest-arc slerped rotations; a
       no-op (passthrough) when no upsample is warranted. Updates ``meta.fps``
       and ``duration_frames``; new frames get ``confidence=None``.
    2. :func:`_apply_rotation_filter` canonicalizes rotation signs when
       ``euler_filter`` is enabled.
    3. :func:`_apply_tangent_smooth` applies the centered box to translation
       axes when ``tangent_smoothing > 0``.

    The stage is stateless and deterministic — identical inputs yield
    byte-identical outputs — and :meth:`NeutralMotion.validate_invariants` runs
    last, so the returned document always satisfies the neutral-motion
    invariants. ``contacts``, ``keyposes`` and ``tracking`` pass through
    unmodified (MVP; frame references may be stale after upsample — remap is
    deferred). ``params=None`` uses :class:`InbetweenParams` defaults.
    """
    p = params if params is not None else InbetweenParams()
    out = _resample(motion, p.target_fps, p.interpolation_method, p.easing)
    out = _apply_rotation_filter(out, enabled=p.euler_filter)
    out = _apply_tangent_smooth(out, intensity=p.tangent_smoothing)
    out.validate_invariants()
    return out
