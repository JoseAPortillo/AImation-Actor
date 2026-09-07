"""Built-in neutral skeleton preset (plan §14.2).

Provides the default ``Root + 21`` neutral skeleton in T-pose, up-Y, with
LOCAL rest offsets in centimetres and parents-before-children dict order.
This is the reference hierarchy shared by the converter and retargeting
pipelines; no external asset is required.

Bone names use the plan §14.2 canonical ``Left…/Right…`` form (ADR-001).
Legacy ``L…/R…`` names are mapped to them by :data:`LEGACY_BONE_RENAME_MAP`
— an explicit table, never a naive prefix rewrite (``Root`` starts with ``R``).
"""

from __future__ import annotations

from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton

#: ADR-001: explicit 16-entry legacy ``L…/R…`` → canonical ``Left…/Right…``
#: bone-name table used by the NeutralMotion 0.2 → 0.3 migration. A naive
#: ``L→Left``/``R→Right`` prefix rewrite is forbidden because ``Root`` starts
#: with ``R`` (and would become ``Rightoot``); every rename is spelled out.
LEGACY_BONE_RENAME_MAP: dict[str, str] = {
    "LShoulder": "LeftShoulder",
    "LArm": "LeftArm",
    "LForeArm": "LeftForeArm",
    "LHand": "LeftHand",
    "RShoulder": "RightShoulder",
    "RArm": "RightArm",
    "RForeArm": "RightForeArm",
    "RHand": "RightHand",
    "LUpLeg": "LeftUpLeg",
    "LLeg": "LeftLeg",
    "LFoot": "LeftFoot",
    "LToeBase": "LeftToeBase",
    "RUpLeg": "RightUpLeg",
    "RLeg": "RightLeg",
    "RFoot": "RightFoot",
    "RToeBase": "RightToeBase",
}

#: The 21 §14.2 bones in T-pose (plus ``Root`` = 22). Rest offsets are LOCAL
#: (relative to each bone's parent) in centimetres, up-Y: the torso chain
#: rises along +Y, legs descend along -Y, and the arms reach sideways along X.
#: Dict order is parents-before-children so callers can walk the hierarchy in
#: a single forward pass.
DEFAULT_NEUTRAL_SKELETON = Skeleton(
    bones={
        "Root": Bone(name="Root", parent=None, rest_position=(0.0, 0.0, 0.0)),
        "Hips": Bone(name="Hips", parent="Root", rest_position=(0.0, 0.0, 0.0)),
        "Spine": Bone(name="Spine", parent="Hips", rest_position=(0.0, 12.0, 0.0)),
        "Chest": Bone(name="Chest", parent="Spine", rest_position=(0.0, 15.0, 0.0)),
        "Neck": Bone(name="Neck", parent="Chest", rest_position=(0.0, 20.0, 0.0)),
        "Head": Bone(name="Head", parent="Neck", rest_position=(0.0, 18.0, 0.0)),
        "LeftShoulder": Bone(name="LeftShoulder", parent="Chest", rest_position=(-15.0, 6.0, 0.0)),
        "LeftArm": Bone(name="LeftArm", parent="LeftShoulder", rest_position=(-15.0, 0.0, 0.0)),
        "LeftForeArm": Bone(name="LeftForeArm", parent="LeftArm", rest_position=(-25.0, 0.0, 0.0)),
        "LeftHand": Bone(name="LeftHand", parent="LeftForeArm", rest_position=(-22.0, 0.0, 0.0)),
        "RightShoulder": Bone(name="RightShoulder", parent="Chest", rest_position=(15.0, 6.0, 0.0)),
        "RightArm": Bone(name="RightArm", parent="RightShoulder", rest_position=(15.0, 0.0, 0.0)),
        "RightForeArm": Bone(
            name="RightForeArm",
            parent="RightArm",
            rest_position=(25.0, 0.0, 0.0),
        ),
        "RightHand": Bone(name="RightHand", parent="RightForeArm", rest_position=(22.0, 0.0, 0.0)),
        "LeftUpLeg": Bone(name="LeftUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
        "LeftLeg": Bone(name="LeftLeg", parent="LeftUpLeg", rest_position=(0.0, -40.0, 0.0)),
        "LeftFoot": Bone(name="LeftFoot", parent="LeftLeg", rest_position=(0.0, -42.0, 0.0)),
        "LeftToeBase": Bone(name="LeftToeBase", parent="LeftFoot", rest_position=(0.0, -2.0, 18.0)),
        "RightUpLeg": Bone(name="RightUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
        "RightLeg": Bone(name="RightLeg", parent="RightUpLeg", rest_position=(0.0, -40.0, 0.0)),
        "RightFoot": Bone(name="RightFoot", parent="RightLeg", rest_position=(0.0, -42.0, 0.0)),
        "RightToeBase": Bone(
            name="RightToeBase",
            parent="RightFoot",
            rest_position=(0.0, -2.0, 18.0),
        ),
    }
)