"""Pose detection endpoint (SDD Phase A, frame-pose-detection).

``GET /detect/{video_path}/{frame_index}`` performs synchronous single-frame
pose detection. Blocking decode + inference runs off the event loop via
``asyncio.to_thread`` (decision D1). The synthetic backend makes detection
instant under test.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from aimation_actor_core.api.deps import get_pose_detector, require_token
from aimation_actor_core.domain.animation.pose_detection import SingleFramePoseDetector
from aimation_actor_core.shared.media_security import MediaPathError

router = APIRouter(tags=["pose"], dependencies=[Depends(require_token)])


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
        )
    except MediaPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return result.model_dump()
