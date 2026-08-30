"""Tests for Keypoint3D/Keypoints3D domain value objects (REQ-1)."""

import json

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation import Keypoint3D, Keypoints3D
from aimation_actor_core.domain.animation.keypoints3d import Keypoint3D as ModuleKeypoint3D
from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D as ModuleKeypoints3D


def _kp(
    label: str = "nose",
    x: float = 0.5,
    y: float = 0.3,
    z: float = 0.55,
    confidence: float = 0.95,
) -> Keypoint3D:
    """Build a valid Keypoint3D for reuse across the test cases."""
    return ModuleKeypoint3D(label=label, x=x, y=y, z=z, confidence=confidence)


class TestKeypoint3D:
    """Test Keypoint3D value object."""

    def test_valid_keypoint3d(self) -> None:
        """Should create a Keypoint3D with valid values."""
        kp = _kp()
        assert kp.label == "nose"
        assert kp.x == 0.5
        assert kp.y == 0.3
        assert kp.z == 0.55
        assert kp.confidence == 0.95

    def test_boundary_values_accepted(self) -> None:
        """Should accept boundary values (0.0 and 1.0)."""
        kp = ModuleKeypoint3D(label="test", x=0.0, y=1.0, z=1.0, confidence=0.0)
        assert kp.x == 0.0
        assert kp.y == 1.0
        assert kp.z == 1.0
        assert kp.confidence == 0.0

    def test_visible_defaults_to_true(self) -> None:
        """Should default visible to True (per-joint occlusion flag)."""
        kp = _kp()
        assert kp.visible is True

    def test_visible_explicit_false(self) -> None:
        """Should accept an explicit visible=False value."""
        kp = ModuleKeypoint3D(label="nose", x=0.5, y=0.3, z=0.55, confidence=0.95, visible=False)
        assert kp.visible is False

    def test_z_rejects_out_of_range_high(self) -> None:
        """Should reject z values above 1.0."""
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=0.5, z=1.1, confidence=0.9)

    def test_z_rejects_out_of_range_low(self) -> None:
        """Should reject z values below 0.0."""
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=0.5, z=-0.1, confidence=0.9)

    def test_x_rejects_out_of_range(self) -> None:
        """Should reject x values outside [0, 1]."""
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=-0.1, y=0.5, z=0.5, confidence=0.9)
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=1.1, y=0.5, z=0.5, confidence=0.9)

    def test_y_rejects_out_of_range(self) -> None:
        """Should reject y values outside [0, 1]."""
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=-0.1, z=0.5, confidence=0.9)
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=1.1, z=0.5, confidence=0.9)

    def test_confidence_rejects_out_of_range(self) -> None:
        """Should reject confidence values outside [0, 1]."""
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=0.5, z=0.5, confidence=-0.1)
        with pytest.raises(ValidationError):
            ModuleKeypoint3D(label="test", x=0.5, y=0.5, z=0.5, confidence=1.1)

    def test_is_frozen(self) -> None:
        """Should be immutable."""
        kp = _kp()
        with pytest.raises(ValidationError):
            kp.label = "changed"

    def test_z_camera_plane_convention_documented(self) -> None:
        """Should document that z=0.5 is the camera plane on the field."""
        description = Keypoint3D.model_fields["z"].description or ""
        assert "0.5" in description
        assert "camera plane" in description


class TestKeypoints3D:
    """Test Keypoints3D value object."""

    def test_valid_keypoints3d(self) -> None:
        """Should create Keypoints3D with keypoints."""
        seq = ModuleKeypoints3D(frame_index=3, keypoints=[_kp(), _kp(label="left_eye", z=0.5)])
        assert seq.frame_index == 3
        assert len(seq.keypoints) == 2
        assert seq.keypoints[0].label == "nose"
        assert seq.keypoints[1].label == "left_eye"

    def test_empty_keypoints_list(self) -> None:
        """Should accept an empty keypoints list."""
        seq = ModuleKeypoints3D(frame_index=5, keypoints=[])
        assert seq.frame_index == 5
        assert len(seq.keypoints) == 0

    def test_rejects_negative_frame_index(self) -> None:
        """Should reject negative frame_index."""
        with pytest.raises(ValidationError):
            ModuleKeypoints3D(frame_index=-1, keypoints=[])

    def test_is_frozen(self) -> None:
        """Should be immutable."""
        seq = ModuleKeypoints3D(frame_index=0, keypoints=[])
        with pytest.raises(ValidationError):
            seq.frame_index = 1


class TestKeypoints3DSerialization:
    """Test JSON-safe, numpy-free serialization (REQ-1)."""

    def test_model_dump_json_round_trips(self) -> None:
        """Should serialize to valid JSON preserving all fields."""
        seq = ModuleKeypoints3D(
            frame_index=2,
            keypoints=[
                _kp(),
                ModuleKeypoint3D(label="ankle", x=0.45, y=0.9, z=0.65, confidence=0.4),
            ],
        )
        payload = json.loads(seq.model_dump_json())
        assert payload["frame_index"] == 2
        assert len(payload["keypoints"]) == 2
        assert payload["keypoints"][0] == {
            "label": "nose",
            "x": 0.5,
            "y": 0.3,
            "z": 0.55,
            "confidence": 0.95,
            "visible": True,
        }
        assert payload["keypoints"][1]["z"] == 0.65

    def test_no_ndarray_values(self) -> None:
        """Should contain only plain JSON scalars, never numpy arrays/scalars.

        ``json.dumps`` raises ``TypeError`` on numpy values, so a successful
        stdlib dump of the decoded payload proves the boundary is numpy-free.
        """
        seq = ModuleKeypoints3D(frame_index=0, keypoints=[_kp()])
        payload = json.loads(seq.model_dump_json())
        json.dumps(payload)
        assert isinstance(payload["frame_index"], int)
        for kp in payload["keypoints"]:
            for value in kp.values():
                assert isinstance(value, (str, bool, int, float))

    def test_reexported_from_animation_package(self) -> None:
        """Should be importable from the animation package public API."""
        assert Keypoint3D is ModuleKeypoint3D
        assert Keypoints3D is ModuleKeypoints3D
