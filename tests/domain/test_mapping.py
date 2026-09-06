"""Tests for the COCO→neutral bone mapping table (REQ-1).

The mapping bridges the estimator's COCO 17 keypoint labels to the §14.2
neutral skeleton. The 13 distal-end rows are exact COCO strings; derived and
rest-only bones complete full skeleton coverage; pose-only labels (eyes,
ears) and unknown labels are intentionally absent/ignored.

Neutral values use the canonical ``Left…/Right…`` names (ADR-001).
"""

from __future__ import annotations

from aimation_actor_core.domain.animation import mapping
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.infrastructure.ai_models.estimators import SyntheticBackend

EXPECTED_ROWS: set[tuple[str, str]] = {
    ("nose", "Head"),
    ("left_shoulder", "LeftShoulder"),
    ("right_shoulder", "RightShoulder"),
    ("left_elbow", "LeftArm"),
    ("right_elbow", "RightArm"),
    ("left_wrist", "LeftForeArm"),
    ("right_wrist", "RightForeArm"),
    ("left_hip", "LeftUpLeg"),
    ("right_hip", "RightUpLeg"),
    ("left_knee", "LeftLeg"),
    ("right_knee", "RightLeg"),
    ("left_ankle", "LeftFoot"),
    ("right_ankle", "RightFoot"),
}

# Bones with no 1:1 COCO landmark; they keep their neutral rest offset.
REST_ONLY_BONES = {
    "Spine",
    "Chest",
    "Neck",
    "LeftHand",
    "RightHand",
    "LeftToeBase",
    "RightToeBase",
}

# Bones derived from lower-level landmarks (not a single COCO row).
DERIVED_BONES = {"Hips"}


class TestCocoToNeutralMapping:
    """The frozen 13-row COCO→bone table."""

    def test_has_13_rows(self) -> None:
        """Should contain exactly the 13 pinned distal-end rows."""
        assert dict(mapping.COCO_TO_NEUTRAL) == dict(EXPECTED_ROWS)

    def test_every_row_key_is_an_exact_estimator_label(self) -> None:
        """The silent rest-offset guard: every key must be an exact COCO string.

        This is the single most important assertion — if a key drifts from the
        estimator's exact label strings, that bone silently falls back to rest
        and the pose is quietly wrong. Keys must match ``KEYPOINT_LABELS``
        byte-for-byte (``left_shoulder``, NOT ``l_shoulder``).
        """
        estimator_labels = set(SyntheticBackend.KEYPOINT_LABELS)
        for coco_label in mapping.COCO_TO_NEUTRAL:
            assert coco_label in estimator_labels, (
                f"'{coco_label}' is not an exact estimator KEYPOINT_LABEL — "
                "the mapping would silently fall back to rest offset"
            )

    def test_every_row_value_is_a_canonical_bone(self) -> None:
        """ADR-001: every mapped value is a canonical skeleton bone name."""
        canonical = set(DEFAULT_NEUTRAL_SKELETON.bones)
        for coco_label, bone_name in mapping.COCO_TO_NEUTRAL.items():
            assert bone_name in canonical, (
                f"'{coco_label}' maps to '{bone_name}', which is not a canonical "
                "skeleton bone name"
            )

    def test_left_shoulder_and_right_hip_resolve_canonically(self) -> None:
        """The spec scenario: left_shoulder→LeftShoulder, right_hip→RightUpLeg."""
        assert mapping.COCO_TO_NEUTRAL["left_shoulder"] == "LeftShoulder"
        assert mapping.COCO_TO_NEUTRAL["right_hip"] == "RightUpLeg"

    def test_every_neutral_bone_is_mapped_or_derived_or_rest(self) -> None:
        """Full §14.2 coverage: every non-root bone is mapped, derived, or rest."""
        mapped = set(mapping.COCO_TO_NEUTRAL.values())
        all_bones = set(DEFAULT_NEUTRAL_SKELETON.bones) - {"Root"}
        assert mapped | DERIVED_BONES | REST_ONLY_BONES == all_bones

    def test_derived_and_rest_sets_do_not_overlap_mapped(self) -> None:
        """No bone is both a direct mapping and derived/rest."""
        mapped = set(mapping.COCO_TO_NEUTRAL.values())
        assert not (mapped & DERIVED_BONES)
        assert not (mapped & REST_ONLY_BONES)
        assert not (DERIVED_BONES & REST_ONLY_BONES)

    def test_eye_and_ear_labels_are_absent(self) -> None:
        """Pose-only labels (eyes/ears) must NOT be mapped to any bone."""
        assert "left_eye" not in mapping.COCO_TO_NEUTRAL
        assert "right_eye" not in mapping.COCO_TO_NEUTRAL
        assert "left_ear" not in mapping.COCO_TO_NEUTRAL
        assert "right_ear" not in mapping.COCO_TO_NEUTRAL

    def test_unknown_labels_are_ignored(self) -> None:
        """An unknown/arbitrary label should not appear in the mapping."""
        assert "left_big_toe" not in mapping.COCO_TO_NEUTRAL
        assert "l_shoulder" not in mapping.COCO_TO_NEUTRAL

    def test_mapping_is_frozen_and_immutable(self) -> None:
        """The table should be read-only (MappingProxyType)."""
        import types

        assert isinstance(mapping.COCO_TO_NEUTRAL, types.MappingProxyType)