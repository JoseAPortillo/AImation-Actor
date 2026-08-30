"""Tests for the neutral skeleton preset (REQ-1, plan §14.2).

The preset is a fixed, deterministic hierarchy: ``Root`` plus 21 bones in a
T-pose, up-Y, with LOCAL rest offsets in centimetres, stored parents-before-
children. These exact numeric offsets are pinned here (pose-3d precedent) and
must not drift.
"""

from __future__ import annotations

import importlib

from aimation_actor_core.domain.animation import skeleton_presets
from aimation_actor_core.domain.animation.skeleton import Bone

# The 21 §14.2 bones (plus ``Root`` = 22 total).
EXPECTED_BONE_NAMES = [
    "Root",
    "Hips",
    "Spine",
    "Chest",
    "Neck",
    "Head",
    "LShoulder",
    "LArm",
    "LForeArm",
    "LHand",
    "RShoulder",
    "RArm",
    "RForeArm",
    "RHand",
    "LUpLeg",
    "LLeg",
    "LFoot",
    "LToeBase",
    "RUpLeg",
    "RLeg",
    "RFoot",
    "RToeBase",
]


class TestSkeletonPreset:
    """The default neutral skeleton contract."""

    def test_has_root_plus_21_bones(self) -> None:
        """Should expose Root plus the 21 §14.2 bones (22 total)."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        assert len(skeleton.bones) == 22
        assert set(skeleton.bones) == set(EXPECTED_BONE_NAMES)

    def test_root_is_the_single_root(self) -> None:
        """Should have exactly one root named 'Root' with no parent."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        assert skeleton.root == "Root"
        assert skeleton.bones["Root"].parent is None
        # Every other bone has a parent.
        assert sum(1 for b in skeleton.bones.values() if b.parent is None) == 1

    def test_forms_single_rooted_tree(self) -> None:
        """Should pass validate_hierarchy() without error."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        skeleton.validate_hierarchy()  # raises on invalid

    def test_parents_before_children_dict_order(self) -> None:
        """Should list each parent before its children (for topological walk)."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        names = list(skeleton.bones)
        index = {name: i for i, name in enumerate(names)}
        for name, bone in skeleton.bones.items():
            if bone.parent is not None:
                assert index[bone.parent] < index[name], (
                    f"parent '{bone.parent}' must appear before child '{name}'"
                )

    def test_all_rest_rotations_are_identity(self) -> None:
        """T-pose: every bone rest rotation is the identity quaternion."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        for name, bone in skeleton.bones.items():
            assert bone.rest_rotation == (1.0, 0.0, 0.0, 0.0), name

    def test_t_pose_orientation_up_y(self) -> None:
        """T-pose with up-Y: torso rest offsets rise along +Y, legs descend.

        Locally, Spine/Chest/Neck/Head rest offsets are positive Y (up), leg
        bones negative Y (down), and shoulders reach sideways along X
        (arms horizontal in the T-pose).
        """
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        # Up axis is +Y: torso chain rises.
        for name in ("Spine", "Chest", "Neck", "Head"):
            y = skeleton.bones[name].rest_position[1]
            assert y > 0.0, name
        # Legs descend along -Y.
        for name in ("LUpLeg", "LLeg", "LFoot", "RUpLeg", "RLeg", "RFoot"):
            y = skeleton.bones[name].rest_position[1]
            assert y < 0.0, name
        # T-pose arms are horizontal: shoulders reach sideways along X.
        assert skeleton.bones["LShoulder"].rest_position[0] < 0.0
        assert skeleton.bones["RShoulder"].rest_position[0] > 0.0

    def test_pinned_rest_offsets(self) -> None:
        """Exact pinned LOCAL rest offsets (cm) for the neutral skeleton."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        expected: dict[str, tuple[float, float, float]] = {
            "Root": (0.0, 0.0, 0.0),
            "Hips": (0.0, 0.0, 0.0),
            "Spine": (0.0, 12.0, 0.0),
            "Chest": (0.0, 15.0, 0.0),
            "Neck": (0.0, 20.0, 0.0),
            "Head": (0.0, 18.0, 0.0),
            "LShoulder": (-15.0, 6.0, 0.0),
            "LArm": (-15.0, 0.0, 0.0),
            "LForeArm": (-25.0, 0.0, 0.0),
            "LHand": (-22.0, 0.0, 0.0),
            "RShoulder": (15.0, 6.0, 0.0),
            "RArm": (15.0, 0.0, 0.0),
            "RForeArm": (25.0, 0.0, 0.0),
            "RHand": (22.0, 0.0, 0.0),
            "LUpLeg": (0.0, -8.0, 0.0),
            "LLeg": (0.0, -40.0, 0.0),
            "LFoot": (0.0, -42.0, 0.0),
            "LToeBase": (0.0, -2.0, 18.0),
            "RUpLeg": (0.0, -8.0, 0.0),
            "RLeg": (0.0, -40.0, 0.0),
            "RFoot": (0.0, -42.0, 0.0),
            "RToeBase": (0.0, -2.0, 18.0),
        }
        for name, rest_position in expected.items():
            assert skeleton.bones[name].rest_position == rest_position, name

    def test_values_are_bone_models(self) -> None:
        """Every entry should be a Bone model."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        assert all(isinstance(b, Bone) for b in skeleton.bones.values())

    def test_deterministic_across_reloads(self) -> None:
        """The preset should be stable across independent module loads."""
        first = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        reloaded = importlib.reload(skeleton_presets).DEFAULT_NEUTRAL_SKELETON
        assert first == reloaded
        assert first.model_dump() == reloaded.model_dump()
