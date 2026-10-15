"""Tests for the AI port contract (M5 S1, S2 · NFR-01, FR-CAP-05, FR-CAP-06).

The port is the seam that keeps an engine swappable: callers see only the domain,
and the engine never sees the toolkit that produced the frame. What is pinned
here is that the contract is abstract, that it speaks domain types, and that an
implementation is all a caller needs.
"""

from __future__ import annotations

import pytest

from aimation_actor.core.models import FrameImage, Quaternion, Skeleton, Vector3, WorldPose
from aimation_actor.core.services import build_production_pose
from aimation_actor.ports.ai_port import AIPort


class _ConstantEngine(AIPort):
    """The smallest engine: reports one fixed pose for any frame."""

    def __init__(self, pose: WorldPose) -> None:
        self._pose = pose

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        return self._pose


def test_the_port_cannot_be_instantiated() -> None:
    # The abstract operation is the whole contract; an engine must provide it.
    with pytest.raises(TypeError):
        AIPort()  # type: ignore[abstract]


def test_an_engine_only_has_to_implement_one_operation() -> None:
    # Interface segregation: one method, so an engine that only extracts is never
    # forced to implement inbetweening it does not have.
    engine = _ConstantEngine(WorldPose(translation=Vector3(z=100.0), rotations={}))

    assert isinstance(engine, AIPort)
    assert engine.extract_pose(_frame(), frame_index=3).translation.z == pytest.approx(100.0)


def test_what_an_engine_reports_feeds_the_production_mapping() -> None:
    # FR-CAP-06 end to end at the contract level: the engine's WorldPose is
    # exactly what build_production_pose consumes, with no translation layer.
    skeleton = Skeleton(joints=_skeleton_joints())
    engine = _ConstantEngine(
        WorldPose(
            translation=Vector3(x=999.0, y=-999.0, z=88.0),  # horizontal is dropped
            rotations={"Pelvis": Quaternion.identity()},
        )
    )

    pose = build_production_pose(engine.extract_pose(_frame(), frame_index=0), skeleton)

    # The rig is fully posed, the hip keeps only its height, and the ground root
    # is the animator's control and stays untouched (AGENTS.md invariants).
    assert set(pose) == set(skeleton.names())
    assert pose["Pelvis"].translation == Vector3(z=-12.0)  # 88 - rest 100
    assert pose["Pelvis"].translation.x == pytest.approx(0.0)
    assert pose["Main"].translation == Vector3()
    assert pose["Main"].rotation == Quaternion.identity()


def _frame() -> FrameImage:
    return FrameImage(width=1, height=1, rgb=bytes(3))


def _skeleton_joints():
    from aimation_actor.core.models import JointData

    return (
        JointData(name="Main", parent=None),
        JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        JointData(name="Spine_1", parent="Pelvis"),
    )
