"""Tests for Keypoints2D domain value objects."""

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D


class TestKeypoint:
    """Test Keypoint value object."""

    def test_valid_keypoint(self) -> None:
        """Should create Keypoint with valid values."""
        kp = Keypoint(label="nose", x=0.5, y=0.3, confidence=0.95)
        assert kp.label == "nose"
        assert kp.x == 0.5
        assert kp.y == 0.3
        assert kp.confidence == 0.95

    def test_keypoint_boundary_values(self) -> None:
        """Should accept boundary values (0.0 and 1.0)."""
        kp = Keypoint(label="test", x=0.0, y=1.0, confidence=0.0)
        assert kp.x == 0.0
        assert kp.y == 1.0
        assert kp.confidence == 0.0

    def test_keypoint_rejects_x_out_of_range(self) -> None:
        """Should reject x values outside [0, 1]."""
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=-0.1, y=0.5, confidence=0.9)
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=1.1, y=0.5, confidence=0.9)

    def test_keypoint_rejects_y_out_of_range(self) -> None:
        """Should reject y values outside [0, 1]."""
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=0.5, y=-0.1, confidence=0.9)
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=0.5, y=1.1, confidence=0.9)

    def test_keypoint_rejects_confidence_out_of_range(self) -> None:
        """Should reject confidence values outside [0, 1]."""
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=0.5, y=0.5, confidence=-0.1)
        with pytest.raises(ValidationError):
            Keypoint(label="test", x=0.5, y=0.5, confidence=1.1)

    def test_keypoint_is_frozen(self) -> None:
        """Should be immutable."""
        kp = Keypoint(label="test", x=0.5, y=0.5, confidence=0.9)
        with pytest.raises(ValidationError):
            kp.label = "changed"  # type: ignore[misc]


class TestKeypoints2D:
    """Test Keypoints2D value object."""

    def test_valid_keypoints2d(self) -> None:
        """Should create Keypoints2D with valid keypoints."""
        kps = [
            Keypoint(label="nose", x=0.5, y=0.3, confidence=0.95),
            Keypoint(label="left_eye", x=0.45, y=0.25, confidence=0.92),
        ]
        kp2d = Keypoints2D(frame_index=0, keypoints=kps)
        assert kp2d.frame_index == 0
        assert len(kp2d.keypoints) == 2
        assert kp2d.keypoints[0].label == "nose"

    def test_empty_keypoints_list(self) -> None:
        """Should accept empty keypoints list."""
        kp2d = Keypoints2D(frame_index=5, keypoints=[])
        assert kp2d.frame_index == 5
        assert len(kp2d.keypoints) == 0

    def test_keypoints2d_rejects_negative_frame_index(self) -> None:
        """Should reject negative frame_index."""
        with pytest.raises(ValidationError):
            Keypoints2D(frame_index=-1, keypoints=[])

    def test_keypoints2d_is_frozen(self) -> None:
        """Should be immutable."""
        kp2d = Keypoints2D(frame_index=0, keypoints=[])
        with pytest.raises(ValidationError):
            kp2d.frame_index = 1  # type: ignore[misc]

    def test_json_serialization(self) -> None:
        """Should be JSON-serializable."""
        kps = [Keypoint(label="nose", x=0.5, y=0.3, confidence=0.95)]
        kp2d = Keypoints2D(frame_index=0, keypoints=kps)

        # Should serialize to dict
        data = kp2d.model_dump()
        assert data["frame_index"] == 0
        assert len(data["keypoints"]) == 1
        assert data["keypoints"][0]["label"] == "nose"

        # Should serialize to JSON
        json_str = kp2d.model_dump_json()
        assert "nose" in json_str
        assert "0.5" in json_str
