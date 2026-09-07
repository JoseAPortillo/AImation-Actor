"""Temporal cleanup algorithms for the animation domain (§12.4).

A deterministic, stateless, pure-stdlib cleanup stage that consumes a
:class:`~NeutralMotion` (in LOCAL coordinate space, as emitted by
``VideoToMotionNode`` in ``only_local`` mode) and applies a fixed five-stage
chain:

1. :func:`_one_euro_smooth` — per-joint one-euro jitter filtering.
2. :func:`_detect_contacts` — velocity + height foot-contact detection with
   hysteresis, writing to ``contacts["left_foot"]`` / ``["right_foot"]``.
3. :func:`_apply_foot_lock` — translation-only XZ clamp of contact feet
   (rotation untouched; rotational IK is deferred).
4. :func:`_apply_ground_clamp` — raise feet to ``Y >= 0`` by lifting the hips
   by the penetration delta.
5. :func:`_normalize_root` — subtract the cumulative root drift while
   preserving relative joint motion.

All transforms are frozen, so every stage constructs new instances rather than
mutating. No numpy/scipy — the domain guardrail ("domain is pure").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import (
    ContactFeed,
    FootContact,
    NeutralMotion,
)

#: One-Euro low-pass cutoff (Hz); preserves intentional motion at 24fps.
DEFAULT_MIN_CUTOFF = 1.0
#: One-Euro speed coefficient — higher = less lag for fast motion.
DEFAULT_BETA = 0.5
#: cm/frame below which a foot's translation speed suggests a potential contact.
DEFAULT_VELOCITY_THRESHOLD = 5.0
#: cm — a foot's world Y within this of the floor is considered near-contact.
DEFAULT_HEIGHT_THRESHOLD = 10.0
#: min frames to hold a contact once entered (flicker suppression).
DEFAULT_HYSTERESIS_FRAMES = 4

#: Local foot bones (children of each leg), canonical names (ADR-001).
_FOOT_BONES = ("LeftFoot", "RightFoot")
#: Contact feed keys for each foot.
_FEED_KEYS = ("left_foot", "right_foot")
#: The hips bone — the root whose drift is normalized and which is raised.
_ROOT_BONE = "Hips"


@dataclass(frozen=True)
class CleanupParams:
    """Tunable parameters for the temporal cleanup chain.

    Attributes:
        min_cutoff: One-Euro minimum cutoff frequency (Hz).
        beta: One-Euro speed coefficient.
        velocity_threshold: cm/frame speed below which a foot may be in contact.
        height_threshold: cm above the floor within which a foot is near-contact.
        hysteresis_frames: minimum frames to hold a contact once entered.
    """

    min_cutoff: float = DEFAULT_MIN_CUTOFF
    beta: float = DEFAULT_BETA
    velocity_threshold: float = DEFAULT_VELOCITY_THRESHOLD
    height_threshold: float = DEFAULT_HEIGHT_THRESHOLD
    hysteresis_frames: int = DEFAULT_HYSTERESIS_FRAMES


def _f(motion: NeutralMotion, frame_idx: int, bone: str) -> Transform3D:
    """Accessor for a bone transform at a frame index."""
    return motion.frames[frame_idx].pose.transforms[bone]


# --------------------------------------------------------------------------- #
# Local / world helpers (pure math, no numpy)
# --------------------------------------------------------------------------- #


def _world_positions(
    motion: NeutralMotion, frame_idx: int
) -> dict[str, tuple[float, float, float]]:
    """Accumulate every bone's world position for one frame.

    Walks the skeleton hierarchy in parents-before-children order (the preset
    guarantees it), summing local offsets from the root. Works for both
    ``only_local`` (offsets) and absolute frames because the root's local
    translation equals its world position.
    """
    frame = motion.frames[frame_idx]
    transforms = frame.pose.transforms
    world: dict[str, tuple[float, float, float]] = {}
    for name, bone in motion.skeleton.bones.items():
        t = transforms.get(name)
        local = t.translation if t is not None else bone.rest_position
        if bone.parent is None:
            world[name] = local
        else:
            px, py, pz = world[bone.parent]
            lx, ly, lz = local
            world[name] = (px + lx, py + ly, pz + lz)
    return world


# --------------------------------------------------------------------------- #
# Stage 1 — One-Euro jitter smoothing
# --------------------------------------------------------------------------- #


def _one_euro_axis(values: list[float], dt: float, min_cutoff: float, beta: float) -> list[float]:
    """Smooth a 1D per-frame track with a stateless one-euro low-pass filter."""
    n = len(values)
    if n <= 1:
        return list(values)
    out = [0.0] * n
    prev_x = values[0]
    out[0] = prev_x
    for i in range(1, n):
        dx = (values[i] - prev_x) / dt
        cutoff = min_cutoff + beta * abs(dx)
        tau = 1.0 / (2.0 * math.pi * cutoff)
        alpha = 1.0 / (1.0 + tau / dt)
        x_hat = alpha * values[i] + (1.0 - alpha) * prev_x
        out[i] = x_hat
        prev_x = x_hat
    return out


def _one_euro_smooth(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
    """Apply the one-euro filter to each bone's translation axes (stage 1)."""
    n = len(motion.frames)
    if n <= 1:
        return motion
    dt = 1.0 / motion.meta.fps if motion.meta.fps > 0 else 1.0 / 24.0
    bones = list(motion.frames[0].pose.transforms.keys())

    x_tracks: dict[str, list[float]] = {}
    y_tracks: dict[str, list[float]] = {}
    z_tracks: dict[str, list[float]] = {}
    for bone in bones:
        x = [_f(motion, i, bone).translation[0] for i in range(n)]
        y = [_f(motion, i, bone).translation[1] for i in range(n)]
        z = [_f(motion, i, bone).translation[2] for i in range(n)]
        x_tracks[bone] = _one_euro_axis(x, dt, params.min_cutoff, params.beta)
        y_tracks[bone] = _one_euro_axis(y, dt, params.min_cutoff, params.beta)
        z_tracks[bone] = _one_euro_axis(z, dt, params.min_cutoff, params.beta)

    frames = []
    for i, frame in enumerate(motion.frames):
        transforms = {}
        for bone in bones:
            orig = frame.pose.transforms[bone]
            transforms[bone] = Transform3D(
                translation=(x_tracks[bone][i], y_tracks[bone][i], z_tracks[bone][i]),
                rotation=orig.rotation,
                scale=orig.scale,
            )
        frames.append(
            Frame(
                frame=frame.frame,
                time=frame.time,
                pose=Pose(transforms=transforms),
                confidence=frame.confidence,
            )
        )
    return motion.model_copy(update={"frames": frames})


# --------------------------------------------------------------------------- #
# Stage 2 — Foot-contact detection with hysteresis
# --------------------------------------------------------------------------- #


def _detect_contacts(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
    """Detect foot contacts (velocity + height) with hysteresis (stage 2)."""
    n = len(motion.frames)
    if n == 0:
        return motion

    velocities: dict[str, list[float]] = {side: [0.0] * n for side in _FEED_KEYS}
    heights: dict[str, list[float]] = {side: [0.0] * n for side in _FEED_KEYS}

    prev_world = _world_positions(motion, 0)
    for side, bone in zip(_FEED_KEYS, _FOOT_BONES, strict=True):
        heights[side][0] = prev_world[bone][1]

    for i in range(1, n):
        world = _world_positions(motion, i)
        for side, bone in zip(_FEED_KEYS, _FOOT_BONES, strict=True):
            px, py, pz = prev_world[bone]
            cx, cy, cz = world[bone]
            velocities[side][i] = math.hypot(cx - px, cy - py, cz - pz)
            heights[side][i] = cy
            prev_world[bone] = (cx, cy, cz)

    samples: dict[str, list[FootContact]] = {side: [] for side in _FEED_KEYS}
    in_contact = {side: False for side in _FEED_KEYS}
    hold = {side: 0 for side in _FEED_KEYS}

    for i in range(n):
        for side in _FEED_KEYS:
            raw = (
                velocities[side][i] < params.velocity_threshold
                and heights[side][i] < params.height_threshold
            )
            if raw:
                in_contact[side] = True
                hold[side] = params.hysteresis_frames
            elif in_contact[side]:
                if hold[side] > 0:
                    hold[side] -= 1
                else:
                    in_contact[side] = False
            samples[side].append(
                FootContact(frame=motion.frames[i].frame, contact=in_contact[side])
            )

    contacts = dict(motion.contacts)
    contacts["left_foot"] = ContactFeed(samples=samples["left_foot"])
    contacts["right_foot"] = ContactFeed(samples=samples["right_foot"])
    return motion.model_copy(update={"contacts": contacts})


# --------------------------------------------------------------------------- #
# Stage 3 — Translation-only foot locking
# --------------------------------------------------------------------------- #


def _contact_frame_numbers(motion: NeutralMotion, side: str) -> set[int]:
    """1-based frame numbers that are in contact for ``side``."""
    feed = motion.contacts.get(side)
    if feed is None:
        return set()
    return {s.frame for s in feed.samples if s.contact}


def _apply_foot_lock(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
    """Clamp contact foot XZ to the contact-frame value (stage 3)."""
    del params
    if not motion.frames:
        return motion

    anchors_by_foot: dict[str, dict[int, tuple[float, float]]] = {}
    for side, bone in zip(_FEED_KEYS, _FOOT_BONES, strict=True):
        if bone not in motion.skeleton.bones:
            continue
        frames_sorted = sorted(_contact_frame_numbers(motion, side))
        run: list[int] = []
        anchors: dict[int, tuple[float, float]] = {}
        anchor_xz: tuple[float, float] | None = None
        for frame_no in frames_sorted:
            idx = frame_no - 1
            if idx < 0 or idx >= len(motion.frames):
                continue
            t = motion.frames[idx].pose.transforms.get(bone)
            if t is None:
                continue
            tx, tz = t.translation[0], t.translation[2]
            if not run or frame_no != run[-1] + 1:
                # A new contact run: lock every frame in it to the run's
                # starting XZ so the foot does not slide during the hold.
                anchor_xz = (tx, tz)
                run = [frame_no]
            else:
                run.append(frame_no)
            if anchor_xz is None:  # pragma: no cover - always set at run start
                anchor_xz = (tx, tz)
            anchors[frame_no] = anchor_xz
        anchors_by_foot[side] = anchors

    frames: list[Frame] = []
    for frame in motion.frames:
        transforms = dict(frame.pose.transforms)
        for side, bone in zip(_FEED_KEYS, _FOOT_BONES, strict=True):
            anchor = anchors_by_foot.get(side, {}).get(frame.frame)
            if anchor is None:
                continue
            ax, az = anchor
            t = transforms[bone]
            transforms[bone] = Transform3D(
                translation=(ax, t.translation[1], az),
                rotation=t.rotation,
                scale=t.scale,
            )
        frames.append(
            Frame(
                frame=frame.frame,
                time=frame.time,
                pose=Pose(transforms=transforms),
                confidence=frame.confidence,
            )
        )
    return motion.model_copy(update={"frames": frames})


# --------------------------------------------------------------------------- #
# Stage 4 — Ground clamping
# --------------------------------------------------------------------------- #


def _raise_bone(motion: NeutralMotion, bone: str, delta_y: float) -> NeutralMotion:
    """Return a copy of ``motion`` with ``bone``'s local Y raised by ``delta_y``."""
    frames: list[Frame] = []
    for frame in motion.frames:
        transforms = dict(frame.pose.transforms)
        if bone in transforms:
            t = transforms[bone]
            transforms[bone] = Transform3D(
                translation=(t.translation[0], t.translation[1] + delta_y, t.translation[2]),
                rotation=t.rotation,
                scale=t.scale,
            )
        frames.append(
            Frame(
                frame=frame.frame,
                time=frame.time,
                pose=Pose(transforms=transforms),
                confidence=frame.confidence,
            )
        )
    return motion.model_copy(update={"frames": frames})


def _world_y_for(motion: NeutralMotion, frame_idx: int, bone: str) -> float:
    """World Y of a single bone for one frame (helper with hierarchy walk)."""
    name = bone
    acc = 0.0
    while True:
        b = motion.skeleton.bones[name]
        t = motion.frames[frame_idx].pose.transforms.get(name)
        acc += t.translation[1] if t is not None else b.rest_position[1]
        if b.parent is None:
            return acc
        name = b.parent


def _apply_ground_clamp(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
    """Raise feet to ``Y >= 0`` by lifting the hips by the penetration delta (stage 4)."""
    del params
    if not motion.frames:
        return motion
    if any(bone not in motion.skeleton.bones for bone in _FOOT_BONES):
        return motion
    if _ROOT_BONE not in motion.skeleton.bones:
        return motion

    result = motion
    for i in range(len(result.frames)):
        ly = _world_y_for(result, i, "LeftFoot")
        ry = _world_y_for(result, i, "RightFoot")
        penetration = min(0.0, ly, ry)
        if penetration < 0.0:
            result = _raise_bone(result, _ROOT_BONE, -penetration)
    return result


# --------------------------------------------------------------------------- #
# Stage 5 — Root drift normalization
# --------------------------------------------------------------------------- #


def _normalize_root(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
    """Subtract the cumulative root drift, preserving relative joint motion (stage 5)."""
    del params
    n = len(motion.frames)
    if n <= 1 or _ROOT_BONE not in motion.skeleton.bones:
        return motion
    if _ROOT_BONE not in motion.frames[0].pose.transforms:
        return motion

    start = _f(motion, 0, _ROOT_BONE).translation
    end = _f(motion, n - 1, _ROOT_BONE).translation
    drift = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    if drift == (0.0, 0.0, 0.0):
        return motion

    denom = n - 1
    frames: list[Frame] = []
    for i, frame in enumerate(motion.frames):
        t = frame.pose.transforms[_ROOT_BONE]
        frac = i / denom
        new_t = Transform3D(
            translation=(
                t.translation[0] - drift[0] * frac,
                t.translation[1] - drift[1] * frac,
                t.translation[2] - drift[2] * frac,
            ),
            rotation=t.rotation,
            scale=t.scale,
        )
        transforms = dict(frame.pose.transforms)
        transforms[_ROOT_BONE] = new_t
        frames.append(
            Frame(
                frame=frame.frame,
                time=frame.time,
                pose=Pose(transforms=transforms),
                confidence=frame.confidence,
            )
        )
    return motion.model_copy(update={"frames": frames})


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def cleanup_motion(motion: NeutralMotion, params: CleanupParams | None = None) -> NeutralMotion:
    """Apply the five-stage deterministic cleanup chain.

    Args:
        motion: A :class:`NeutralMotion` document (immutable).
        params: Optional :class:`CleanupParams`; defaults are used when omitted.

    Returns:
        A new :class:`NeutralMotion` with smoothed joints, populated
        ``contacts``, locked feet, a clamped floor, and normalized root drift.
    """
    p = params if params is not None else CleanupParams()
    result = motion
    result = _one_euro_smooth(result, p)
    result = _detect_contacts(result, p)
    result = _apply_foot_lock(result, p)
    result = _apply_ground_clamp(result, p)
    result = _normalize_root(result, p)
    result.validate_invariants()
    return result
