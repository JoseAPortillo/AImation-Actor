"""OpenCV frame provider implementation (SDD Phase A, decision D1).

Implements the ``FrameProvider`` protocol: resolves video paths through the
shared media-root allowlist, decodes single frames off the event loop via
``asyncio.to_thread``, and returns JPEG bytes plus the video's total frame
count. Frame indices are **1-based** at this boundary; conversion to 0-based
cv2 indexing happens inside the blocking decode helper.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aimation_actor_core.domain.media.frame_provider import FrameProvider
from aimation_actor_core.shared.media_security import MediaPathError, resolve_media_path


class FrameIndexOutOfRange(MediaPathError):
    """Raised when the requested 1-based frame index is outside the video."""

    code = "frame_index_out_of_range"


class FrameProviderError(MediaPathError):
    """Raised when the video cannot be opened or decoded."""

    code = "frame_provider_error"


class OpenCvFrameProvider:
    """Serves JPEG frames from videos under the media-root allowlist.

    All blocking cv2 work runs via ``asyncio.to_thread`` so the event loop
    stays responsive (decision D1). Frame indices are **1-based** at this
    boundary: ``frame_index=1`` is the first frame; conversion to 0-based cv2
    indexing happens inside ``_decode_frame_blocking``.
    """

    def __init__(self, media_root: Path) -> None:
        self._media_root = media_root

    async def get_frame_jpeg(
        self, video_path: str, frame_index: int, width: int | None = None
    ) -> tuple[bytes, int]:
        """Return the requested frame as JPEG plus the video's frame count.

        Args:
            video_path: Media reference relative to ``media_root``.
            frame_index: 1-based frame index; the first frame is ``1``.
            width: Optional resize width; ``None`` keeps the original size.

        Returns:
            ``(jpeg_bytes, frame_count)``.

        Raises:
            MediaPathError: If the video path violates the allowlist.
            FrameIndexOutOfRange: If the frame index is outside the video.
            FrameProviderError: If the video cannot be opened or decoded.
        """
        resolved = self._resolve(video_path)
        jpeg_bytes, frame_count = await asyncio.to_thread(
            _decode_frame_blocking, resolved, frame_index, width
        )
        return jpeg_bytes, frame_count

    async def get_frame_count(self, video_path: str) -> int:
        """Return the total frame count of a video under ``media_root``.

        Args:
            video_path: Media reference relative to ``media_root``.

        Returns:
            Total number of frames in the video.
        """
        resolved = self._resolve(video_path)
        count = await asyncio.to_thread(_get_frame_count_blocking, resolved)
        return count

    def _resolve(self, video_path: str) -> Path:
        """Resolve ``video_path`` through the shared allowlist (D3)."""
        try:
            return resolve_media_path(self._media_root, video_path)
        except MediaPathError as exc:
            raise FrameProviderError(str(exc)) from exc


def _get_frame_count_blocking(path: Path) -> int:
    """Return the total frame count (runs off the event loop)."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise FrameProviderError(f"could not open video: {path.name}")
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count <= 0:
            raise FrameProviderError(f"video has no frames: {path.name}")
        return count
    finally:
        cap.release()


def _decode_frame_blocking(
    path: Path, frame_index: int, width: int | None
) -> tuple[bytes, int]:
    """Decode a single frame as JPEG (runs off the event loop).

    ``frame_index`` is **1-based**; conversion to 0-based cv2 indexing
    happens here: ``cv2_index = frame_index - 1``.
    """
    import cv2

    if frame_index < 1:
        raise FrameIndexOutOfRange(
            f"frame_index must be >= 1 (got {frame_index})"
        )

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise FrameProviderError(f"could not open video: {path.name}")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count <= 0:
            raise FrameProviderError(f"video has no frames: {path.name}")

        # 1-based → 0-based for cv2
        cv2_index = frame_index - 1
        if cv2_index >= frame_count:
            raise FrameIndexOutOfRange(
                f"frame_index {frame_index} exceeds video length {frame_count}"
            )

        cap.set(cv2.CAP_PROP_POS_FRAMES, cv2_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise FrameProviderError(
                f"failed to read frame {frame_index} from {path.name}"
            )

        if width is not None and width > 0:
            h, w = frame.shape[:2]
            aspect = w / h
            new_h = int(width / aspect)
            frame = cv2.resize(frame, (width, new_h))

        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise FrameProviderError(
                f"failed to encode frame {frame_index} as JPEG"
            )

        return buf.tobytes(), frame_count
    finally:
        cap.release()
