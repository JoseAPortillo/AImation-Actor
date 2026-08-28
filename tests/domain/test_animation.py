"""Unit tests for the animation domain contracts (SDD §3.3, domain coverage)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation import (
    Bone,
    Frame,
    HierarchyError,
    NeutralMotion,
    Pose,
    Skeleton,
    Transform3D,
)


def _hierarchy() -> Skeleton:
    """Build a minimal valid single-tree skeleton."""
    return Skeleton(
        bones={
            "Root": Bone(name="Root", parent=None),
            "Hips": Bone(name="Hips", parent="Root"),
            "Spine": Bone(name="Spine", parent="Hips"),
        }
    )


class TestTransform3D:
    def test_defaults_are_identity(self) -> None:
        t = Transform3D()
        assert t.translation == (0.0, 0.0, 0.0)
        assert t.rotation == (1.0, 0.0, 0.0, 0.0)
        assert t.scale == (1.0, 1.0, 1.0)

    def test_frozen(self) -> None:
        t = Transform3D()
        with pytest.raises(ValidationError):
            t.translation = (1.0, 2.0, 3.0)  # type: ignore[misc]

    def test_rejects_wrong_vector_length(self) -> None:
        with pytest.raises(ValidationError):
            Transform3D(translation=(1.0, 2.0))  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Transform3D(rotation=(1.0, 0.0, 0.0))  # type: ignore[arg-type]


class TestFrame:
    def test_min_frame_is_one(self) -> None:
        with pytest.raises(ValidationError):
            Frame(frame=0)

    def test_confidence_range(self) -> None:
        with pytest.raises(ValidationError):
            Frame(frame=1, confidence=1.5)
        ok = Frame(frame=1, confidence=0.9)
        assert ok.confidence == 0.9


class TestSkeletonHierarchy:
    def test_valid_hierarchy_passes(self) -> None:
        skeleton = _hierarchy()
        skeleton.validate_hierarchy()

    def test_single_root(self) -> None:
        assert _hierarchy().root == "Root"

    def test_unknown_parent_fails(self) -> None:
        skeleton = Skeleton(
            bones={
                "A": Bone(name="A", parent=None),
                "B": Bone(name="B", parent="Ghost"),
            }
        )
        with pytest.raises(HierarchyError):
            skeleton.validate_hierarchy()

    def test_multiple_roots_fail(self) -> None:
        skeleton = Skeleton(
            bones={
                "A": Bone(name="A", parent=None),
                "B": Bone(name="B", parent=None),
            }
        )
        with pytest.raises(HierarchyError):
            skeleton.validate_hierarchy()

    def test_cycle_fails(self) -> None:
        skeleton = Skeleton(
            bones={
                "A": Bone(name="A", parent="B"),
                "B": Bone(name="B", parent="A"),
            }
        )
        with pytest.raises(HierarchyError):
            skeleton.validate_hierarchy()

    def test_empty_skeleton_fails(self) -> None:
        with pytest.raises(HierarchyError):
            Skeleton().validate_hierarchy()


class TestNeutralMotion:
    def test_round_trip_frozen(self) -> None:
        motion = NeutralMotion(
            skeleton=_hierarchy(),
            frames=[
                Frame(
                    frame=1,
                    pose=Pose(
                        transforms={"Hips": Transform3D(translation=(0.0, 100.0, 0.0))}
                    ),
                ),
                Frame(frame=2),
            ],
        )
        motion.validate_invariants()
        with pytest.raises(ValidationError):
            motion.meta = NeutralMotion().meta  # type: ignore[misc]

    def test_out_of_order_frames_fail(self) -> None:
        motion = NeutralMotion(
            frames=[Frame(frame=2), Frame(frame=1)],
            skeleton=_hierarchy(),
        )
        with pytest.raises(ValueError):
            motion.validate_invariants()

    def test_frame_exceeds_duration_fails(self) -> None:
        meta = NeutralMotion().meta.model_copy(update={"duration_frames": 5})
        motion = NeutralMotion(
            meta=meta,
            skeleton=_hierarchy(),
            frames=[Frame(frame=10)],
        )
        with pytest.raises(ValueError):
            motion.validate_invariants()
