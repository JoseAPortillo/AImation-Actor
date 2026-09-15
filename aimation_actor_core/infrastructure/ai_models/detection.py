"""Single-frame pose detector implementation (SDD Phase A, frame-pose-detection).

Wraps a ``PoseEstimator`` backend to serve the ``SingleFramePoseDetector``
domain protocol. The blocking cv2 decode + ``estimate_single`` call runs
entirely off the event loop via ``asyncio.to_thread`` (decision D1).

When the selected backend raises ``NotImplementedError`` (e.g. the ONNX
backend in Phase C), the detector re-raises it as
``PoseDetectionUnavailableError`` so the API layer can map it to HTTP 501.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from aimation_actor_core.domain.animation.pose_detection import SingleFramePose
from aimation_actor_core.infrastructure.ai_models.estimators import PoseEstimator
from aimation_actor_core.shared.media_security import MediaPathError, resolve_media_path


class PoseDetectionUnavailableError(MediaPathError):
    """Raised when the selected pose backend cannot perform detection."""

    code = "pose_detection_unavailable"


class DetectionError(MediaPathError):
    """Raised when detection fails for any other reason."""

    code = "detection_error"


class SingleFramePoseDetectorImpl:
    """Detects the 2D pose of a single video frame.

    Uses the injected ``PoseEstimator`` backend. All blocking work (cv2
    decode + inference) runs off the event loop via ``asyncio.to_thread``
    (decision D1). The synthetic backend makes detection instant under test.
    """

    def __init__(self, media_root: Path, backend: PoseEstimator) -> None:
        self._media_root = media_root
        self._backend = backend

    async def detect(self, video_path: str, frame_index: int) -> SingleFramePose:
        """Detect the pose of one frame.

        Args:
            video_path: Media reference relative to ``media_root``.
            frame_index: 1-based frame index; the first frame is ``1``.

        Returns:
            The detected keypoints plus a frame-level confidence in [0, 1].

        Raises:
            MediaPathError: If the video path violates the allowlist.
            PoseDetectionUnavailableError: If the backend cannot perform detection.
            DetectionError: If decode or detection fails for other reasons.
        """
        resolved = self._resolve(video_path)
        try:
            return await asyncio.to_thread(
                _detect_blocking, resolved, frame_index, self._backend
            )
        except NotImplementedError as exc:
            raise PoseDetectionUnavailableError(str(exc)) from exc

    def _resolve(self, video_path: str) -> Path:
        """Resolve ``video_path`` through the shared allowlist (D3)."""
        try:
            return resolve_media_path(self._media_root, video_path)
        except MediaPathError as exc:
            raise DetectionError(str(exc)) from exc


def _decode_frame(path: Path, frame_index: int) -> np.ndarray:
    """Decode a single frame as a numpy BGR array (runs off the event loop).

    ``frame_index`` is **1-based**; conversion to 0-based cv2 indexing
    happens here: ``cv2_index = frame_index - 1``.
    """
    import cv2  # noqa: F811 — local import to keep cv2 off module level

    if frame_index < 1:
        raise DetectionError(f"frame_index must be >= 1 (got {frame_index})")

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise DetectionError(f"could not open video: {path.name}")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cv2_index = frame_index - 1
        if cv2_index >= frame_count:
            raise DetectionError(
                f"frame_index {frame_index} exceeds video length {frame_count}"
            )

        cap.set(cv2.CAP_PROP_POS_FRAMES, cv2_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise DetectionError(
                f"failed to read frame {frame_index} from {path.name}"
            )
        return frame
    finally:
        cap.release()


def _detect_blocking(
    path: Path, frame_index: int, backend: PoseEstimator
) -> SingleFramePose:
    """Synchronous decode + estimate (runs off the event loop)."""
    frame = _decode_frame(path, frame_index)
    return backend.estimate_single(frame)
