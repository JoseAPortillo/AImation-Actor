"""Real AI-pipeline node: OpenCV frame extraction (plan §12, ai-processors).

``FrameExtractorNode`` (type ``video-source``) is the first genuine
AI-pipeline stage. It decodes a video file into a list of frames and reports
the source FPS. It conforms to the :class:`INode` contract and runs through
the unchanged :class:`SynchronousGraphExecutor`.

Security (SDD §4.3): ``video_path`` is a user-supplied param. It is validated
against an allowlisted media root *before* any ``cv2.VideoCapture`` opens the
file — no arbitrary filesystem paths, no external-code execution, strict
path-string handling. The blocking decode is offloaded from the asyncio event
loop via :func:`asyncio.to_thread` (decision D1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    INode,
    NodeOutput,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.schema import (
    DataType,
    NodeCategory,
    NodeSchema,
    PortSpec,
)
from aimation_actor_core.shared.errors import AImationError


class VideoPathError(AImationError):
    """Raised when ``video_path`` is disallowed by the media-root allowlist."""

    code = "video_path_disallowed"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class FrameExtractorNode(INode):
    """Decodes a video file into frames, reporting FPS (OpenCV, CPU-only)."""

    def __init__(self, media_root: Path = Path("media")) -> None:
        self._media_root = media_root

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="video-source",
            category=NodeCategory.SOURCE,
            title="Frame Extractor",
            description="Decodes a video file into frames (OpenCV).",
            inputs=[],
            outputs=[
                PortSpec(name="frames", data_type=DataType.FRAMES),
                PortSpec(name="fps", data_type=DataType.NUMBER),
            ],
            params=[
                PortSpec(
                    name="video_path",
                    data_type=DataType.VIDEO_PATH,
                    required=True,
                ),
                PortSpec(name="start", data_type=DataType.NUMBER, default=0),
                PortSpec(name="end", data_type=DataType.NUMBER, default=None),
                PortSpec(name="resize", data_type=DataType.NUMBER, default=None),
            ],
        )

    def _resolve_video_path(self, video_path: str) -> Path:
        """Resolve and validate ``video_path`` against the media_root allowlist.

        Raises :class:`VideoPathError` for absolute paths, traversal escapes,
        missing files, and non-file targets — before any ``cv2.VideoCapture``
        opens the path (SDD §4.3 arbitrary-file-read boundary).
        """
        if not isinstance(video_path, str) or not video_path.strip():
            raise VideoPathError("param video_path must be a non-empty path string")

        candidate = Path(video_path)
        if candidate.is_absolute():
            raise VideoPathError("param video_path must be a relative path under media_root")

        root = self._media_root.resolve()
        resolved = (self._media_root / candidate).resolve()
        try:
            inside = resolved.is_relative_to(root)
        except ValueError:  # pragma: no cover - defensive for non-matching drives
            inside = False
        if not inside:
            raise VideoPathError("param video_path escapes the allowlisted media_root")
        if not resolved.exists():
            raise VideoPathError("param video_path does not exist under media_root")
        if not resolved.is_file():
            raise VideoPathError("param video_path is not a file under media_root")
        return resolved

    @staticmethod
    def _decode_blocking(
        path: Path, start: int, end: int | None, resize: int | None
    ) -> tuple[list[Any], float]:
        """Synchronous decode of a resolved video file (runs off the loop).

        Opens with :func:`cv2.VideoCapture`, reports ``fps``, reads frames in
        the half-open slice ``[start, end)`` (or to EOF when ``end`` is None),
        optionally resizes each frame, and returns ``(frames, fps)``.
        """
        import cv2  # local import keeps the cv2/numpy dependency in this module

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                raise VideoPathError(f"could not open video: {path.name}")
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            # cv2 indexing is 0-based; ``start`` uses the same frame index.
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            frames: list[Any] = []
            frame_index = start
            while True:
                if end is not None and frame_index >= end:
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                if resize is not None and resize > 0:
                    frame = cv2.resize(frame, (resize, resize))
                frames.append(frame)
                frame_index += 1
            return frames, fps
        finally:
            cap.release()

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        video_path = params.get("video_path")
        if not isinstance(video_path, str) or not video_path.strip():
            raise VideoPathError("param video_path must be a non-empty path string")
        resolved = self._resolve_video_path(video_path)
        start = int(params.get("start", 0) or 0)
        end_param = params.get("end")
        end: int | None = None if end_param is None else int(end_param)
        resize_param = params.get("resize")
        resize: int | None = None if resize_param is None else int(resize_param)

        frames, fps = await asyncio.to_thread(self._decode_blocking, resolved, start, end, resize)
        return NodeOutput(values={"frames": frames, "fps": fps})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Defense-in-depth param validation (executor does not call it; kept)."""
        errors: list[str] = []
        video_path = params.get("video_path")
        if not isinstance(video_path, str) or not video_path.strip():
            errors.append("missing required param: video_path")
        return ValidationResult(valid=not errors, errors=errors)
