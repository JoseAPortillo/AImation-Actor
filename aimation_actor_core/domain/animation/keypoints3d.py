"""Domain value objects for 3D keypoints (pose-3d output).

``z`` is normalized depth in ``[0, 1]`` where ``0.5`` is the camera plane:
closer objects have smaller ``z``, farther objects have larger ``z`` (design
D2). Scene-unit conversion happens downstream at the NeutralMotion boundary.
"""

from pydantic import BaseModel, Field


class Keypoint3D(BaseModel):
    """Single 3D keypoint with normalized coordinates and confidence."""

    model_config = {"frozen": True}

    label: str = Field(..., description="Keypoint label (e.g., 'nose', 'left_eye')")
    x: float = Field(..., ge=0.0, le=1.0, description="Normalized x coordinate [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized y coordinate [0, 1]")
    z: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Normalized depth [0, 1]; 0.5 = camera plane (closer -> smaller, farther -> larger)"
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence [0, 1]")
    visible: bool = True  # per-joint occlusion flag


class Keypoints3D(BaseModel):
    """Collection of 3D keypoints for a single frame."""

    model_config = {"frozen": True}

    frame_index: int = Field(..., ge=0, description="Frame index (>= 0)")
    keypoints: list[Keypoint3D] = Field(default_factory=list, description="List of 3D keypoints")
