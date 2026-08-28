"""Public API of the video (AI preprocessing) infrastructure adapters."""

from aimation_actor_core.infrastructure.video.frame_extractor import (
    FrameExtractorNode,
    VideoPathError,
)

__all__ = [
    "FrameExtractorNode",
    "VideoPathError",
]
