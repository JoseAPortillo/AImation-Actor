"""The production skeleton: SMPL's chain mirrored under ``Main``.

The production hierarchy is a contract, not a per-session choice: the bodies
the engine reports (``Hmr2Adapter`` names its joints with SMPL's canonical
names — the same tuple the engine-side worker carries as
``SMPL_BODY_JOINT_NAMES``, mirrored here because ``core`` must not import an
adapter) are remapped, unchanged and in order, under a ground root bone
``Main`` (the domain invariants in ``AGENTS.md``).

The bind offsets are **real model data, not constants**: SMPL's T-pose joint
positions come from the user-supplied body model, so the worker computes them
(the same template the hip-height anchor is derived from) and the adapter
converts them into the domain frame before they reach this builder. names-only
stand-ins invent joint data behind the production mapping, which ``build_window``
refused in M4 for exactly this reason — a missing name is a typed failure.

Standard library only: this module may import the domain (``core.models``) and
nothing from ``ports/`` or ``adapters/``, and no third-party package (NFR-01).
"""

from __future__ import annotations

from collections.abc import Mapping

from aimation_actor.core.models import JointData, Skeleton, Vector3

__all__ = [
    "PRODUCTION_BODY_JOINT_NAMES",
    "PRODUCTION_BODY_JOINT_PARENTS",
    "production_skeleton",
]

#: The 23 body joints after the pelvis, in SMPL's canonical order — the same
#: tuple as the engine-side worker's ``SMPL_BODY_JOINT_NAMES`` (SMPL joints
#: 1..23; the pelvis itself is ``global_orient`` and is named ``Pelvis``).
PRODUCTION_BODY_JOINT_NAMES: tuple[str, ...] = (
    "L_Hip",
    "R_Hip",
    "Spine_1",
    "L_Knee",
    "R_Knee",
    "Spine_2",
    "L_Ankle",
    "R_Ankle",
    "Spine_3",
    "L_Foot",
    "R_Foot",
    "Neck",
    "L_Collar",
    "R_Collar",
    "Head",
    "L_Shoulder",
    "R_Shoulder",
    "L_Elbow",
    "R_Elbow",
    "L_Wrist",
    "R_Wrist",
    "L_Hand",
    "R_Hand",
)

#: Each body joint's production parent, mirroring SMPL's kintree: the three
#: spine joints and both hips hang from ``Pelvis``, the spine chain descends
#: through ``Spine_1 -> Spine_2 -> Spine_3``, the collarbones and ``Neck`` hang
#: from ``Spine_3``, and the limbs descend in SMPL's canonical order.
PRODUCTION_BODY_JOINT_PARENTS: dict[str, str] = {
    name: parent
    for name, parent in (
        ("L_Hip", "Pelvis"),
        ("R_Hip", "Pelvis"),
        ("Spine_1", "Pelvis"),
        ("L_Knee", "L_Hip"),
        ("R_Knee", "R_Hip"),
        ("Spine_2", "Spine_1"),
        ("L_Ankle", "L_Knee"),
        ("R_Ankle", "R_Knee"),
        ("Spine_3", "Spine_2"),
        ("L_Foot", "L_Ankle"),
        ("R_Foot", "R_Ankle"),
        ("Neck", "Spine_3"),
        ("L_Collar", "Spine_3"),
        ("R_Collar", "Spine_3"),
        ("Head", "Neck"),
        ("L_Shoulder", "L_Collar"),
        ("R_Shoulder", "R_Collar"),
        ("L_Elbow", "L_Shoulder"),
        ("R_Elbow", "R_Shoulder"),
        ("L_Wrist", "L_Elbow"),
        ("R_Wrist", "R_Elbow"),
        ("L_Hand", "L_Wrist"),
        ("R_Hand", "R_Wrist"),
    )
}


def production_skeleton(bind_offsets: Mapping[str, Vector3]) -> Skeleton:
    """Build the production skeleton from the engine's template bind offsets.

    ``bind_offsets`` maps every production joint name but ``Main`` to its
    local bind offset: ``Pelvis`` to the template pelvis position from the
    ground (its ``z`` is the bind height ``build_production_pose`` consumes),
    and every body joint to its SMIL-kintree parent-relative T-pose offset,
    both in the domain's Z-up centimetres. A missing name is a ``ValueError``
    naming every hole — the skeleton feeds both the viewport and the FBX
    writer, so a partially known bind would export a knowingly wrong rig.
    """
    required = ("Pelvis", *PRODUCTION_BODY_JOINT_NAMES)
    missing = [name for name in required if name not in bind_offsets]
    if missing:
        raise ValueError(
            "the engine's template bind offsets are incomplete "
            f"(missing: {', '.join(missing)}); the body model may not be the "
            "SMPL one the adapter configures"
        )

    joints: list[JointData] = [
        JointData(name="Main", parent=None),
        JointData(name="Pelvis", parent="Main", rest_translation=bind_offsets["Pelvis"]),
    ]
    joints.extend(
        JointData(
            name=name,
            parent=PRODUCTION_BODY_JOINT_PARENTS[name],
            rest_translation=bind_offsets[name],
        )
        for name in PRODUCTION_BODY_JOINT_NAMES
    )
    return Skeleton(joints=tuple(joints))
