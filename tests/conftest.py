"""Shared fixtures for the FBX tests."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fbx_helpers import rotation_x, rotation_xyz_120, rotation_z

from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)


@pytest.fixture
def workspace() -> Iterator[Path]:
    """A writable scratch directory.

    Deliberately not pytest's ``tmp_path``: on this machine the user-level
    ``pytest-of-*`` temp root is owned by another account and cannot be removed.
    """
    with tempfile.TemporaryDirectory(prefix="aimation-tests-") as directory:
        yield Path(directory)


@pytest.fixture
def sample_state() -> TimelineState:
    """A small sparse timeline: five joints, keys only at frames 15 and 42."""
    skeleton = Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="Spine_1", parent="Pelvis"),
            JointData(name="Spine_2", parent="Spine_1"),
            JointData(name="Head", parent="Spine_2"),
        )
    )
    keyframes = (
        Keyframe(
            frame=15,
            pose={
                "Main": JointPose(rotation=Quaternion.identity(), translation=Vector3(x=10.0)),
                "Spine_1": JointPose(rotation=rotation_z(30.0)),
            },
        ),
        Keyframe(
            frame=42,
            pose={
                "Main": JointPose(
                    rotation=Quaternion.identity(), translation=Vector3(x=20.0, y=5.0)
                ),
                "Spine_1": JointPose(rotation=rotation_xyz_120()),
                "Head": JointPose(rotation=rotation_x(60.0)),
            },
        ),
    )
    return TimelineState(
        skeleton=skeleton,
        keyframes=keyframes,
        fps=24.0,
        frame_start=15,
        frame_end=42,
    )
