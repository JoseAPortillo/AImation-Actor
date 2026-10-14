"""Tests for the domain <-> FBX coordinate conversions."""

from __future__ import annotations

import math

import pytest
from fbx_helpers import rotation_x, rotation_y, rotation_z

from aimation_actor.adapters.io.fbx import transform
from aimation_actor.core.models import Quaternion, Vector3

_TOLERANCE = 1e-9


def _same_rotation(actual: Quaternion, expected: Quaternion) -> None:
    got = (actual.w, actual.x, actual.y, actual.z)
    want = (expected.w, expected.x, expected.y, expected.z)
    same = all(abs(a - b) <= _TOLERANCE for a, b in zip(got, want, strict=True))
    flipped = all(abs(a + b) <= _TOLERANCE for a, b in zip(got, want, strict=True))
    assert same or flipped, f"{got} is not {want} (up to sign)"


def _flat(matrix) -> list[float]:
    return [value for row in matrix for value in row]


def _quaternion_to_matrix(quaternion: Quaternion):
    return transform.quaternion_to_matrix(quaternion)


def test_a_maps_domain_up_axis_onto_fbx_up_axis() -> None:
    assert transform.to_fbx_vector(Vector3(z=100.0)) == pytest.approx((0.0, 100.0, 0.0))
    domain = transform.to_domain_vector(0.0, 100.0, 0.0)
    assert (domain.x, domain.y, domain.z) == pytest.approx((0.0, 0.0, 100.0))


def test_a_and_a_inverse_are_mutual_inverses() -> None:
    product = transform.mat_mul(transform.A, transform.A_INV)
    assert _flat(product) == pytest.approx([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])


def test_domain_z_rotation_becomes_fbx_y_rotation() -> None:
    half = math.radians(15)
    expected = Quaternion(math.cos(half), 0.0, math.sin(half), 0.0)
    _same_rotation(transform.rotation_to_fbx(rotation_z(30.0)), expected)


def test_rotation_conversion_round_trips() -> None:
    for quaternion in (rotation_z(30.0), rotation_x(60.0), Quaternion(0.5, 0.5, 0.5, 0.5)):
        converted = transform.rotation_to_fbx(quaternion)
        _same_rotation(transform.rotation_to_domain(converted), quaternion)


def test_euler_xyz_matches_fbx_axis_mapping() -> None:
    to_euler = transform.rotation_to_fbx_euler_degrees
    assert to_euler(rotation_z(30.0)) == pytest.approx((0.0, 30.0, 0.0))
    assert to_euler(rotation_x(60.0)) == pytest.approx((60.0, 0.0, 0.0))
    # The 120-deg (1, 1, 1) rotation lands on FBX's Y = 90 deg gimbal lock.
    assert to_euler(Quaternion(0.5, 0.5, 0.5, 0.5)) == pytest.approx((90.0, 90.0, 0.0))


def test_euler_decomposition_inverts_the_rz_ry_rx_construction() -> None:
    matrix = transform.mat_mul(
        _quaternion_to_matrix(rotation_z(90.0)),
        _quaternion_to_matrix(rotation_y(90.0)),
    )
    x, y, z = transform.matrix_to_euler_xyz_degrees(matrix)
    rebuilt = transform.mat_mul(
        transform.mat_mul(
            _quaternion_to_matrix(rotation_z(z)),
            _quaternion_to_matrix(rotation_y(y)),
        ),
        _quaternion_to_matrix(rotation_x(x)),
    )
    assert _flat(rebuilt) == pytest.approx(_flat(matrix), abs=1e-9)
