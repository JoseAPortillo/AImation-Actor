"""Tests for the versioned NeutralMotion contract migration (ADR-001).

``meta.version`` bumps ``0.2`` → ``0.3``: producers write ``0.3`` with the
canonical ``Left…/Right…`` bone names (plan §14.2). Reading a stored ``0.2``
document migrates its legacy names deterministically; ``0.3`` passes through;
any other version is rejected with ``UnsupportedNeutralVersionError``. The
rename is an explicit table — never a naive ``L→Left``/``R→Right`` prefix
rewrite, so ``Root`` is never corrupted.
"""

from __future__ import annotations

import pytest

from aimation_actor_core.domain.animation.neutral_motion import (
    NeutralMotion,
    UnsupportedNeutralVersionError,
    migrate_neutral_motion,
)


def _legacy_zero_two_doc() -> dict:
    """A stored 0.2 document carrying legacy L/R bone names (ADR-001)."""
    return {
        "meta": {
            "version": "0.2",
            "fps": 24.0,
            "units": "cm",
            "up_axis": "Y",
            "source_type": "unknown",
            "duration_frames": 1,
            "style": "realistic_v1",
            "model_version": "",
            "graph_hash": "",
        },
        "skeleton": {
            "bones": {
                "Root": {
                    "name": "Root",
                    "parent": None,
                    "rest_position": (0.0, 0.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "Hips": {
                    "name": "Hips",
                    "parent": "Root",
                    "rest_position": (0.0, 0.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "LUpLeg": {
                    "name": "LUpLeg",
                    "parent": "Hips",
                    "rest_position": (0.0, -8.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "LLeg": {
                    "name": "LLeg",
                    "parent": "LUpLeg",
                    "rest_position": (0.0, -40.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "LFoot": {
                    "name": "LFoot",
                    "parent": "LLeg",
                    "rest_position": (0.0, -42.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "RUpLeg": {
                    "name": "RUpLeg",
                    "parent": "Hips",
                    "rest_position": (0.0, -8.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "RLeg": {
                    "name": "RLeg",
                    "parent": "RUpLeg",
                    "rest_position": (0.0, -40.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
                "RFoot": {
                    "name": "RFoot",
                    "parent": "RLeg",
                    "rest_position": (0.0, -42.0, 0.0),
                    "rest_rotation": (1.0, 0.0, 0.0, 0.0),
                },
            }
        },
        "frames": [
            {
                "frame": 1,
                "time": 1 / 24.0,
                "pose": {
                    "transforms": {
                        "LFoot": {
                            "translation": (0.0, -42.0, 0.0),
                            "rotation": (1.0, 0.0, 0.0, 0.0),
                            "scale": (1.0, 1.0, 1.0),
                        },
                        "RFoot": {
                            "translation": (0.0, -42.0, 0.0),
                            "rotation": (1.0, 0.0, 0.0, 0.0),
                            "scale": (1.0, 1.0, 1.0),
                        },
                    }
                },
            }
        ],
        "contacts": {},
        "keyposes": [],
        "tracking": {},
    }


def _zero_three_canonical_doc() -> dict:
    """A stored 0.3 document already carrying canonical names."""
    doc = _legacy_zero_two_doc()
    rename = {
        "LUpLeg": "LeftUpLeg",
        "LLeg": "LeftLeg",
        "LFoot": "LeftFoot",
        "RUpLeg": "RightUpLeg",
        "RLeg": "RightLeg",
        "RFoot": "RightFoot",
    }
    doc["meta"]["version"] = "0.3"
    bones = doc["skeleton"]["bones"]
    for legacy in rename:
        bone = bones[legacy]
        bone["name"] = rename[legacy]
        bones[rename[legacy]] = bone
        del bones[legacy]
    for bone in bones.values():
        if bone["parent"] in rename:
            bone["parent"] = rename[bone["parent"]]
    transforms = doc["frames"][0]["pose"]["transforms"]
    for legacy in rename:
        if legacy in transforms:
            transforms[rename[legacy]] = transforms.pop(legacy)
    return doc


class TestNeutralMotionVersion:
    """meta.version contract (ADR-001)."""

    def test_default_version_is_zero_three(self) -> None:
        """New NeutralMotion documents are version 0.3."""
        assert NeutralMotion().meta.version == "0.3"

    def test_zero_three_document_built_by_new_pipeline(self) -> None:
        """A 0.3 doc with canonical names loads unchanged (spec scenario)."""
        motion = NeutralMotion.model_validate(_zero_three_canonical_doc())
        assert motion.meta.version == "0.3"
        assert "LeftUpLeg" in motion.skeleton.bones
        assert "LFoot" not in motion.skeleton.bones


class TestMigrateNeutralMotion:
    """migrate_neutral_motion: the read-boundary coercion (ADR-001)."""

    def test_default_meta_version_is_zero_three(self) -> None:
        """NeutralMotion() constructor defaults to 0.3."""
        assert migrate_neutral_motion(NeutralMotion()).meta.version == "0.3"

    def test_zero_two_doc_migrates_skeleton_keys(self) -> None:
        """0.2 skeleton bone keys are renamed to canonical form."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        names = set(motion.skeleton.bones)
        assert names == {
            "Root",
            "Hips",
            "LeftUpLeg",
            "LeftLeg",
            "LeftFoot",
            "RightUpLeg",
            "RightLeg",
            "RightFoot",
        }

    def test_zero_two_doc_migrates_parent_references(self) -> None:
        """Parent references follow the renamed bones."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        assert motion.skeleton.bones["LeftFoot"].parent == "LeftLeg"
        assert motion.skeleton.bones["LeftLeg"].parent == "LeftUpLeg"
        assert motion.skeleton.bones["RightFoot"].parent == "RightLeg"

    def test_zero_two_doc_migrates_bone_names(self) -> None:
        """Bone.name matches the renamed dict key."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        assert motion.skeleton.bones["LeftFoot"].name == "LeftFoot"
        assert motion.skeleton.bones["RightUpLeg"].name == "RightUpLeg"

    def test_zero_two_doc_migrates_frame_transforms(self) -> None:
        """Frame pose transforms keyed by legacy names are renamed."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        transforms = motion.frames[0].pose.transforms
        assert set(transforms) == {"LeftFoot", "RightFoot"}

    def test_migrated_doc_bumps_version_and_validates(self) -> None:
        """Migration bumps meta.version to 0.3 and satisfies invariants."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        assert motion.meta.version == "0.3"
        motion.validate_invariants()  # raises on invalid

    def test_zero_two_rest_offsets_and_rotations_preserved(self) -> None:
        """Only names change — offsets and rotations are untouched."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        assert motion.skeleton.bones["LeftFoot"].rest_position == (0.0, -42.0, 0.0)
        assert motion.skeleton.bones["LeftFoot"].rest_rotation == (1.0, 0.0, 0.0, 0.0)
        assert motion.frames[0].pose.transforms["LeftFoot"].translation == (0.0, -42.0, 0.0)

    def test_zero_three_doc_passes_through(self) -> None:
        """0.3 docs are accepted as-is (no rename, no version churn)."""
        motion = migrate_neutral_motion(_zero_three_canonical_doc())
        assert motion.meta.version == "0.3"
        assert "LeftUpLeg" in motion.skeleton.bones
        assert "Hips" in motion.skeleton.bones

    def test_zero_three_instance_returns_identity(self) -> None:
        """A 0.3 NeutralMotion instance is returned unchanged (idempotent)."""
        motion = NeutralMotion()
        assert migrate_neutral_motion(motion) is motion

    def test_unknown_version_rejected(self) -> None:
        """Any version other than 0.2/0.3 raises UnsupportedNeutralVersionError."""
        doc = _legacy_zero_two_doc()
        doc["meta"]["version"] = "0.4"
        with pytest.raises(UnsupportedNeutralVersionError):
            migrate_neutral_motion(doc)

    def test_missing_version_rejected(self) -> None:
        """A doc with no version never silently migrates."""
        doc = _legacy_zero_two_doc()
        del doc["meta"]["version"]
        with pytest.raises(UnsupportedNeutralVersionError):
            migrate_neutral_motion(doc)

    def test_legacy_root_is_never_prefix_rewritten(self) -> None:
        """'Root' survives intact — no naive R→Right prefix rewrite (ADR-001)."""
        motion = migrate_neutral_motion(_legacy_zero_two_doc())
        assert "Root" in motion.skeleton.bones
        assert motion.skeleton.bones["Root"].name == "Root"
        assert "Rightoot" not in motion.skeleton.bones
        assert motion.skeleton.root == "Root"

    def test_migrate_is_deterministic(self) -> None:
        """Running the migration twice yields identical documents."""
        first = migrate_neutral_motion(_legacy_zero_two_doc())
        second = migrate_neutral_motion(_legacy_zero_two_doc())
        assert first.model_dump() == second.model_dump()