"""Pose-3D node: 3D pose lifting from 2D keypoints (REQ-3)."""

import asyncio
import logging
from typing import Any

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
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
from aimation_actor_core.infrastructure.ai_models.lifters import (
    HeuristicLiftingBackend,
    LiftingBackend,
    OnnxLiftingBackend,
    SyntheticLiftingBackend,
)

logger = logging.getLogger(__name__)


class Pose3DNode(INode):
    """3D pose lifting node.

    Consumes KEYPOINTS_2D and produces POSE_3D using a swappable
    :class:`LiftingBackend`. Defaults to the deterministic
    :class:`SyntheticLiftingBackend`; ``heuristic`` adds anthropometric depth;
    ``onnx`` is a lazy placeholder seam. Unknown model values fall back to the
    synthetic backend (spec REQ-3). Offloads lifting to a worker thread via
    ``asyncio.to_thread`` (design D1), then applies the output-only confidence
    filter (design D5).
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="pose-3d",
            category=NodeCategory.AI,
            title="Pose 3D",
            description="Lift 2D keypoints into normalized 3D poses",
            inputs=[PortSpec(name="keypoints", data_type=DataType.KEYPOINTS_2D)],
            outputs=[PortSpec(name="keypoints_3d", data_type=DataType.POSE_3D)],
            params=[
                PortSpec(
                    name="model",
                    data_type=DataType.STRING,
                    required=False,
                    default="synthetic",
                    description="Backend model: 'synthetic', 'heuristic' or 'onnx'",
                ),
                PortSpec(
                    name="depth_mode",
                    data_type=DataType.STRING,
                    required=False,
                    default="proportional",
                    description="Depth deviation mode: 'proportional' or 'flat'",
                ),
                PortSpec(
                    name="confidence",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=0.0,
                    description="Confidence threshold for output keypoints [0, 1]",
                ),
            ],
        )

    @staticmethod
    def _build_backend(model: str, depth_mode: str) -> LiftingBackend:
        """Build the appropriate backend based on model and depth_mode.

        Args:
            model: Backend identifier ('synthetic', 'heuristic' or 'onnx').
            depth_mode: Depth deviation mode passed to the lifting backend.

        Returns:
            A :class:`LiftingBackend` instance; unknown models fall back to
            the synthetic backend with a warning (never crash).
        """
        if model == "heuristic":
            return HeuristicLiftingBackend(depth_mode=depth_mode)
        if model == "onnx":
            return OnnxLiftingBackend()
        if model != "synthetic":
            logger.warning(f"Unknown model '{model}', falling back to synthetic backend")
        return SyntheticLiftingBackend(depth_mode=depth_mode)

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute 3D pose lifting.

        Args:
            inputs: Input keypoints (list of :class:`Keypoints2D` or raw
                dicts as they arrive from the job-store serialized path).
            params: Parameters (model, depth_mode, confidence).
            context: Execution context.

        Returns:
            NodeOutput with keypoints_3d.
        """
        del context  # unused; kept for the INode contract
        raw_keypoints = inputs["keypoints"]
        model = params.get("model", "synthetic")
        depth_mode = params.get("depth_mode", "proportional")
        confidence_threshold = float(params.get("confidence", 0.0))

        # Coerce the job-store serialized path: dicts -> Keypoints2D.
        keypoints_2d: list[Keypoints2D] = [
            item if isinstance(item, Keypoints2D) else Keypoints2D.model_validate(item)
            for item in raw_keypoints
        ]

        backend = self._build_backend(model, depth_mode)

        # Run lifting off the event loop (design D1).
        lifted: list[Keypoints3D] = await asyncio.to_thread(backend.lift, keypoints_2d)

        # Output-only confidence filter (design D5): geometry preserved.
        if confidence_threshold > 0.0:
            filtered = [
                Keypoints3D(
                    frame_index=seq.frame_index,
                    keypoints=[kp for kp in seq.keypoints if kp.confidence >= confidence_threshold],
                )
                for seq in lifted
            ]
            lifted = filtered

        return NodeOutput(values={"keypoints_3d": lifted})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters (mirrors finalized pose-2d contract).

        The ``model`` and ``depth_mode`` params, when provided, must be
        non-empty strings. Unknown model/depth_mode *values* are accepted here
        because ``execute()`` degrades safely (spec REQ-3).
        """
        for param_name in ("model", "depth_mode"):
            if param_name in params:
                value = params[param_name]
                if not isinstance(value, str) or not value.strip():
                    return ValidationResult(
                        valid=False,
                        errors=[f"{param_name} must be a non-empty string when provided"],
                    )
        return ValidationResult(valid=True)
