"""Coordinate conversions between the domain (Z-up) and FBX (Y-up).

The domain is **Z-up, right-handed, centimetres** (the ``Pelvis`` height lives on
``Z``). FBX's standard scene is **Y-up, right-handed, centimetres**. A single
rotation ``A = R_x(-90 deg)`` bridges them::

    A @ (x, y, z) == (x, z, -y)          # domain -> FBX
    A^-1 @ (x, y, z) == (x, -z, y)       # FBX -> domain

Vectors are mapped with ``A``; rotations (which are frame changes) are
*conjugated* by ``A``. This module holds that arithmetic in plain Python so both
the writer and the reader share it, and so it can be unit tested without Blender.

The module imports only the standard library and the domain models.
"""

from __future__ import annotations

import math

from aimation_actor.core.models import Quaternion, Vector3

Matrix3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]

#: Domain (Z-up) -> FBX (Y-up): ``R_x(-90 deg)``.
A: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
#: FBX (Y-up) -> domain (Z-up): the inverse of :data:`A`.
A_INV: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))

IDENTITY_QUATERNION = Quaternion(1.0, 0.0, 0.0, 0.0)

#: :data:`A` (`R_x(-90 deg)`) expressed as a unit quaternion.
A_Q = Quaternion(math.cos(math.radians(45)), -math.sin(math.radians(45)), 0.0, 0.0)

#: :data:`A_INV` (`R_x(+90 deg)`) expressed as a unit quaternion.
A_INV_Q = Quaternion(math.cos(math.radians(45)), math.sin(math.radians(45)), 0.0, 0.0)


def mat_mul(a: Matrix3, b: Matrix3) -> Matrix3:
    """Multiply two 3x3 matrices."""
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )  # type: ignore[return-value]


def mat_vec(m: Matrix3, v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Multiply a 3x3 matrix by a column vector."""
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def transpose(m: Matrix3) -> Matrix3:
    """Transpose a 3x3 matrix."""
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def quaternion_to_matrix(q: Quaternion) -> Matrix3:
    """Convert a quaternion to a rotation matrix."""
    w, x, y, z = q.w, q.x, q.y, q.z
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def matrix_to_euler_xyz_degrees(m: Matrix3) -> tuple[float, float, float]:
    """Decompose ``m = Rz(z) @ Ry(y) @ Rx(x)`` into ``(x, y, z)`` degrees.

    This is the convention FBX (and Blender's exporter) use for
    ``RotationOrder = XYZ``.
    """
    sin_y = max(-1.0, min(1.0, -m[2][0]))
    y = math.asin(sin_y)
    if abs(sin_y) < 0.999999:
        x = math.atan2(m[2][1], m[2][2])
        z = math.atan2(m[1][0], m[0][0])
    else:  # gimbal lock: fold the x rotation into z.
        x = math.atan2(-m[1][2], m[1][1])
        z = 0.0
    return math.degrees(x), math.degrees(y), math.degrees(z)


def quaternion_multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    """Hamilton product ``a * b`` (apply ``b`` first, then ``a``)."""
    return Quaternion(
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    )


def quaternion_conjugate(q: Quaternion) -> Quaternion:
    """The inverse rotation of a unit quaternion."""
    return Quaternion(q.w, -q.x, -q.y, -q.z)


def quaternion_normalized(q: Quaternion) -> Quaternion:
    """Return ``q`` scaled to unit length (identity if degenerate)."""
    norm = math.sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z)
    if norm == 0.0:
        return IDENTITY_QUATERNION
    return Quaternion(q.w / norm, q.x / norm, q.y / norm, q.z / norm)


def rotate_vector(q: Quaternion, v: Vector3) -> Vector3:
    """Rotate ``v`` by the unit quaternion ``q``."""
    w, x, y, z = q.w, q.x, q.y, q.z
    # t = 2 * (q_vec x v); v' = v + w*t + q_vec x t
    tx = 2.0 * (y * v.z - z * v.y)
    ty = 2.0 * (z * v.x - x * v.z)
    tz = 2.0 * (x * v.y - y * v.x)
    return Vector3(
        v.x + w * tx + (y * tz - z * ty),
        v.y + w * ty + (z * tx - x * tz),
        v.z + w * tz + (x * ty - y * tx),
    )


def to_fbx_vector(vector: Vector3) -> tuple[float, float, float]:
    """Rotate a domain (Z-up) vector into FBX space (Y-up)."""
    return mat_vec(A, (vector.x, vector.y, vector.z))


def to_domain_vector(x: float, y: float, z: float) -> Vector3:
    """Rotate an FBX (Y-up) vector into domain space (Z-up)."""
    dx, dy, dz = mat_vec(A_INV, (x, y, z))
    return Vector3(dx, dy, dz)


def rotation_to_fbx(q: Quaternion) -> Quaternion:
    """Reinterpret a domain (Z-up) local rotation as an FBX (Y-up) rotation."""
    return quaternion_normalized(
        quaternion_multiply(quaternion_multiply(A_Q, q), quaternion_conjugate(A_Q))
    )


def rotation_to_fbx_euler_degrees(q: Quaternion) -> tuple[float, float, float]:
    """Convert a domain quaternion to an FBX ``Lcl Rotation`` (Y-up, Euler XYZ)."""
    matrix = mat_mul(mat_mul(A, quaternion_to_matrix(q)), transpose(A))
    return matrix_to_euler_xyz_degrees(matrix)


def rotation_to_domain(q: Quaternion) -> Quaternion:
    """Reinterpret an FBX (Y-up) local rotation as a domain (Z-up) rotation."""
    return quaternion_normalized(
        quaternion_multiply(quaternion_multiply(A_INV_Q, q), quaternion_conjugate(A_INV_Q))
    )
