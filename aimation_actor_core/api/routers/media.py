"""Media endpoints: frame serving and video upload (SDD Phase A).

``GET /media/frame`` serves a single JPEG frame from a video, with
``X-Frame-Count`` in the response header for the frontend timeslider.
``POST /media/upload`` accepts a multipart video file and stores it under
the media-root allowlist. Both endpoints require Bearer token auth.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from aimation_actor_core.api.deps import get_frame_provider, get_settings, require_token
from aimation_actor_core.domain.media.frame_provider import FrameProvider
from aimation_actor_core.shared.config import Settings
from aimation_actor_core.shared.media_security import MediaPathError, resolve_media_path

router = APIRouter(
    prefix="/media", tags=["media"], dependencies=[Depends(require_token)]
)


@router.get("/frame", summary="Get a single video frame as JPEG")
async def get_frame(
    video_path: str,
    frame_index: int,
    width: int | None = None,
    provider: FrameProvider = Depends(get_frame_provider),
) -> Response:
    """Return a JPEG frame from a video.

    ``frame_index`` is **1-based**: ``1`` is the first frame. The response
    includes an ``X-Frame-Count`` header with the total number of frames
    in the video.
    """
    try:
        jpeg_bytes, frame_count = await provider.get_frame_jpeg(
            video_path, frame_index, width=width
        )
    except MediaPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"X-Frame-Count": str(frame_count)},
    )


@router.post("/upload", summary="Upload a video file")
async def upload_video(
    file: UploadFile,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Accept a multipart video upload and store it under ``media_root``.

    Files exceeding ``max_video_bytes`` are rejected with 413. The stored
    filename is ``{uuid4[:12]}_{original_basename}`` to avoid collisions.
    """
    content = await file.read()
    if len(content) > settings.max_video_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"file exceeds max size of {settings.max_video_bytes} bytes",
        )

    original_name = file.filename or "upload.bin"

    # Reject path separators and traversal in the original filename —
    # defensive before the shared allowlist boundary (D3).
    if any(c in original_name for c in ("/", "\\")) or ".." in original_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename contains path separators or traversal",
        )

    safe_name = f"{uuid.uuid4().hex[:12]}_{original_name}"

    # Validate the target path through the shared allowlist (D3) BEFORE
    # writing — rejects any remaining escape even when Starlette does not.
    try:
        resolve_media_path(settings.media_root, safe_name, must_exist=False)
    except MediaPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"disallowed filename: {exc}",
        ) from exc

    target = settings.media_root / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {"reference": safe_name}
