"""Math tests for :func:`retarget_motion` (SDD §14, task 2.7).

Synthetic motions over a canonical leg/arm chain pin the four pipeline passes:
height-ratio root scaling (①), per-bone rotation/scale (②/③), and the
translation-only foot-ground pass on Hips Y (④) — plus determinism and
invariants. Deep rotation semantics (LOCAL offsets, axis corrections) live in
``test_retarget_rotation.py`` (task 2.9).
"""

import pytest

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import (
    ContactFeed,
    FootContact,
    NeutralMeta,
    NeutralMotion,
)
from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton
from aimation_actor_core.domain.retargeting.map import RetargetEntry, RetargetMap
from aimation_actor_core.domain.retargeting.retarget import retarget_motion

#: Left leg chain rest Y sums to -90 -> the source root-to-ground height is 90.
SOURCE_GROUND_CM = 90.0

IDENTITY_ROT = (1.0, 0.0, 0.0, 0.0)
UNIT_Z_ROT = (0.0, 0.0, 0.7071067811865476, 0.7071067811865476)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _retarget_skeleton() -> Skeleton:
    """Canonical-ish skeleton: root, hips, both leg chains, one arm."""
    return Skeleton(
        bones={
            "Root": Bone(name="Root", parent=None, rest_position=(0.0, 0.0, 0.0)),
            "Hips": Bone(name="Hips", parent="Root", rest_position=(0.0, 0.0, 0.0)),
            "LeftUpLeg": Bone(name="LeftUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
            "LeftLeg": Bone(name="LeftLeg", parent="LeftUpLeg", rest_position=(0.0, -40.0, 0.0)),
            "LeftFoot": Bone(name="LeftFoot", parent="LeftLeg", rest_position=(0.0, -42.0, 0.0)),
            "RightUpLeg": Bone(name="RightUpLeg", parent="Hips", rest_position=(0.0, -8.0, 0.0)),
            "RightLeg": Bone(name="RightLeg", parent="RightUpLeg", rest_position=(0.0, -40.0, 0.0)),
            "RightFoot": Bone(name="RightFoot", parent="RightLeg", rest_position=(0.0, -42.0, 0.0)),
            "LeftArm": Bone(name="LeftArm", parent="Hips", rest_position=(-18.0, 10.0, 0.0)),
        }
    )


def _make_motion() -> NeutralMotion:
    """Two-frame motion at rest pose; Hips at (10, 20, 30) per frame."""
    transforms = {
        "Hips": Transform3D(translation=(10.0, 20.0, 30.0)),
        "LeftArm": Transform3D(translation=(-18.0, 10.0, 2.0)),
        "LeftUpLeg": Transform3D(translation=(0.0, -8.0, 0.0)),
        "LeftLeg": Transform3D(translation=(0.0, -40.0, 0.0)),
        "LeftFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
        "RightUpLeg": Transform3D(translation=(0.0, -8.0, 0.0)),
        "RightLeg": Transform3D(translation=(0.0, -40.0, 0.0)),
        "RightFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
    }
    frames = [
        Frame(frame=1, time=1.0 / 30.0, pose=Pose(transforms=dict(transforms))),
        Frame(frame=2, time=2.0 / 30.0, pose=Pose(transforms=dict(transforms))),
    ]
    return NeutralMotion(
        meta=NeutralMeta(fps=30.0, duration_frames=2),
        skeleton=_retarget_skeleton(),
        frames=frames,
    )


def _foot_motion(hips_y: float, contact_left: bool = False) -> NeutralMotion:
    """Single-frame motion; left chain world Y = hips_y - 9, right = hips_y - 15."""
    transforms = {
        "Hips": Transform3D(translation=(0.0, hips_y, 0.0)),
        "LeftUpLeg": Transform3D(translation=(0.0, -3.0, 0.0)),
        "LeftLeg": Transform3D(translation=(0.0, -3.0, 0.0)),
        "LeftFoot": Transform3D(translation=(0.0, -3.0, 0.0)),
        "RightUpLeg": Transform3D(translation=(0.0, -5.0, 0.0)),
        "RightLeg": Transform3D(translation=(0.0, -5.0, 0.0)),
        "RightFoot": Transform3D(translation=(0.0, -5.0, 0.0)),
    }
    contacts = {}
    if contact_left:
        contacts["left_foot"] = ContactFeed(samples=[FootContact(frame=1, contact=True)])
    return NeutralMotion(
        meta=NeutralMeta(fps=30.0, duration_frames=1),
        skeleton=_retarget_skeleton(),
        frames=[Frame(frame=1, time=1.0 / 30.0, pose=Pose(transforms=transforms))],
        contacts=contacts,
    )


# --------------------------------------------------------------------------- #
# ① Height-ratio root scaling
# --------------------------------------------------------------------------- #


class TestHeightRatio:
    def test_height_ratio_doubles_root_translation(self) -> None:
        """target 180 / source 90 -> Hips translation doubles on every frame."""
        rmap = RetargetMap(
            mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig")},
            scale_source_height=True,
            target_root_to_ground_cm=2.0 * SOURCE_GROUND_CM,
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].translation == (20.0, 40.0, 60.0)

    def test_height_ratio_halves_root_translation(self) -> None:
        """target 45 / source 90 -> Hips translation halves."""
        rmap = RetargetMap(
            mapping={},
            scale_source_height=True,
            target_root_to_ground_cm=SOURCE_GROUND_CM / 2.0,
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].translation == (5.0, 10.0, 15.0)

    def test_height_ratio_inert_when_scale_disabled(self) -> None:
        """scale_source_height=False leaves the root untouched even with a height."""
        rmap = RetargetMap(
            mapping={},
            scale_source_height=False,
            target_root_to_ground_cm=2.0 * SOURCE_GROUND_CM,
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].translation == (10.0, 20.0, 30.0)

    def test_height_ratio_inert_without_target_height(self) -> None:
        """No target height -> the ratio is unavailable, scaling stays inert."""
        rmap = RetargetMap(mapping={}, scale_source_height=True, target_root_to_ground_cm=None)
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].translation == (10.0, 20.0, 30.0)

    def test_use_root_translation_false_keeps_root(self) -> None:
        """use_root_translation=False opts the root out of height scaling."""
        rmap = RetargetMap(
            mapping={},
            use_root_translation=False,
            scale_source_height=True,
            target_root_to_ground_cm=2.0 * SOURCE_GROUND_CM,
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].translation == (10.0, 20.0, 30.0)


# --------------------------------------------------------------------------- #
# Passthrough, determinism, child-position guarantees
# --------------------------------------------------------------------------- #


class TestPassthroughDeterminism:
    def test_disabled_passthrough_identity(self) -> None:
        """An empty mapping with default flags reproduces the input motion."""
        motion = _make_motion()
        out = retarget_motion(motion, RetargetMap(mapping={}))
        assert out == motion
        out.validate_invariants()

    def test_run_twice_byte_identical(self) -> None:
        """retarget_motion is deterministic: two runs are byte-identical."""
        rmap = RetargetMap(
            mapping={
                "LeftArm": RetargetEntry(
                    target_name="arm_l_rig",
                    rotation_offset=UNIT_Z_ROT,
                    scale=(2.0, 3.0, 4.0),
                )
            },
            scale_source_height=True,
            target_root_to_ground_cm=2.0 * SOURCE_GROUND_CM,
        )
        motion = _make_motion()
        first = retarget_motion(motion, rmap)
        second = retarget_motion(motion, rmap)
        assert first == second
        assert first.model_dump_json() == second.model_dump_json()
        first.validate_invariants()

    def test_unmapped_bones_untouched(self) -> None:
        """Bones absent from the mapping keep their transforms verbatim."""
        rmap = RetargetMap(mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig")})
        motion = _make_motion()
        out = retarget_motion(motion, rmap)
        for frame in out.frames:
            for bone in ("Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightFoot"):
                assert frame.pose.transforms[bone] == motion.frames[0].pose.transforms[bone]

    def test_child_positions_untouched(self) -> None:
        """Height scaling moves the root only — child positions never change."""
        rmap = RetargetMap(
            mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig")},
            scale_source_height=True,
            target_root_to_ground_cm=2.0 * SOURCE_GROUND_CM,
        )
        motion = _make_motion()
        out = retarget_motion(motion, rmap)
        for frame in out.frames:
            assert frame.pose.transforms["LeftArm"].translation == (-18.0, 10.0, 2.0)
            assert frame.pose.transforms["LeftFoot"].translation == (0.0, -42.0, 0.0)


# --------------------------------------------------------------------------- #
# ②/③ Per-bone rotation and scale
# --------------------------------------------------------------------------- #


class TestPerBoneTransform:
    def test_per_bone_scale_applied(self) -> None:
        """An entry's scale factor multiplies the bone's scale component."""
        rmap = RetargetMap(
            mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig", scale=(2.0, 3.0, 4.0))}
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            arm = frame.pose.transforms["LeftArm"]
            assert arm.scale == (2.0, 3.0, 4.0)
            assert arm.rotation == IDENTITY_ROT

    def test_scale_never_affects_position(self) -> None:
        """Per-bone scale never leaks into translation (MVP constraint)."""
        rmap = RetargetMap(
            mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig", scale=(2.0, 0.5, 9.0))}
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["LeftArm"].translation == (-18.0, 10.0, 2.0)

    def test_unmapped_bone_scale_untouched(self) -> None:
        """A bone outside the mapping keeps its original scale."""
        rmap = RetargetMap(
            mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig", scale=(2.0, 2.0, 2.0))}
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["Hips"].scale == (1.0, 1.0, 1.0)

    def test_identity_source_rotation_stays_identity(self) -> None:
        """Rotation is never fabricated from an identity source (Decision C)."""
        rmap = RetargetMap(
            mapping={
                "LeftArm": RetargetEntry(
                    target_name="arm_l_rig",
                    rotation_offset=UNIT_Z_ROT,
                    axis_correction=(0.0, 1.0, 0.0, 0.0),
                )
            }
        )
        out = retarget_motion(_make_motion(), rmap)
        for frame in out.frames:
            assert frame.pose.transforms["LeftArm"].rotation == IDENTITY_ROT

    def test_unit_source_rotation_passes_through_pipeline(self) -> None:
        """A mapped non-identity unit rotation survives with identity offset."""
        rmap = RetargetMap(mapping={"LeftArm": RetargetEntry(target_name="arm_l_rig")})
        motion = _make_motion()
        motion = motion.model_copy(
            update={
                "frames": [
                    f.model_copy(
                        update={
                            "pose": Pose(
                                transforms={
                                    **f.pose.transforms,
                                    "LeftArm": f.pose.transforms["LeftArm"].model_copy(
                                        update={"rotation": UNIT_Z_ROT}
                                    ),
                                }
                            )
                        }
                    )
                    for f in motion.frames
                ]
            }
        )
        out = retarget_motion(motion, rmap)
        for frame in out.frames:
            assert frame.pose.transforms["LeftArm"].rotation == pytest.approx(UNIT_Z_ROT)


# --------------------------------------------------------------------------- #
# ④ Translation-only foot ground pass
# --------------------------------------------------------------------------- #


class TestFootGroundPass:
    def test_foot_ik_disabled_keeps_penetration(self) -> None:
        """foot_ik=False never alters Hips Y, even with penetrating feet."""
        motion = _foot_motion(hips_y=5.0)  # both feet world Y < 0
        out = retarget_motion(motion, RetargetMap(mapping={}))
        assert out.frames[0].pose.transforms["Hips"].translation == (0.0, 5.0, 0.0)

    def test_foot_ik_raises_hips_to_lowest_foot(self) -> None:
        """foot_ik=True lifts Hips so the lowest foot rests exactly on ground."""
        motion = _foot_motion(hips_y=5.0)  # deepest foot at -10 -> lift by 10
        out = retarget_motion(motion, RetargetMap(mapping={}, foot_ik=True))
        assert out.frames[0].pose.transforms["Hips"].translation == (0.0, 15.0, 0.0)

    def test_foot_ik_no_lift_when_grounded(self) -> None:
        """A grounded pose (lowest foot at world Y >= 0) is not lifted."""
        motion = _foot_motion(hips_y=15.0)  # right foot at 0 — grounded
        out = retarget_motion(motion, RetargetMap(mapping={}, foot_ik=True))
        assert out.frames[0].pose.transforms["Hips"].translation == (0.0, 15.0, 0.0)

    def test_foot_ik_contact_track_overrides_lowest_foot(self) -> None:
        """A contact-flagged foot is the ground reference, not the lowest one."""
        motion = _foot_motion(hips_y=5.0, contact_left=True)  # left at -4, right at -10
        out = retarget_motion(motion, RetargetMap(mapping={}, foot_ik=True))
        # Left foot reference only -> lift by 4, not 10.
        assert out.frames[0].pose.transforms["Hips"].translation == (0.0, 9.0, 0.0)

    def test_foot_ik_missing_foot_bones_is_noop(self) -> None:
        """Skeletons without foot bones bypass the ground pass entirely."""
        no_feet = Skeleton(
            bones={
                "Root": Bone(name="Root", parent=None, rest_position=(0.0, 0.0, 0.0)),
                "Hips": Bone(name="Hips", parent="Root", rest_position=(0.0, 0.0, 0.0)),
            }
        )
        motion = NeutralMotion(
            meta=NeutralMeta(fps=30.0, duration_frames=1),
            skeleton=no_feet,
            frames=[
                Frame(
                    frame=1,
                    time=1.0 / 30.0,
                    pose=Pose(transforms={"Hips": Transform3D(translation=(0.0, -5.0, 0.0))}),
                )
            ],
        )
        out = retarget_motion(motion, RetargetMap(mapping={}, foot_ik=True))
        assert out.frames[0].pose.transforms["Hips"].translation == (0.0, -5.0, 0.0)