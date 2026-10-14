"""Small rotation helpers shared by the FBX tests (domain-space quaternions)."""

from __future__ import annotations

import math

from aimation_actor.core.models import Quaternion


def rotation_z(degrees: float) -> Quaternion:
    """A rotation of ``degrees`` about the (domain) ``Z`` axis."""
    half = math.radians(degrees) / 2.0
    return Quaternion(math.cos(half), 0.0, 0.0, math.sin(half))


def rotation_x(degrees: float) -> Quaternion:
    """A rotation of ``degrees`` about the (domain) ``X`` axis."""
    half = math.radians(degrees) / 2.0
    return Quaternion(math.cos(half), math.sin(half), 0.0, 0.0)


def rotation_y(degrees: float) -> Quaternion:
    """A rotation of ``degrees`` about the (domain) ``Y`` axis."""
    half = math.radians(degrees) / 2.0
    return Quaternion(math.cos(half), 0.0, math.sin(half), 0.0)


def rotation_xyz_120() -> Quaternion:
    """A 120-degree rotation about the ``(1, 1, 1)`` axis."""
    return Quaternion(0.5, 0.5, 0.5, 0.5)
