"""Pose endpoints: single-frame detection and bulk 2D→3D lifting (REQ-2).

``GET /detect/{video_path}/{frame_index}`` performs synchronous single-frame
pose detection. Blocking decode + inference runs off the event loop via
``asyncio.to_thread`` (decision D1). The synthetic backend makes detection
instant under test.

``POST /pose/lift`` lifts a batch of 2D keypoint frames with the injected
:class:`LiftingBackend`. ``z`` is a deterministic heuristic depth preview in
[0, 1] (0.5 = camera plane), NOT a real 3D reconstruction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from aimation_actor_core.api.deps import get_lifting_backend, get_pose_detector
from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.lifting import LiftingBackend
from aimation_actor_core.domain.animation.pose_detection import SingleFramePoseDetector
from aimation_actor_core.shared.media_security import MediaPathError

router = APIRouter(tags=["pose"])  # DEV: auth disabled for validation


class LiftKeypoint(BaseModel):
    """A single 2D keypoint supplied for 3D lifting."""

    label: str
    x: float = Field(..., ge=0.0, le=1.0, description="Normalized x coordinate [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized y coordinate [0, 1]")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence [0, 1]")


class LiftKeypoint3D(BaseModel):
    """A single lifted 3D keypoint (normalized geometry + confidence)."""

    label: str
    x: float = Field(..., ge=0.0, le=1.0, description="Normalized x coordinate [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized y coordinate [0, 1]")
    z: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized depth [0, 1]; 0.5 = camera plane",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence [0, 1]")


class LiftPose3DRequest(BaseModel):
    """Bulk 2D keypoint frames to lift into 3D (one inner list per frame)."""

    frames: list[list[LiftKeypoint]] = Field(default_factory=list)


class LiftPose3DResponse(BaseModel):
    """Per-frame lifted 3D keypoints, order and shape preserved."""

    frames: list[list[LiftKeypoint3D]] = Field(default_factory=list)


@router.get(
    "/detect/{video_path:path}/{frame_index}",
    response_model=dict,
    summary="Detect 2D pose for a single frame",
)
async def detect_pose(
    video_path: str,
    frame_index: int,
    detector: SingleFramePoseDetector = Depends(get_pose_detector),
) -> dict:
    """Detect the 2D pose of a single video frame.

    Returns named keypoints with normalized x/y and per-keypoint confidence,
    plus a frame-level confidence score.

    Raises 501 when the selected backend is unavailable (e.g. ONNX not yet
    wired in Phase C).
    """
    try:
        result = await detector.detect(video_path, frame_index)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc
    except MediaPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result.model_dump()


@router.post(
    "/pose/lift",
    response_model=LiftPose3DResponse,
    summary="Lift 2D keypoint frames into a deterministic 3D preview",
)
async def lift_pose_3d(
    request: LiftPose3DRequest,
    backend: LiftingBackend = Depends(get_lifting_backend),
) -> LiftPose3DResponse:
    """Lift every requested frame into normalized 3D keypoints.

    Each frame is lifted independently by the injected deterministic backend;
    ``z`` is a heuristic depth in [0, 1] (0.5 = camera plane), not a real 3D
    reconstruction. An empty ``frames`` list, or an empty inner frame, yields
    empty lists rather than an error.
    """
    frames_2d = [
        Keypoints2D(
            frame_index=index,
            keypoints=[
                Keypoint(label=kp.label, x=kp.x, y=kp.y, confidence=kp.confidence)
                for kp in frame
            ],
        )
        for index, frame in enumerate(request.frames)
    ]
    lifted = backend.lift(frames_2d)
    return LiftPose3DResponse(
        frames=[
            [
                LiftKeypoint3D(
                    label=kp.label,
                    x=kp.x,
                    y=kp.y,
                    z=kp.z,
                    confidence=kp.confidence,
                )
                for kp in sequence.keypoints
            ]
            for sequence in lifted
        ]
    )
