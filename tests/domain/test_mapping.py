"""Tests for the COCO→neutral bone mapping table (REQ-1).

The mapping bridges the estimator's COCO 17 keypoint labels to the §14.2
neutral skeleton. The 13 distal-end rows are exact COCO strings; derived and
rest-only bones complete full skeleton coverage; pose-only labels (eyes,
ears) and unknown labels are intentionally absent/ignored.
"""

from __future__ import annotations

from aimation_actor_core.domain.animation import mapping
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.infrastructure.ai_models.estimators import SyntheticBackend

EXPECTED_ROWS: set[tuple[str, str]] = {
    ("nose", "Head"),
    ("left_shoulder", "LShoulder"),
    ("right_shoulder", "RShoulder"),
    ("left_elbow", "LArm"),
    ("right_elbow", "RArm"),
    ("left_wrist", "LForeArm"),
    ("right_wrist", "RForeArm"),
    ("left_hip", "LUpLeg"),
    ("right_hip", "RUpLeg"),
    ("left_knee", "LLeg"),
    ("right_knee", "RLeg"),
    ("left_ankle", "LFoot"),
    ("right_ankle", "RFoot"),
}

# Bones with no 1:1 COCO landmark; they keep their neutral rest offset.
REST_ONLY_BONES = {
    "Spine",
    "Chest",
    "Neck",
    "LHand",
    "RHand",
    "LToeBase",
    "RToeBase",
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
