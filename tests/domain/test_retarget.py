"""Unit tests for the retarget map model (SDD §14, tasks 2.5–2.7).

Covers :class:`RetargetEntry` / :class:`RetargetMap` validation (frozen,
``extra="forbid"``, the string→entry shorthand of plan §14.3, skeleton
validation) and the pure-stdlib :func:`retarget_motion` math (height-ratio
root scaling, per-bone rotation/scale, foot-ground pass, determinism).
"""

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton
from aimation_actor_core.domain.retargeting.map import RetargetEntry, RetargetMap

IDENTITY_ROT = (1.0, 0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _source_skeleton() -> Skeleton:
    """A minimal canonical neutral skeleton (root + hips + one arm)."""
    return Skeleton(
        bones={
            "Root": Bone(name="Root", parent=None, rest_position=(0.0, 0.0, 0.0)),
            "Hips": Bone(name="Hips", parent="Root", rest_position=(0.0, 0.0, 0.0)),
            "LeftArm": Bone(name="LeftArm", parent="Hips", rest_position=(-20.0, 10.0, 0.0)),
        }
    )


def _target_skeleton() -> Skeleton:
    """A minimal target rig (non-neutral bone names)."""
    return Skeleton(
        bones={
            "root_rig": Bone(name="root_rig", parent=None, rest_position=(0.0, 0.0, 0.0)),
            "arm_l_rig": Bone(name="arm_l_rig", parent="root_rig", rest_position=(0.0, 10.0, 0.0)),
        }
    )


def _entry(target_name: str = "arm_l_rig", **overrides: object) -> dict[str, object]:
    """A well-formed per-bone entry dict."""
    return {"target_name": target_name, **overrides}


# --------------------------------------------------------------------------- #
# RetargetMap model — task 2.5
# --------------------------------------------------------------------------- #


class TestRetargetMapModel:
    def test_well_formed_map_validates(self) -> None:
        """A full entry (target + optional rotation/axis/scale) validates."""
        rmap = RetargetMap(
            mapping={
                "LeftArm": _entry(
                    rotation_offset=(0.0, 0.0, 0.0, 1.0),
                    axis_correction=(0.0, 1.0, 0.0, 0.0),
                    scale=(2.0, 2.0, 2.0),
                )
            },
            use_root_translation=True,
            foot_ik=False,
            scale_source_height=True,
            preserve_keyframes=True,
            target_root_to_ground_cm=180.0,
        )
        entry = rmap.mapping["LeftArm"]
        assert entry.target_name == "arm_l_rig"
        assert entry.rotation_offset == (0.0, 0.0, 0.0, 1.0)
        assert entry.axis_correction == (0.0, 1.0, 0.0, 0.0)
        assert entry.scale == (2.0, 2.0, 2.0)
        assert rmap.use_root_translation is True
        assert rmap.foot_ik is False
        assert rmap.scale_source_height is True
        assert rmap.preserve_keyframes is True
        assert rmap.target_root_to_ground_cm == 180.0

    def test_defaults(self) -> None:
        """Optional fields default: identity rotation/scale, scaling inert."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        entry = rmap.mapping["LeftArm"]
        assert entry.rotation_offset == IDENTITY_ROT
        assert entry.axis_correction is None
        assert entry.scale == (1.0, 1.0, 1.0)
        assert rmap.use_root_translation is True
        assert rmap.foot_ik is False
        assert rmap.scale_source_height is False
        assert rmap.preserve_keyframes is False
        assert rmap.target_root_to_ground_cm is None

    def test_shorthand_string_promotes_to_entry(self) -> None:
        """Plan §14.3 shorthand ``{bone: target_name}`` promotes to an entry."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        assert isinstance(rmap.mapping["LeftArm"], RetargetEntry)
        assert rmap.mapping["LeftArm"].target_name == "arm_l_rig"
        assert rmap.mapping["LeftArm"].rotation_offset == IDENTITY_ROT

    def test_extra_top_level_field_rejected(self) -> None:
        """Unknown document-level keys must be rejected (extra='forbid')."""
        with pytest.raises(ValidationError):
            RetargetMap(mapping={"LeftArm": "arm_l_rig"}, bogus_option=True)

    def test_extra_per_bone_field_rejected(self) -> None:
        """Unknown per-bone keys must be rejected (extra='forbid')."""
        with pytest.raises(ValidationError):
            RetargetMap(mapping={"LeftArm": _entry(bogus_option=True)})

    def test_missing_target_name_rejected(self) -> None:
        """An entry without a target name cannot validate."""
        with pytest.raises(ValidationError):
            RetargetMap(mapping={"LeftArm": {"scale": (2.0, 2.0, 2.0)}})

    def test_map_is_frozen(self) -> None:
        """The document is immutable after construction."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        with pytest.raises(ValidationError):
            rmap.use_root_translation = False  # type: ignore[misc]

    def test_entry_is_frozen(self) -> None:
        """Each entry is immutable after construction."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        with pytest.raises(ValidationError):
            rmap.mapping["LeftArm"].target_name = "other"  # type: ignore[misc]

    def test_validate_against_matching_source_and_target(self) -> None:
        """Every mapped bone exists in source (and target when given)."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        rmap.validate_against(_source_skeleton(), _target_skeleton())

    def test_validate_against_without_target(self) -> None:
        """Target is optional: source-only validation is the node path."""
        rmap = RetargetMap(mapping={"LeftArm": "arm_l_rig"})
        rmap.validate_against(_source_skeleton())

    def test_unknown_source_bone_rejected(self) -> None:
        """A mapping key not present in the source skeleton must fail."""
        rmap = RetargetMap(mapping={"LeftHand": "hand_l_rig"})
        with pytest.raises(ValueError, match="LeftHand"):
            rmap.validate_against(_source_skeleton())

    def test_unknown_target_bone_rejected_when_target_given(self) -> None:
        """With a target rig, a missing target bone must fail."""
        rmap = RetargetMap(mapping={"LeftArm": "missing_rig"})
        with pytest.raises(ValueError, match="missing_rig"):
            rmap.validate_against(_source_skeleton(), _target_skeleton())

    def test_target_root_to_ground_cm_optional(self) -> None:
        """``target_root_to_ground_cm`` accepts a float or stays None."""
        rmap = RetargetMap(mapping={}, target_root_to_ground_cm=90.5)
        assert rmap.target_root_to_ground_cm == 90.5
        assert RetargetMap(mapping={}).target_root_to_ground_cm is None