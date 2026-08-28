"""Pose-2D node: 2D pose estimation from video frames."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
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
from aimation_actor_core.infrastructure.ai_models.estimators import (
    OnnxBackend,
    PoseEstimator,
    SyntheticBackend,
)

logger = logging.getLogger(__name__)


class Pose2DNode(INode):
    """2D pose estimation node.

    Consumes FRAMES and produces KEYPOINTS_2D using a swappable backend.
    Defaults to SyntheticBackend for deterministic testing; can use OnnxBackend
    for real pose estimation when a model is available.
    """

    def __init__(self, model_dir: Path = Path("models")) -> None:
        """Initialize pose-2D node.

        Args:
            model_dir: Directory containing ONNX model files.
        """
        self.model_dir = model_dir

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="pose-2d",
            category=NodeCategory.AI,
            title="Pose 2D",
            description="Estimate 2D keypoints from video frames",
            inputs=[PortSpec(name="frames", data_type=DataType.FRAMES)],
            outputs=[PortSpec(name="keypoints", data_type=DataType.KEYPOINTS_2D)],
            params=[
                PortSpec(
                    name="model",
                    data_type=DataType.STRING,
                    required=False,
                    default="synthetic",
                    description="Backend model: 'synthetic' or 'onnx'",
                ),
                PortSpec(
                    name="confidence",
                    data_type=DataType.NUMBER,
                    required=False,
                    default=0.0,
                    description="Confidence threshold for keypoints [0, 1]",
                ),
            ],
        )

    def _build_backend(self, model: str) -> PoseEstimator:
        """Build the appropriate backend based on model name.

        Args:
            model: Backend identifier ('synthetic' or 'onnx').

        Returns:
            PoseEstimator instance.
        """
        if model == "synthetic":
            return SyntheticBackend()
        elif model == "onnx":
            # For now, use a dummy path; in production this would be configured
            model_path = self.model_dir / "rtmpose.onnx"
            return OnnxBackend(model_path=model_path)
        else:
            # Unknown model, fall back to synthetic with warning
            logger.warning(f"Unknown model '{model}', falling back to synthetic backend")
            return SyntheticBackend()

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute pose estimation.

        Args:
            inputs: Input frames (list of numpy arrays).
            params: Parameters (model, confidence).
            context: Execution context.

        Returns:
            NodeOutput with keypoints.
        """
        frames = inputs["frames"]
        model = params.get("model", "synthetic")
        confidence_threshold = float(params.get("confidence", 0.0))

        # Build backend
        backend = self._build_backend(model)

        # Run inference in thread pool (offload from event loop)
        keypoints_list: list[Keypoints2D] = await asyncio.to_thread(backend.estimate, frames)

        # Filter by confidence threshold
        if confidence_threshold > 0.0:
            filtered_keypoints = []
            for kp2d in keypoints_list:
                filtered_kps = [
                    kp for kp in kp2d.keypoints if kp.confidence >= confidence_threshold
                ]
                filtered_keypoints.append(
                    Keypoints2D(frame_index=kp2d.frame_index, keypoints=filtered_kps)
                )
            keypoints_list = filtered_keypoints

        return NodeOutput(values={"keypoints": keypoints_list})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters.

        Args:
            params: Parameters to validate.

        Returns:
            ValidationResult.
        """
        # All params are optional, so validation always passes
        return ValidationResult(valid=True)
