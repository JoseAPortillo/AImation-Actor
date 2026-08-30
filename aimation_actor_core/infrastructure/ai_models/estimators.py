"""Pose estimator backends for pose-2d node."""

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D


@runtime_checkable
class PoseEstimator(Protocol):
    """Protocol for pose estimation backends."""

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Estimate 2D keypoints for each frame.

        Args:
            frames: List of video frames as numpy arrays (BGR format).

        Returns:
            List of Keypoints2D, one per input frame.
        """
        ...


class SyntheticBackend:
    """Deterministic synthetic backend for testing and CI.

    Produces fixed, scripted keypoints regardless of input frames.
    Useful for deterministic graph e2e tests.
    """

    # Standard COCO-style keypoints (17 points)
    KEYPOINT_LABELS = [
        "nose",
        "left_eye",
        "right_eye",
        "left_ear",
        "right_ear",
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    ]

    # Fixed normalized coordinates for a standing person (centered)
    FIXED_KEYPOINTS = [
        (0.50, 0.20),  # nose
        (0.48, 0.18),  # left_eye
        (0.52, 0.18),  # right_eye
        (0.45, 0.20),  # left_ear
        (0.55, 0.20),  # right_ear
        (0.40, 0.35),  # left_shoulder
        (0.60, 0.35),  # right_shoulder
        (0.35, 0.50),  # left_elbow
        (0.65, 0.50),  # right_elbow
        (0.30, 0.65),  # left_wrist
        (0.70, 0.65),  # right_wrist
        (0.45, 0.60),  # left_hip
        (0.55, 0.60),  # right_hip
        (0.45, 0.75),  # left_knee
        (0.55, 0.75),  # right_knee
        (0.45, 0.90),  # left_ankle
        (0.55, 0.90),  # right_ankle
    ]

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Generate deterministic keypoints for each frame.

        Args:
            frames: List of video frames (ignored, output is fixed).

        Returns:
            List of Keypoints2D with fixed keypoints, one per frame.
        """
        result = []
        for frame_idx in range(len(frames)):
            keypoints = [
                Keypoint(
                    label=label,
                    x=x,
                    y=y,
                    confidence=0.95,  # High confidence for synthetic data
                )
                for (label, (x, y)) in zip(self.KEYPOINT_LABELS, self.FIXED_KEYPOINTS, strict=True)
            ]
            result.append(Keypoints2D(frame_index=frame_idx, keypoints=keypoints))
        return result


class OnnxBackend:
    """ONNX Runtime backend for real pose estimation.

    Uses lazy import of onnxruntime so the module can be imported even if
    onnxruntime is not installed. The import happens only when estimate() is called.
    """

    def __init__(self, model_path: str | Path) -> None:
        """Initialize ONNX backend with model path.

        Args:
            model_path: Path to the ONNX model file.
        """
        self.model_path = Path(model_path)

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Estimate 2D keypoints using ONNX Runtime.

        Args:
            frames: List of video frames as numpy arrays (BGR format).

        Returns:
            List of Keypoints2D, one per input frame.

        Raises:
            ImportError: If onnxruntime is not installed.
            NotImplementedError: If model loading/inference is not yet implemented.
        """
        # Lazy import of onnxruntime
        try:
            import onnxruntime  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "onnxruntime is required for OnnxBackend but is not installed. "
                "Install it with: pip install onnxruntime"
            ) from e

        # TODO: Implement actual ONNX inference
        # For now, raise NotImplementedError as we don't have a real model yet
        raise NotImplementedError(
            f"ONNX inference not yet implemented. Model path: {self.model_path}"
        )
