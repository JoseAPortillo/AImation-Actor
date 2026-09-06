"""Rotation rig tests (SDD §14, task 2.9).

Rig-grade semantics of :func:`apply_rotation` and
:func:`axis_correction_quat`: LOCAL rotation offsets (post-multiplied) on
*non-identity* sources only, the documented forward-axis correction pairs, and
the Decision-C guard that identity input is never fabricated into rotation.
"""

import math

import pytest

from aimation_actor_core.domain.retargeting.map import RetargetEntry
from aimation_actor_core.domain.retargeting.rotation import (
    apply_rotation,
    axis_correction_quat,
)
from aimation_actor_core.shared.types import Vec4

IDENTITY: Vec4 = (1.0, 0.0, 0.0, 0.0)

S = math.sqrt(2.0) / 2.0  # cos/sin of 45deg
INV_SQRT3 = 1.0 / math.sqrt(3.0)

#: 90deg about z.
Q_Z90: Vec4 = (S, 0.0, 0.0, S)
#: 90deg about x.
Q_X90: Vec4 = (S, S, 0.0, 0.0)
#: 180deg about y (the FBX(-Z) -> glTF(+Z) forward-axis flip).
Q_Y180: Vec4 = (0.0, 0.0, 1.0, 0.0)


def _entry(**overrides: object) -> RetargetEntry:
    return RetargetEntry(target_name="arm_l_rig", **overrides)


class TestApplyRotationIdentityGuard:
    def test_identity_source_never_fabricates(self) -> None:
        """Decision C: an identity source yields identity even with offset+axis."""
        out = apply_rotation(
            IDENTITY,
            _entry(rotation_offset=Q_X90, axis_correction=Q_Y180),
        )
        assert out == IDENTITY

    def test_identity_source_with_local_offset_stays_identity(self) -> None:
        """A LOCAL offset does not invent rotation where the source has none."""
        out = apply_rotation(IDENTITY, _entry(rotation_offset=Q_Z90))
        assert out == IDENTITY

    def test_identity_output_is_exact(self) -> None:
        """The guard returns the exact identity tuple, not a normalized look-alike."""
        assert apply_rotation(IDENTITY, _entry(rotation_offset=Q_X90)) == (1.0, 0.0, 0.0, 0.0)


class TestApplyRotationLocalOffset:
    def test_local_offset_post_multiplied_on_non_identity_source(self) -> None:
        """q' = q * offset (LOCAL): z90 then local x90 -> (0.5, 0.5, 0.5, 0.5)."""
        out = apply_rotation(Q_Z90, _entry(rotation_offset=Q_X90))
        assert out == pytest.approx((0.5, 0.5, 0.5, 0.5))

    def test_local_offset_is_not_global_order(self) -> None:
        """Local application must not equal the global (pre-multiplied) order."""
        local = apply_rotation(Q_Z90, _entry(rotation_offset=Q_X90))
        global_result = (0.0, 0.5, 0.0, 0.5)  # offset * rotation
        assert local != pytest.approx(global_result)

    def test_same_axis_local_offset_doubles_angle(self) -> None:
        """z90 applied in its own frame doubles to 180deg about z."""
        out = apply_rotation(Q_Z90, _entry(rotation_offset=Q_Z90))
        assert out == pytest.approx((0.0, 0.0, 0.0, 1.0))

    def test_identity_offset_keeps_unit_source(self) -> None:
        """With no offset/axis the unit source rotation is unchanged."""
        out = apply_rotation(Q_Z90, _entry())
        assert out == pytest.approx(Q_Z90)


class TestAxisCorrectionQuat:
    def test_fbx_to_gltf_is_half_turn_about_y(self) -> None:
        """FBX(-Z) -> glTF(+Z) is exactly 180deg about Y — the documented flip."""
        assert axis_correction_quat("fbx", "gltf") == Q_Y180
        assert axis_correction_quat("gltf", "fbx") == Q_Y180  # self-inverse

    def test_no_backwards_flip(self) -> None:
        """The correction is the half-turn pair, not a quarter-turn (sideways)."""
        correction = axis_correction_quat("fbx", "gltf")
        assert correction == (0.0, 0.0, 1.0, 0.0)
        assert correction[1] == 0.0  # about Y only — never about X/Z

    def test_yup_to_zup_is_plus_90_about_x(self) -> None:
        """yup -> zup raises the up axis: +90deg about X."""
        assert axis_correction_quat("yup", "zup") == pytest.approx((S, S, 0.0, 0.0))

    def test_zup_to_yup_is_minus_90_about_x(self) -> None:
        """zup -> yup lowers the up axis: -90deg about X."""
        assert axis_correction_quat("zup", "yup") == pytest.approx((S, -S, 0.0, 0.0))

    def test_same_convention_is_identity(self) -> None:
        """No reorientation needed when source and target share a convention."""
        assert axis_correction_quat("fbx", "fbx") == IDENTITY
        assert axis_correction_quat("yup", "yup") == IDENTITY

    def test_unknown_pair_rejected(self) -> None:
        """Pairs outside the documented table must fail loudly."""
        for pair in (("yup", "gltf"), ("fbx", "zup"), ("zup", "gltf")):
            with pytest.raises(ValueError):
                axis_correction_quat(*pair)


class TestApplyRotationAxisCorrection:
    def test_axis_correction_pre_multiplied(self) -> None:
        """q' = normalize(axis * q * offset): axis applies in global space."""
        out = apply_rotation(Q_Z90, _entry(axis_correction=Q_Y180))
        # (0,0,1,0) * (s,0,0,s) = (0, s, s, 0) — already unit.
        assert out == pytest.approx((0.0, S, S, 0.0))

    def test_offset_and_axis_compose(self) -> None:
        """q' = normalize(axis * q * offset) — both terms are applied."""
        out = apply_rotation(Q_Z90, _entry(axis_correction=Q_Y180, rotation_offset=Q_X90))
        base = (0.0, S, S, 0.0)  # axis * q (no offset yet)
        assert out != pytest.approx(base)
        # (0,s,s,0) * (s,s,0,0) = (-1/2, 1/2, 1/2, -1/2).
        assert out == pytest.approx((-0.5, 0.5, 0.5, -0.5))

    def test_result_is_unit(self) -> None:
        """apply_rotation always returns a unit quaternion."""
        for rotation in (Q_Z90, (0.0, 0.0, 1.0, 0.0), (0.0, S, 0.0, S)):
            out = apply_rotation(rotation, _entry(rotation_offset=Q_X90, axis_correction=Q_Y180))
            norm = math.sqrt(sum(c * c for c in out))
            assert norm == pytest.approx(1.0, abs=1e-9)