"""Quaternion math shared by the animation domain (SDD §14, task 2.2).

Pure-stdlib rotation primitives in ``(w, x, y, z)`` order, promoted from the
inbetween-resampling module without behavior change (SDD §14 D4); the retarget
domain adds the Hamilton product (:func:`quat_multiply`) used to compose LOCAL
rotation offsets and axis corrections. Everything here operates on plain
tuples — no numpy/scipy (domain guardrail, AGENTS.md §3.1).
"""

import math

from aimation_actor_core.shared.types import Vec4

#: Threshold beyond which slerp degenerates (nearly parallel quaternions);
#: the division by ``sin(theta)`` would lose precision / produce NaN.
_SLERP_EPS: float = 1e-6


def quat_dot(qa: Vec4, qb: Vec4) -> float:
    """Dot product of two quaternions ``(w, x, y, z)``."""
    return qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3]


def quat_negate(q: Vec4) -> Vec4:
    """Negate a quaternion (``-q`` encodes the same rotation as ``q``)."""
    return (-q[0], -q[1], -q[2], -q[3])


def quat_normalize(q: Vec4) -> Vec4:
    """Rescale ``q`` to unit norm; a zero quaternion stays zero."""
    norm = math.sqrt(quat_dot(q, q))
    if norm == 0.0:
        return q
    inv = 1.0 / norm
    return (q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv)


def quat_multiply(qa: Vec4, qb: Vec4) -> Vec4:
    """Hamilton product of two quaternions ``(w, x, y, z)``.

    Order matters: composing the rotation ``qb`` *after* ``qa`` uses
    ``qa * qb``. The product of two unit quaternions is a unit quaternion.
    """
    w1, x1, y1, z1 = qa
    w2, x2, y2, z2 = qb
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def slerp(q0: Vec4, q1: Vec4, t: float) -> Vec4:
    """Spherical interpolation between two unit quaternions along the short arc.

    The far endpoint is sign-canonicalized first (``-q`` is the same rotation as
    ``q``): when the pair's dot product is negative the second endpoint is
    flipped, so the interpolation follows the short arc. Near-parallel pairs
    (``|dot| > 1 - 1e-6``, i.e. ``sin(theta) < 1e-6``) use normalized linear
    interpolation instead of slerp to avoid dividing by ~zero (anti-NaN). The
    result is a unit quaternion; endpoints are reproduced exactly at ``t=0``
    and ``t=1``.
    """
    # Canonicalize pre-interpolation: flip the far endpoint onto the short arc.
    dot = quat_dot(q0, q1)
    if dot < 0.0:
        q1 = quat_negate(q1)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))  # clamp float noise

    if dot > 1.0 - _SLERP_EPS:
        # Nearly parallel: nlerp — no acos/sin division, hence no NaN.
        blend = (
            q0[0] + t * (q1[0] - q0[0]),
            q0[1] + t * (q1[1] - q0[1]),
            q0[2] + t * (q1[2] - q0[2]),
            q0[3] + t * (q1[3] - q0[3]),
        )
        return quat_normalize(blend)

    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    if sin_theta < _SLERP_EPS:  # numerical guard; unreachable after clamp
        blend = (
            q0[0] + t * (q1[0] - q0[0]),
            q0[1] + t * (q1[1] - q0[1]),
            q0[2] + t * (q1[2] - q0[2]),
            q0[3] + t * (q1[3] - q0[3]),
        )
        return quat_normalize(blend)

    w0 = math.sin((1.0 - t) * theta) / sin_theta
    w1 = math.sin(t * theta) / sin_theta
    return (
        w0 * q0[0] + w1 * q1[0],
        w0 * q0[1] + w1 * q1[1],
        w0 * q0[2] + w1 * q1[2],
        w0 * q0[3] + w1 * q1[3],
    )