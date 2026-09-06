"""Temporal cleanup node: ``NEUTRAL_ANIMATION → NEUTRAL_ANIMATION`` (REQ §12.4).

A deterministic :class:`TemporalCleanupNode` that consumes a
:class:`NeutralMotion` (local coordinate space, as emitted by
``VideoToMotionNode`` in ``only_local`` mode) and applies the five-stage
cleanup chain from :mod:`domain.animation.cleanup`:

    one-euro smoothing → contact detection → foot locking →
    ground clamping → root normalization

Following the ``VideoToMotionNode`` adapter pattern, this node owns no math of
its own — it only adapts the :class:`INode` contract to :func:`cleanup_motion`:
dict coercion for the serialized job-store path, ``asyncio.to_thread`` offload
(design D7), and param validation. Runtime is pure in-memory math, so no model
probe / ``/health`` key is added.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aimation_actor_core.domain.animation.cleanup import (
    DEFAULT_BETA,
    DEFAULT_HEIGHT_THRESHOLD,
    DEFAULT_HYSTERESIS_FRAMES,
    DEFAULT_MIN_CUTOFF,
    DEFAULT_VELOCITY_THRESHOLD,
    CleanupParams,
    cleanup_motion,
)
from aimation_actor_core.domain.animation.neutral_motion import migrate_neutral_motion
from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    INode,
    NodeOutput,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.schema import (
    DataType,
    NodeCategory,
    NodeSchema,
    PortSpec,
)

#: Numeric threshold params validated to be positive numbers when provided.
_NUMERIC_PARAMS = (
    ("min_cutoff", "min_cutoff"),
    ("beta", "beta"),
    ("velocity_threshold", "velocity_threshold"),
    ("height_threshold", "height_threshold"),
)


class TemporalCleanupNode(INode):
    """Applies deterministic temporal cleanup to a neutral motion.

    Stateless at the contract level; all per-run tuning lives in the ``params``
    passed to :meth:`execute`. The blocking math runs off the asyncio loop via
    :func:`asyncio.to_thread`.
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="temporal-cleanup",
            category=NodeCategory.CLEANUP,
            title="Temporal Cleanup",
            description=(
                "Smooth jitter, detect contacts, lock feet, clamp ground, and normalize root"
            ),
            inputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            outputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            params=[
                PortSpec(
                    name="min_cutoff",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_MIN_CUTOFF,
                    description="One-Euro minimum cutoff frequency (Hz)",
                ),
                PortSpec(
                    name="beta",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_BETA,
                    description="One-Euro speed coefficient",
                ),
                PortSpec(
                    name="velocity_threshold",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_VELOCITY_THRESHOLD,
                    description="cm/frame below which a foot may be in contact",
                ),
                PortSpec(
                    name="height_threshold",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_HEIGHT_THRESHOLD,
                    description="cm above the floor within which a foot is near-contact",
                ),
                PortSpec(
                    name="hysteresis_frames",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_HYSTERESIS_FRAMES,
                    description="Minimum frames to hold a contact once entered",
                ),
            ],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute the temporal cleanup chain.

        Args:
            inputs: Input ``motion`` (a :class:`NeutralMotion` or raw serialized
                dict from the job-store path; migrated on read per ADR-001).
            params: Tuning params (all optional; defaults applied).
            context: Execution context.

        Returns:
            NodeOutput with the cleaned :class:`NeutralMotion` under ``motion``.
        """
        del context  # unused; kept for the INode contract
        motion = migrate_neutral_motion(inputs["motion"])
        cleanup_params = CleanupParams(
            min_cutoff=float(params.get("min_cutoff", DEFAULT_MIN_CUTOFF)),
            beta=float(params.get("beta", DEFAULT_BETA)),
            velocity_threshold=float(params.get("velocity_threshold", DEFAULT_VELOCITY_THRESHOLD)),
            height_threshold=float(params.get("height_threshold", DEFAULT_HEIGHT_THRESHOLD)),
            hysteresis_frames=int(params.get("hysteresis_frames", DEFAULT_HYSTERESIS_FRAMES)),
        )

        # Run the cleanup math off the event loop (design D7).
        result = await asyncio.to_thread(cleanup_motion, motion, cleanup_params)
        return NodeOutput(values={"motion": result})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters (design D6).

        Numeric thresholds (``min_cutoff``, ``beta``, ``velocity_threshold``,
        ``height_threshold``) — when provided — must be positive numbers
        (booleans and non-numeric values are rejected). ``hysteresis_frames`` —
        when provided — must be a positive integer. All params are optional.
        """
        errors: list[str] = []
        for key, _label in _NUMERIC_PARAMS:
            if key in params and params[key] is not None:
                value = params[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(f"{key} must be a number when provided")
                elif value <= 0:
                    errors.append(f"{key} must be greater than 0")
        if "hysteresis_frames" in params and params["hysteresis_frames"] is not None:
            value = params["hysteresis_frames"]
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append("hysteresis_frames must be an integer when provided")
            elif value <= 0:
                errors.append("hysteresis_frames must be greater than 0")
        return ValidationResult(valid=not errors, errors=errors)
