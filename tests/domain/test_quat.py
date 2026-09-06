"""Unit tests for :mod:`aimation_actor_core.domain.animation.quat` (SDD §14, task 2.1).

The quaternion helpers are the canonical implementation of the rotation math
shared by inbetween resampling (promoted, no behavior change) and the
retargeting domain (which adds the Hamilton product). These tests pin the
public contract: unit-norm invariants, short-arc slerp with anti-NaN
near-parallel fallback, and the Hamilton multiply used for offset/axis
composition.
"""

import math

import pytest

from aimation_actor_core.domain.animation.quat import (
    quat_dot,
    quat_multiply,
    quat_negate,
    quat_normalize,
    slerp,
)
from aimation_actor_core.shared.types import Vec4

#: Identity quaternion ``(w, x, y, z)``.
IDENTITY: Vec4 = (1.0, 0.0, 0.0, 0.0)


def _norm(q: Vec4) -> float:
    """Euclidean norm of a quaternion."""
    return math.sqrt(quat_dot(q, q))


class TestQuatNormalize:
    def test_normalize_produces_unit_norm(self) -> None:
        """Any non-zero quaternion is rescaled to unit norm."""
        for q in ((2.0, 0.0, 0.0, 0.0), (0.0, 3.0, 4.0, 0.0), (1.0, 2.0, -2.0, 4.0)):
            unit = quat_normalize(q)
            assert _norm(unit) == pytest.approx(1.0, abs=1e-9)
            # Direction preserved: unit is q scaled by a positive scalar.
            assert quat_dot(unit, q) > 0.0

    def test_normalize_identity_is_identity(self) -> None:
        """The identity quaternion passes through unchanged."""
        assert quat_normalize(IDENTITY) == IDENTITY

    def test_normalize_zero_quat_stays_zero(self) -> None:
        """A zero quaternion stays zero (no division by zero, no NaN)."""
        zero: Vec4 = (0.0, 0.0, 0.0, 0.0)
        assert quat_normalize(zero) == zero


class TestQuatDot:
    def test_dot_is_symmetric(self) -> None:
        """``quat_dot(a, b) == quat_dot(b, a)`` — the dot product is commutative."""
        a: Vec4 = (0.5, -0.25, 0.75, 0.125)
        b: Vec4 = (0.1, 0.9, 0.05, 0.4)
        assert quat_dot(a, b) == pytest.approx(quat_dot(b, a))

    def test_dot_reference_value(self) -> None:
        """Hand-computed reference: w1w2 + x1x2 + y1y2 + z1z2."""
        a: Vec4 = (1.0, 2.0, 3.0, 4.0)
        b: Vec4 = (5.0, 6.0, 7.0, 8.0)
        assert quat_dot(a, b) == pytest.approx(70.0)

    def test_dot_with_negated_quat_is_negated(self) -> None:
        """``dot(q, -q) = -dot(q, q)`` — the negation primitive is consistent."""
        q: Vec4 = (0.3, 0.6, -0.2, 0.9)
        assert quat_dot(q, quat_negate(q)) == pytest.approx(-quat_dot(q, q))
        assert quat_negate(quat_negate(q)) == q


class TestQuatMultiply:
    def test_multiply_left_identity(self) -> None:
        """``quat_multiply(identity, q) == q`` — identity is a left unit."""
        q: Vec4 = (0.2, -0.3, 0.4, 0.5)
        assert quat_multiply(IDENTITY, q) == pytest.approx(q)

    def test_multiply_right_identity(self) -> None:
        """``quat_multiply(q, identity) == q`` — identity is a right unit."""
        q: Vec4 = (0.2, -0.3, 0.4, 0.5)
        assert quat_multiply(q, IDENTITY) == pytest.approx(q)

    def test_multiply_hamilton_reference(self) -> None:
        """Hamilton product of two 90-degree rotations (known reference).

        ``qx = 90deg about X``, ``qy = 90deg about Y`` →
        ``qx * qy = (0.5, 0.5, 0.5, 0.5)`` (unit quaternion).
        """
        qx: Vec4 = (math.sqrt(2.0) / 2.0, math.sqrt(2.0) / 2.0, 0.0, 0.0)
        qy: Vec4 = (math.sqrt(2.0) / 2.0, 0.0, math.sqrt(2.0) / 2.0, 0.0)
        assert quat_multiply(qx, qy) == pytest.approx((0.5, 0.5, 0.5, 0.5))

    def test_multiply_of_unit_quats_is_unit(self) -> None:
        """The product of two unit quaternions is a unit quaternion."""
        qx: Vec4 = (math.sqrt(2.0) / 2.0, math.sqrt(2.0) / 2.0, 0.0, 0.0)
        qy: Vec4 = (math.sqrt(2.0) / 2.0, 0.0, math.sqrt(2.0) / 2.0, 0.0)
        assert _norm(quat_multiply(qx, qy)) == pytest.approx(1.0, abs=1e-9)


class TestSlerpEndpoints:
    def test_endpoint_zero_reproduces_start(self) -> None:
        """``slerp(q0, q1, 0) == q0`` exactly."""
        q0: Vec4 = (0.0, 0.0, 0.0, 1.0)
        q1: Vec4 = (0.0, 1.0, 0.0, 0.0)
        assert slerp(q0, q1, 0.0) == pytest.approx(q0)

    def test_endpoint_one_reproduces_end(self) -> None:
        """``slerp(q0, q1, 1) == q1`` (short-arc canonicalized)."""
        q0: Vec4 = (0.0, 0.0, 0.0, 1.0)
        q1: Vec4 = (0.0, 1.0, 0.0, 0.0)
        assert slerp(q0, q1, 1.0) == pytest.approx(q1)

    def test_slerp_short_arc_with_negative_dot_pair(self) -> None:
        """Slerping the negated 120deg-about-z quaternion follows the 60deg short arc.

        ``-q`` encodes the same rotation as ``q``, so a pair with negative dot
        must interpolate the short way: the midpoint of (identity, -120deg-z)
        is the 60deg rotation, not the 120deg one.
        """
        q0: Vec4 = IDENTITY
        q_neg: Vec4 = quat_negate(
            (
                math.cos(math.radians(60.0)),
                0.0,
                0.0,
                math.sin(math.radians(60.0)),
            )
        )
        assert quat_dot(q0, q_neg) < 0.0
        mid = slerp(q0, q_neg, 0.5)
        # 60deg about z: (cos30, 0, 0, sin30) — positive dot with identity.
        reference: Vec4 = (
            math.cos(math.radians(30.0)),
            0.0,
            0.0,
            math.sin(math.radians(30.0)),
        )
        assert quat_dot(mid, reference) == pytest.approx(1.0, abs=1e-6)


class TestSlerpNearParallel:
    def test_nlerp_identical_quats_no_nan(self) -> None:
        """``slerp(q, q, 0.5)`` must not produce NaN (near-parallel → nlerp)."""
        q: Vec4 = (0.0, 0.7071067811865476, 0.0, 0.7071067811865476)
        mid = slerp(q, q, 0.5)
        assert all(math.isfinite(v) for v in mid)
        assert _norm(mid) == pytest.approx(1.0, abs=1e-9)
        assert mid == pytest.approx(q)

    def test_nlerp_nearly_parallel_no_nan(self) -> None:
        """Nearly parallel pair (dot just below 1) interpolates without NaN."""
        q0: Vec4 = (1.0, 0.0, 0.0, 0.0)
        q1: Vec4 = (1.0 - 1e-7, 5e-8, 0.0, 0.0)
        assert quat_dot(q0, q1) > 1.0 - 1e-6
        for t in (0.25, 0.5, 0.75):
            mid = slerp(q0, q1, t)
            assert all(math.isfinite(v) for v in mid)
            assert _norm(mid) == pytest.approx(1.0, abs=1e-6)

    def test_slerp_output_is_always_unit(self) -> None:
        """Slerp between perpendicular rotations stays on the unit sphere."""
        q0: Vec4 = (1.0, 0.0, 0.0, 0.0)
        q1: Vec4 = (0.0, 0.0, 0.0, 1.0)
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert _norm(slerp(q0, q1, t)) == pytest.approx(1.0, abs=1e-9)