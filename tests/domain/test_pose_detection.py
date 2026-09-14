"""Unit tests for the single-frame pose domain model and detector protocol.

``SingleFramePose`` reuses the existing ``Keypoint`` domain model and carries
a frame-level confidence; the detector protocol is the framework-free boundary
for the Phase 2 endpoint wiring.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation.keypoints import Keypoint
from aimation_actor_core.domain.animation.pose_detection import (
    SingleFramePose,
    SingleFramePoseDetector,
)


class TestSingleFramePose:
    """Behavior of the ``SingleFramePose`` domain model."""

    def test_valid_pose_roundtrips_fields(self) -> None:
        kp = Keypoint(label="nose", x=0.5, y=0.2, confidence=0.95)
        pose = SingleFramePose(keypoints=[kp], confidence=0.95)
        assert pose.keypoints == [kp]
        assert pose.confidence == 0.95

    def test_reuses_domain_keypoint_model(self) -> None:
        pose = SingleFramePose(
            keypoints=[Keypoint(label="left_ankle", x=0.45, y=0.9, confidence=0.7)],
            confidence=0.7,
        )
        assert isinstance(pose.keypoints[0], Keypoint)

    @pytest.mark.parametrize("bad_confidence", [1.1, -0.1])
    def test_confidence_out_of_range_rejected(self, bad_confidence: float) -> None:
        with pytest.raises(ValidationError):
            SingleFramePose(keypoints=[], confidence=bad_confidence)


class _ConformingDetector:
    async def detect(self, video_path: str, frame_index: int) -> SingleFramePose:
        return SingleFramePose(keypoints=[], confidence=0.5)


class _MissingDetect:
    pass


class TestSingleFramePoseDetectorProtocol:
    """Structural conformance of the detector protocol."""

    def test_conforming_detector_implements_protocol(self) -> None:
        assert isinstance(_ConformingDetector(), SingleFramePoseDetector)

    def test_detector_without_detect_does_not_implement(self) -> None:
        assert not isinstance(_MissingDetect(), SingleFramePoseDetector)
