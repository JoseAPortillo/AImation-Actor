"""Contract tests for the ``FrameProvider`` domain protocol.

The protocol is the framework-free boundary between the API layer and the
OpenCV frame provider (Phase 2). These tests pin the required method surface
so a conforming provider is recognized and an incomplete one is not.
"""

from __future__ import annotations

from aimation_actor_core.domain.media.frame_provider import FrameProvider


class _ConformingProvider:
    """Minimal ``FrameProvider``-shaped fake with the contract signatures."""

    async def get_frame_jpeg(
        self, video_path: str, frame_index: int, width: int | None = None
    ) -> tuple[bytes, int]:
        return b"\xff\xd8jpeg", 42

    async def get_frame_count(self, video_path: str) -> int:
        return 42


class _MissingFrameCount:
    async def get_frame_jpeg(
        self, video_path: str, frame_index: int, width: int | None = None
    ) -> tuple[bytes, int]:
        return b"\xff\xd8jpeg", 42


class _MissingFrameJpeg:
    async def get_frame_count(self, video_path: str) -> int:
        return 42


class TestFrameProviderProtocol:
    """Structural conformance of the ``FrameProvider`` protocol."""

    def test_conforming_provider_implements_protocol(self) -> None:
        assert isinstance(_ConformingProvider(), FrameProvider)

    def test_provider_without_frame_count_does_not_implement(self) -> None:
        assert not isinstance(_MissingFrameCount(), FrameProvider)

    def test_provider_without_frame_jpeg_does_not_implement(self) -> None:
        assert not isinstance(_MissingFrameJpeg(), FrameProvider)
