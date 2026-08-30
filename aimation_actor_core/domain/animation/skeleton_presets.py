"""Built-in neutral skeleton preset (plan §14.2).

Provides the default ``Root + 21`` neutral skeleton in T-pose, up-Y, with
LOCAL rest offsets in centimetres and parents-before-children dict order.
This is the reference hierarchy shared by the converter and retargeting
pipelines; no external asset is required.
"""

from __future__ import annotations

from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton

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
        "LShoulder": Bone(name="LShoulder", parent="Chest", rest_position=(-15.0, 6.0, 0.0)),
        "LArm": Bone(name="LArm", parent="LShoulder", rest_position=(-15.0, 0.0, 0.0)),
        "LForeArm": Bone(name="LForeArm", parent="LArm", rest_position=(-25.0, 0.0, 0.0)),
        "LHand": Bone(name="LHand", parent="LForeArm", rest_position=(-22.0, 0.0, 0.0)),
        "RShoulder": Bone(name="RShoulder", parent="Chest", rest_position=(15.0, 6.0, 0.0)),
        "RArm": Bone(name="RArm", parent="RShoulder", rest_position=(15.0, 0.0, 0.0)),
        "RForeArm": Bone(name="RForeArm", parent="RArm", rest_position=(25.0, 0.0, 0.0)),
        "RHand": Bone(name="RHand", parent="RForeArm", rest_position=(22.0, 0.0, 0.0)),
        "LUpLeg": Bone(name="LUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
        "LLeg": Bone(name="LLeg", parent="LUpLeg", rest_position=(0.0, -40.0, 0.0)),
        "LFoot": Bone(name="LFoot", parent="LLeg", rest_position=(0.0, -42.0, 0.0)),
        "LToeBase": Bone(name="LToeBase", parent="LFoot", rest_position=(0.0, -2.0, 18.0)),
        "RUpLeg": Bone(name="RUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
        "RLeg": Bone(name="RLeg", parent="RUpLeg", rest_position=(0.0, -40.0, 0.0)),
        "RFoot": Bone(name="RFoot", parent="RLeg", rest_position=(0.0, -42.0, 0.0)),
        "RToeBase": Bone(name="RToeBase", parent="RFoot", rest_position=(0.0, -2.0, 18.0)),
    }
)
