"""Production skeleton builder: SMPL's chain mirrored under ``Main``.

The production hierarchy is the one the engine reports (the worker names its
joints with SMPL's canonical names and the adapter converts the template's
bind offsets into the domain frame), so the builder is pure domain logic
tested against the same contract that ``AGENTS.md`` documents.
"""

from __future__ import annotations

import pytest

from aimation_actor.core.models import Vector3
from aimation_actor.core.production_skeleton import (
    PRODUCTION_BODY_JOINT_NAMES,
    production_skeleton,
)

_BIND = {
    "Pelvis": Vector3(x=0.0, y=0.0, z=93.85),
    "L_Hip": Vector3(x=3.0, y=0.2, z=88.0),
    "R_Hip": Vector3(x=-3.0, y=0.2, z=88.0),
    "L_Knee": Vector3(x=2.0, y=1.0, z=44.0),
    "L_Hand": Vector3(x=1.0, y=-1.0, z=1.0),
}


def _offsets() -> dict[str, Vector3]:
    """A bind mapping covering every production joint (flat stand-ins)."""
    return {
        "Pelvis": Vector3(x=0.0, y=0.0, z=93.85),
        **{name: Vector3(x=1.0, y=0.0, z=1.0) for name in PRODUCTION_BODY_JOINT_NAMES},
    }


def test_the_hierarchy_mirrors_smpl_under_main() -> None:
    skeleton = production_skeleton(_offsets())
    names = skeleton.names()

    assert len(names) == 25  # Main + Pelvis + 23 SMPL body joints
    assert names[0] == "Main"
    assert names[1] == "Pelvis"
    by_name = {joint.name: joint for joint in skeleton.joints}
    assert by_name["Main"].parent is None
    assert by_name["Pelvis"].parent == "Main"
    assert by_name["L_Knee"].parent == "L_Hip"
    assert by_name["R_Knee"].parent == "R_Hip"
    assert by_name["Spine_2"].parent == "Spine_1"
    assert by_name["Head"].parent == "Neck"
    assert by_name["L_Shoulder"].parent == "L_Collar"
    assert by_name["L_Hand"].parent == "L_Wrist"


def test_the_order_is_root_first_topological() -> None:
    skeleton = production_skeleton(_offsets())
    seen = set()
    for joint in skeleton.joints:
        if joint.parent is not None:
            assert joint.parent in seen, f"{joint.name} placed before its parent"
        seen.add(joint.name)


def test_bind_offsets_become_rest_translations() -> None:
    offsets = _offsets()
    offsets.update(_BIND)
    skeleton = production_skeleton(offsets)
    by_name = {joint.name: joint for joint in skeleton.joints}
    assert by_name["Main"].rest_translation == Vector3(x=0.0, y=0.0, z=0.0)
    assert by_name["Pelvis"].rest_translation == Vector3(x=0.0, y=0.0, z=93.85)
    assert by_name["L_Hip"].rest_translation == Vector3(x=3.0, y=0.2, z=88.0)
    assert by_name["L_Knee"].rest_translation == Vector3(x=2.0, y=1.0, z=44.0)


def test_a_missing_bind_is_a_named_failure() -> None:
    incomplete = _offsets()
    del incomplete["L_Knee"]
    del incomplete["R_Hip"]
    with pytest.raises(ValueError) as caught:
        production_skeleton(incomplete)
    message = str(caught.value)
    assert "L_Knee" in message and "R_Hip" in message


def test_the_bind_mapping_must_be_complete_not_partial() -> None:
    skeleton = production_skeleton(_offsets())
    names = skeleton.names()
    assert set(PRODUCTION_BODY_JOINT_NAMES) <= set(names)
    assert "Pelvis" in names and "Main" in names
