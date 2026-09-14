"""Framework-free media domain contracts (SDD §2.3).

``FrameProvider`` is the boundary the API layer uses to serve video frames;
implementations live in ``infrastructure`` and are injected via ``app.state``
(decision D1/D3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FrameProvider(Protocol):
    """Serves JPEG frames from videos under the media-root allowlist.

    Implementations MUST resolve every ``video_path`` through the shared
    ``resolve_media_path`` allowlist before opening the file (decision D3).

    Frame indices are **1-based** at this boundary: ``frame_index=1`` is the
    first frame of the video. Implementations MUST convert to the 0-based
    ``cv2`` frame index before decoding (interface-boundary conversion).
    """

    async def get_frame_jpeg(
        self, video_path: str, frame_index: int, width: int | None = None
    ) -> tuple[bytes, int]:
        """Return the requested frame as JPEG plus the video's frame count.

        Args:
            video_path: Media reference relative to ``media_root``.
            frame_index: 1-based frame index; the first frame is ``1``.
            width: Optional resize width; ``None`` keeps the original size.

        Returns:
            ``(jpeg_bytes, frame_count)``; ``frame_count`` is the total
            number of frames in the video.
        """
        ...

    async def get_frame_count(self, video_path: str) -> int:
        """Return the total frame count of a video under ``media_root``.

        Args:
            video_path: Media reference relative to ``media_root``.

        Returns:
            Total number of frames in the video.
        """
        ...
