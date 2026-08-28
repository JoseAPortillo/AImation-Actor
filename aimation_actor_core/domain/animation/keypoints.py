"""Domain value objects for 2D keypoints (pose-2d output)."""

from pydantic import BaseModel, Field


class Keypoint(BaseModel):
    """Single 2D keypoint with normalized coordinates and confidence."""

    model_config = {"frozen": True}

    label: str = Field(..., description="Keypoint label (e.g., 'nose', 'left_eye')")
    x: float = Field(..., ge=0.0, le=1.0, description="Normalized x coordinate [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized y coordinate [0, 1]")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence [0, 1]")


class Keypoints2D(BaseModel):
    """Collection of 2D keypoints for a single frame."""

    model_config = {"frozen": True}

    frame_index: int = Field(..., ge=0, description="Frame index (>= 0)")
    keypoints: list[Keypoint] = Field(default_factory=list, description="List of keypoints")
