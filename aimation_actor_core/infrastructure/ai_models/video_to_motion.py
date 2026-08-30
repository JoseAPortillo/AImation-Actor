"""Video-to-motion node: terminal converter (REQ-2).

A deterministic, backend-less :class:`VideoToMotionNode` that consumes
``keypoints_3d: POSE_3D`` and emits ``motion: NEUTRAL_ANIMATION``. There is
no backend/model to probe, so no ``/health`` key is added (proposal). The
actual math (mapping, scale, abs→local, frame assembly) lives in
:mod:`motion_conversion`; this node only adapts the ``INode`` contract to it
(dict coercion for the serialized path, ``asyncio.to_thread`` offload, and
safe handling of empty input / missing labels).
"""

from __future__ import annotations

import asyncio
from typing import Any

from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D
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
from aimation_actor_core.infrastructure.ai_models.motion_conversion import (
    DEFAULT_PERSON_HEIGHT_CM,
    convert_keypoints_to_motion,
)


class VideoToMotionNode(INode):
    """Terminal ``POSE_3D → NEUTRAL_ANIMATION`` converter node.

    Deterministic and backend-less. Raw ``Keypoints3D`` dicts (the job-store
    serialized path) are coerced to :class:`Keypoints3D` before conversion.
    Missing or invalid labels skip the affected bone (never fail), and empty
    input yields an empty ``NeutralMotion`` that still carries the default
    skeleton. Conversion is offloaded to a worker thread via
    ``asyncio.to_thread`` (design D7).
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="video-to-motion",
            category=NodeCategory.OUTPUT,
            title="Video to Motion",
            description="Convert normalized 3D keypoints into a neutral motion",
            inputs=[PortSpec(name="keypoints_3d", data_type=DataType.POSE_3D)],
            outputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            params=[
                PortSpec(
                    name="person_height_cm",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=DEFAULT_PERSON_HEIGHT_CM,
                    description="Person height used to upscale normalized keypoints (cm)",
                ),
                PortSpec(
                    name="only_local",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    default=True,
                    description="Whether to derive local (child-parent) offsets",
                ),
            ],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute the terminal conversion.

        Args:
            inputs: Input 3D keypoints (list of :class:`Keypoints3D` or raw
                dicts as they arrive from the job-store serialized path).
            params: Parameters (person_height_cm, only_local).
            context: Execution context.

        Returns:
            NodeOutput with a :class:`NeutralMotion` under ``motion``.
        """
        del context  # unused; kept for the INode contract
        raw_keypoints = inputs["keypoints_3d"]
        person_height_cm = params.get("person_height_cm", DEFAULT_PERSON_HEIGHT_CM)
        only_local = params.get("only_local", True)

        # Coerce the job-store serialized path: dicts -> Keypoints3D.
        keypoints_3d: list[Keypoints3D] = [
            item if isinstance(item, Keypoints3D) else Keypoints3D.model_validate(item)
            for item in raw_keypoints
        ]

        # Run the conversion off the event loop (design D7).
        motion = await asyncio.to_thread(
            convert_keypoints_to_motion,
            keypoints_3d,
            person_height_cm=person_height_cm,
            only_local=only_local,
        )
        return NodeOutput(values={"motion": motion})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters (design D6).

        ``person_height_cm`` — when provided — must be a positive number
        (booleans and non-numeric values are rejected). ``only_local`` — when
        provided — must be a boolean. Both are optional.
        """
        errors: list[str] = []
        if "person_height_cm" in params and params["person_height_cm"] is not None:
            value = params["person_height_cm"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append("person_height_cm must be a number when provided")
            elif value <= 0:
                errors.append("person_height_cm must be greater than 0")
        if "only_local" in params and params["only_local"] is not None:
            if not isinstance(params["only_local"], bool):
                errors.append("only_local must be a boolean when provided")
        return ValidationResult(valid=not errors, errors=errors)
