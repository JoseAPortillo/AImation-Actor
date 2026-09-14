"""Single-frame pose detection contracts (frame-pose-detection capability).

``SingleFramePose`` is the synchronous single-frame detection result: a list
of ``Keypoint`` (reusing the existing ``domain.animation.keypoints`` model)
plus a frame-level confidence. ``SingleFramePoseDetector`` is the
framework-free boundary implemented in ``infrastructure`` and injected via
``app.state`` (decision D1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from aimation_actor_core.domain.animation.keypoints import Keypoint


class SingleFramePose(BaseModel):
    """Detected 2D pose for a single frame, with frame-level confidence."""

    model_config = {"frozen": True}

    keypoints: list[Keypoint] = Field(..., description="Detected keypoints")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Frame-level confidence [0, 1]")


@runtime_checkable
class SingleFramePoseDetector(Protocol):
    """Detects the 2D pose of a single video frame (1-based index)."""

    async def detect(self, video_path: str, frame_index: int) -> SingleFramePose:
        """Detect the pose of one frame.

        Args:
            video_path: Media reference relative to ``media_root``, resolved
                through the shared allowlist before any file is opened (D3).
            frame_index: 1-based frame index; the first frame is ``1``.

        Returns:
            The detected keypoints plus a frame-level confidence in [0, 1].
        """
        ...