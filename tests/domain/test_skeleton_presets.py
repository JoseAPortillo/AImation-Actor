"""Tests for the neutral skeleton preset (REQ-1, plan §14.2).

The preset is a fixed, deterministic hierarchy: ``Root`` plus 21 bones in a
T-pose, up-Y, with LOCAL rest offsets in centimetres, stored parents-before-
children. These exact numeric offsets are pinned here (pose-3d precedent) and
must not drift.

Bone names use the plan §14.2 canonical ``Left…/Right…`` form (ADR-001); the
legacy ``L…/R…`` names migrate to these via ``LEGACY_BONE_RENAME_MAP``.
"""

from __future__ import annotations

import importlib

from aimation_actor_core.domain.animation import skeleton_presets
from aimation_actor_core.domain.animation.skeleton import Bone
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

# The 21 §14.2 bones (plus ``Root`` = 22 total), canonical names (ADR-001).
EXPECTED_BONE_NAMES = [
    "Root",
    "Hips",
    "Spine",
    "Chest",
    "Neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
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
        for name in ("LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"):
            y = skeleton.bones[name].rest_position[1]
            assert y < 0.0, name
        # T-pose arms are horizontal: shoulders reach sideways along X.
        assert skeleton.bones["LeftShoulder"].rest_position[0] < 0.0
        assert skeleton.bones["RightShoulder"].rest_position[0] > 0.0

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
            "LeftShoulder": (-15.0, 6.0, 0.0),
            "LeftArm": (-15.0, 0.0, 0.0),
            "LeftForeArm": (-25.0, 0.0, 0.0),
            "LeftHand": (-22.0, 0.0, 0.0),
            "RightShoulder": (15.0, 6.0, 0.0),
            "RightArm": (15.0, 0.0, 0.0),
            "RightForeArm": (25.0, 0.0, 0.0),
            "RightHand": (22.0, 0.0, 0.0),
            "LeftUpLeg": (0.0, -8.0, 0.0),
            "LeftLeg": (0.0, -40.0, 0.0),
            "LeftFoot": (0.0, -42.0, 0.0),
            "LeftToeBase": (0.0, -2.0, 18.0),
            "RightUpLeg": (0.0, -8.0, 0.0),
            "RightLeg": (0.0, -40.0, 0.0),
            "RightFoot": (0.0, -42.0, 0.0),
            "RightToeBase": (0.0, -2.0, 18.0),
        }
        for name, rest_position in expected.items():
            assert skeleton.bones[name].rest_position == rest_position, name

    def test_values_are_bone_models(self) -> None:
        """Every entry should be a Bone model."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        assert all(isinstance(b, Bone) for b in skeleton.bones.values())

    def test_no_legacy_bone_names_remain(self) -> None:
        """ADR-001: no abbreviated L/R (legacy map key) survives in the skeleton.

        Checked against the map keys, not an ``R`` prefix — ``Root`` is an
        unpaired bone and legitimately starts with ``R``.
        """
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        assert not set(skeleton.bones) & set(skeleton_presets.LEGACY_BONE_RENAME_MAP)

    def test_deterministic_across_reloads(self) -> None:
        """The preset should be stable across independent module loads."""
        first = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        reloaded = importlib.reload(skeleton_presets).DEFAULT_NEUTRAL_SKELETON
        assert first == reloaded
        assert first.model_dump() == reloaded.model_dump()


class TestLegacyBoneRenameMap:
    """ADR-001: the explicit 16-entry legacy → canonical rename table.

    The map must be an explicit table — a naive ``L→Left``/``R→Right`` prefix
    rewrite is forbidden because ``Root`` starts with ``R``.
    """

    def test_map_has_exactly_16_entries(self) -> None:
        """All 16 L/R bones are present, one entry each."""
        assert len(skeleton_presets.LEGACY_BONE_RENAME_MAP) == 16

    def test_map_pairs_legacy_names_to_canonical(self) -> None:
        """Every legacy name maps to its exact canonical counterpart."""
        expected = {
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
        assert dict(skeleton_presets.LEGACY_BONE_RENAME_MAP) == expected

    def test_map_is_bijective_with_skeleton(self) -> None:
        """Keys are legacy-only and values resolve to canonical skeleton bones."""
        skeleton = skeleton_presets.DEFAULT_NEUTRAL_SKELETON
        legacy = set(skeleton_presets.LEGACY_BONE_RENAME_MAP)
        canonical = set(skeleton_presets.LEGACY_BONE_RENAME_MAP.values())
        assert not (legacy & canonical)
        assert not legacy & set(skeleton.bones)
        assert canonical <= set(skeleton.bones)

    def test_root_is_never_prefix_rewritten(self) -> None:
        """'Root' must not be a legacy key and 'Rightoot' must never exist."""
        assert "Root" not in skeleton_presets.LEGACY_BONE_RENAME_MAP
        assert "Rightoot" not in skeleton_presets.LEGACY_BONE_RENAME_MAP.values()
        assert DEFAULT_NEUTRAL_SKELETON.bones["Root"].name == "Root"