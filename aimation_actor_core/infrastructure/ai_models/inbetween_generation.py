"""In-between generation node: ``NEUTRAL_ANIMATION → NEUTRAL_ANIMATION`` (REQ §12.5).

A deterministic :class:`InbetweenGenerationNode` that consumes a
:class:`NeutralMotion` (as emitted by ``TemporalCleanupNode``) and applies the
enrichment chain from :mod:`domain.animation.inbetween`:

    resample (+easing) → rotation filter → tangent smoothing

Following the ``TemporalCleanupNode`` adapter pattern, this node owns no math
of its own — it only adapts the :class:`INode` contract to
:func:`enrich_motion`: dict coercion for the serialized job-store path,
``asyncio.to_thread`` offload, and param validation. Runtime is pure
in-memory math, so no model probe / ``/health`` key is added.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aimation_actor_core.domain.animation.inbetween import (
    DEFAULT_EASING,
    DEFAULT_EULER_FILTER,
    DEFAULT_INTERPOLATION_METHOD,
    DEFAULT_TANGENT_SMOOTHING,
    DEFAULT_TARGET_FPS,
    InbetweenParams,
    enrich_motion,
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


class InbetweenGenerationNode(INode):
    """Applies deterministic in-between generation/enrichment to a neutral motion.

    Stateless at the contract level; all per-run tuning lives in the ``params``
    passed to :meth:`execute`. The blocking math runs off the asyncio loop via
    :func:`asyncio.to_thread`.
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="inbetween-generation",
            category=NodeCategory.ENRICHMENT,
            title="In-Between Generation",
            description=("Resample, ease, filter rotation continuity, and smooth tangents"),
            inputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            outputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            params=[
                PortSpec(
                    name="interpolation_method",
                    data_type=DataType.STRING,
                    required=False,
                    default=DEFAULT_INTERPOLATION_METHOD,
                    description='"linear" or "cubic" interpolation',
                ),
                PortSpec(
                    name="target_fps",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_TARGET_FPS,
                    description="Target frame rate to upsample onto",
                ),
                PortSpec(
                    name="easing",
                    data_type=DataType.STRING,
                    required=False,
                    default=DEFAULT_EASING,
                    description='"none", "ease-in", "ease-out" or "ease-in-out"',
                ),
                PortSpec(
                    name="euler_filter",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    default=DEFAULT_EULER_FILTER,
                    description="Canonicalize rotation sign continuity",
                ),
                PortSpec(
                    name="tangent_smoothing",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_TANGENT_SMOOTHING,
                    description="Smoothing intensity in [0, 1]",
                ),
            ],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute the enrichment chain.

        Args:
            inputs: Input ``motion`` (a :class:`NeutralMotion` or raw serialized
                dict from the job-store path; migrated on read per ADR-001).
            params: Tuning params (all optional; defaults applied).
            context: Execution context.

        Returns:
            NodeOutput with the enriched :class:`NeutralMotion` under ``motion``.
        """
        del context  # unused; kept for the INode contract
        motion = migrate_neutral_motion(inputs["motion"])
        inbetween_params = InbetweenParams(
            interpolation_method=str(
                params.get("interpolation_method", DEFAULT_INTERPOLATION_METHOD)
            ),
            target_fps=float(params.get("target_fps", DEFAULT_TARGET_FPS)),
            easing=str(params.get("easing", DEFAULT_EASING)),
            euler_filter=bool(params.get("euler_filter", DEFAULT_EULER_FILTER)),
            tangent_smoothing=float(params.get("tangent_smoothing", DEFAULT_TANGENT_SMOOTHING)),
        )

        # Run the enrichment math off the event loop (design D7).
        result = await asyncio.to_thread(enrich_motion, motion, inbetween_params)
        return NodeOutput(values={"motion": result})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters (design D6).

        ``interpolation_method`` must be in {"linear","cubic"}, ``easing`` in
        {"none","ease-in","ease-out","ease-in-out"}, ``euler_filter`` must be a
        bool, ``tangent_smoothing`` must be a number in [0,1], and
        ``target_fps`` must be a positive number. Invalid enum/range/fps/bool
        values are rejected before execution. All params are optional.
        """
        errors: list[str] = []
        if "interpolation_method" in params and params["interpolation_method"] is not None:
            if params["interpolation_method"] not in ("linear", "cubic"):
                errors.append(
                    "interpolation_method must be one of linear, cubic, "
                    f"got {params['interpolation_method']!r}"
                )
        if "easing" in params and params["easing"] is not None:
            if params["easing"] not in ("none", "ease-in", "ease-out", "ease-in-out"):
                errors.append(
                    "easing must be one of none, ease-in, ease-out, ease-in-out, "
                    f"got {params['easing']!r}"
                )
        if "euler_filter" in params and params["euler_filter"] is not None:
            if not isinstance(params["euler_filter"], bool):
                errors.append("euler_filter must be a boolean")
        for key in ("tangent_smoothing", "target_fps"):
            if key in params and params[key] is not None:
                value = params[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(f"{key} must be a number when provided")
                elif key == "tangent_smoothing" and not 0.0 <= value <= 1.0:
                    errors.append("tangent_smoothing must be in [0, 1]")
                elif key == "target_fps" and value <= 0:
                    errors.append("target_fps must be greater than 0")
        return ValidationResult(valid=not errors, errors=errors)
