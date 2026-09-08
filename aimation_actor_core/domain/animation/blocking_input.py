"""Blocking-input payload model and domain converter (§20.5 / REQ-01, REQ-02, REQ-04).

A lightweight, DCC-friendly blocking payload (decision D1b) is modeled and
validated in the pure domain, then converted to a sparse :class:`NeutralMotion`
with populated ``keyposes``. The math and validation live here — the node
adapter (infrastructure) owns no conversion math (spec constraint).

This module is pure Pydantic + stdlib — no external deps (domain guardrail,
AGENTS.md §3.1). Frozen models with ``extra="forbid"`` reject any unknown field
(REQ-01 SC-02), and bounded validation follows decision D4: maximum keypose
count, weight in ``[0,1]``, finite-only numeric values, unit-norm non-zero
quaternions.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import (
    KeyPose,
    NeutralMeta,
    NeutralMotion,
)
from aimation_actor_core.domain.animation.skeleton import Skeleton
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

#: Default frame rate for blocking documents (blocking-friendly rate, D1b).
DEFAULT_BLOCKING_FPS: float = 24.0
#: Maximum number of keyposes (D4 bound — prevents unbounded resample).
MAX_KEYPOSES: int = 1000
#: Weight band ``>=`` this value triggers exact-lock in ``inbetween-generation`` (D4).
EXACT_LOCK_MIN: float = 0.99
#: Quaternion unit-norm tolerance.
_QUAT_NORM_TOL: float = 1e-3


class BlockingKeyPose(BaseModel):
    """A single authored key pose at a concrete frame (REQ-01).

    Attributes:
        frame: Positive (``>= 1``) frame number within the timeline.
        pose: Full per-bone transform set naming every bone of the resolved
            skeleton.
        weight: Blend weight in ``[0, 1]`` (default ``1.0``) controlling the
            exact-lock band in ``inbetween-generation``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    frame: int = Field(ge=1)
    pose: dict[str, Transform3D]
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_finite_unit_quats(self) -> BlockingKeyPose:
        """Reject non-finite values and non-unit / all-zero quaternions (D4).

        Every rotation quaternion must be finite and unit-norm within
        tolerance; every translation/scale component must be finite.
        """
        for name, transform in self.pose.items():
            for label, value in (
                ("translation", transform.translation),
                ("scale", transform.scale),
            ):
                if not all(math.isfinite(c) for c in value):
                    raise ValueError(f"{name}.{label} must be finite (no NaN/Inf)")
            q = transform.rotation
            if not all(math.isfinite(c) for c in q):
                raise ValueError(f"{name}.rotation must be finite (no NaN/Inf)")
            norm = math.sqrt(sum(c * c for c in q))
            if norm == 0.0:
                raise ValueError(f"{name}.rotation must not be the all-zero quaternion")
            if abs(norm - 1.0) > _QUAT_NORM_TOL:
                raise ValueError(f"{name}.rotation must be a unit quaternion (norm={norm:.4f})")
        return self


class BlockingInput(BaseModel):
    """The blocking payload: an optional skeleton plus ordered keyposes.

    The ``skeleton`` field is optional (REQ-01); when omitted the converter uses
    the default neutral skeleton. Every keypose's ``pose`` must address exactly
    the resolved skeleton's bone set (REQ-01 SC-04).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skeleton: Skeleton | None = None
    keyposes: list[BlockingKeyPose] = Field(min_length=1, max_length=MAX_KEYPOSES)

    @model_validator(mode="after")
    def _validate_poses_match_skeleton(self) -> BlockingInput:
        """Every keypose pose must name exactly the resolved skeleton's bones."""
        resolved = self.resolved_skeleton()
        expected = set(resolved.bones.keys())
        for i, kp in enumerate(self.keyposes):
            actual = set(kp.pose.keys())
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                if missing or extra:
                    raise ValueError(
                        f"keypose {i} pose must address exactly the resolved skeleton "
                        f"bones; missing={missing}, extra={extra}"
                    )
        return self

    def resolved_skeleton(self) -> Skeleton:
        """The default neutral skeleton when none was provided, else ``self.skeleton``."""
        return self.skeleton if self.skeleton is not None else DEFAULT_NEUTRAL_SKELETON


def blocking_to_neutral_motion(input_: BlockingInput) -> NeutralMotion:
    """Convert a validated blocking payload into a sparse :class:`NeutralMotion`.

    One :class:`Frame` per keypose, frames strictly increasing (duplicates
    rejected), ``keyposes`` populated, default neutral skeleton when omitted,
    ``meta.fps`` defaulting to :data:`DEFAULT_BLOCKING_FPS`, and
    ``meta.duration_frames`` set to the highest keypose frame. The document is
    validated with :meth:`NeutralMotion.validate_invariants` before return.

    Args:
        input_: A validated :class:`BlockingInput` document.

    Returns:
        A sparse :class:`NeutralMotion` satisfying the neutral-motion invariants.

    Raises:
        ValueError: If keyposes are out of order or contain duplicate frames, or
            the produced document fails its invariants.
    """
    keyposes_sorted = sorted(input_.keyposes, key=lambda kp: kp.frame)
    frames_numbers = [kp.frame for kp in keyposes_sorted]
    if len(frames_numbers) != len(set(frames_numbers)):
        raise ValueError("keypose frames must be unique (no duplicates)")

    skeleton = input_.resolved_skeleton()
    duration = max(frames_numbers)
    frames: list[Frame] = []
    for kp in keyposes_sorted:
        frames.append(
            Frame(
                frame=kp.frame,
                time=kp.frame / DEFAULT_BLOCKING_FPS,
                pose=Pose(transforms=kp.pose),
                confidence=None,
            )
        )

    keyposes = [KeyPose(frame=kp.frame, weight=kp.weight) for kp in keyposes_sorted]

    motion = NeutralMotion(
        meta=NeutralMeta(
            fps=DEFAULT_BLOCKING_FPS, source_type="blocking", duration_frames=duration
        ),
        skeleton=skeleton,
        frames=frames,
        keyposes=keyposes,
    )
    motion.validate_invariants()
    return motion
