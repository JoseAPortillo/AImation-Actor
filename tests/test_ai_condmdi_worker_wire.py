"""The CondMDI wire's body quats: engine chain convention -> Maya locals.

The generated motion's rot columns encode ``Skeleton``'s OWN chain convention
(``data_loaders/humanml/common/skeleton.py``): the kinematic tree restarts the
accumulated chain rotation at the ROOT quat for every chain, so an L/R collar
is local to the pelvis-accumulated frame — its parent's (Spine_3) quat never
multiplies in. The Maya timeline consumes standard parent-relative locals, so
``_frame_to_wire`` must re-express the collar chain locals (verified by the
T5 conversion probe P3 on the engine's own FK).

Wire contract being pinned here (M6 T5):

- every body joint's ``quat`` conjugates back to a parent-relative local the
  Maya rig threads hierarchically;
- non-collar locals pass through unchanged (both conventions nest identically);
- the collars divide by their chain parent's accumulated quat;
- rebuilding the engine's chain accumulations from the wire locals through the
  plain Maya parent map reproduces them (the pose is the same world pose).
"""

from __future__ import annotations

from math import cos, sin

import pytest

from aimation_actor.adapters.ai import condmdi_worker as W


def _yaw(angle: float) -> tuple:
    return (cos(angle), 0.0, sin(angle), 0.0)


def _pitch(angle: float) -> tuple:
    return (cos(angle), sin(angle), 0.0, 0.0)


def _roll(angle: float) -> tuple:
    return (cos(angle), 0.0, 0.0, sin(angle))


def _tol() -> float:
    return 1e-9


# ---------------------------------------------------------------------------
# The engine's own chain convention (P3), restated for the wire conversion
# ---------------------------------------------------------------------------

_ENGINE_CHAINS = (
    ("R_Hip", "R_Knee", "R_Ankle", "R_Foot"),
    ("L_Hip", "L_Knee", "L_Ankle", "L_Foot"),
    ("Spine_1", "Spine_2", "Spine_3", "Neck", "Head"),
    ("L_Collar", "L_Shoulder", "L_Elbow", "L_Wrist"),
    ("R_Collar", "R_Shoulder", "R_Elbow", "R_Wrist"),
)


def _locals_fixture() -> dict[str, tuple]:
    """A distinctive deterministic local set (the 21 body joints)."""
    return {
        "L_Hip": _pitch(0.04),
        "R_Hip": _roll(0.02),
        "Spine_1": _yaw(0.05),
        "L_Knee": _pitch(0.01),
        "R_Knee": _roll(0.03),
        "Spine_2": _yaw(-0.02),
        "L_Ankle": _pitch(0.02),
        "R_Ankle": _roll(0.01),
        "Spine_3": _yaw(0.03),
        "L_Foot": _pitch(0.01),
        "R_Foot": _roll(0.02),
        "Neck": _yaw(-0.01),
        "L_Collar": _roll(0.12),
        "R_Collar": _roll(-0.11),
        "Head": _yaw(0.02),
        "L_Shoulder": _pitch(0.03),
        "R_Shoulder": _roll(0.02),
        "L_Elbow": _pitch(0.05),
        "R_Elbow": _roll(0.04),
        "L_Wrist": _pitch(0.02),
        "R_Wrist": _roll(0.03),
    }


def _engine_accs(root: tuple, locals_by_name: dict[str, tuple]) -> dict[str, tuple]:
    """The engine's ``Skeleton`` accumulation: every chain restarts at the root."""
    accs = {"Pelvis": root}
    for chain in _ENGINE_CHAINS:
        running = root
        for name in chain:
            running = W._quat_mul(running, locals_by_name[name])
            accs[name] = running
    return accs


def _wire_pose_of(root: tuple, locals_by_name: dict[str, tuple]) -> dict:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    order = W._OBSERVED_JOINTS[1:]
    rig = {"offsets": {"Pelvis": (0.0, 0.9, 0.0)}}
    return engine._frame_to_wire(
        rig, root, 1.0, [locals_by_name[name] for name in order]
    )


def _same_rotation(actual: list[float], expected: tuple) -> None:
    """Quaternion equality up to the antipodal sign and unit tolerance."""
    quat = W._quat_normalize((actual[0], actual[1], actual[2], actual[3]))
    target = W._quat_normalize(expected)
    aligned = max(
        abs(quat[i] - target[i]) for i in range(4)
    )
    opposed = max(
        abs(quat[i] + target[i]) for i in range(4)
    )
    best = min(aligned, opposed)
    assert best < _tol(), f"quat mismatch: {quat} vs {target}"


# ---------------------------------------------------------------------------
# The wire conversion
# ---------------------------------------------------------------------------


def test_the_wire_pelvis_carries_the_engine_root_and_height() -> None:
    root = W._quat_normalize(_yaw(0.2))
    pose = _wire_pose_of(root, _locals_fixture())
    assert pose["Main"] == {"quat": [1.0, 0.0, 0.0, 0.0], "trans": [0.0, 0.0, 0.0]}
    height_cm = 1.0 * 100.0 - 0.9 * 100.0
    assert pose["Pelvis"]["trans"] == [0.0, 0.0, pytest.approx(height_cm)]
    _same_rotation(pose["Pelvis"]["quat"], W._hml_rotation_to_domain(root))


def test_non_collar_wire_locals_pass_through_and_collars_retarget() -> None:
    root = W._quat_normalize(_yaw(0.2))
    locals_by_name = _locals_fixture()
    accs = _engine_accs(root, locals_by_name)
    pose = _wire_pose_of(root, locals_by_name)
    for name in locals_by_name:
        if name in ("L_Collar", "R_Collar"):
            # chain restart: the collar is local to the pelvis frame; the
            # Maya parent (Spine_3) carries the spine's own accumulation.
            expected = W._quat_mul(W._quat_inverse(accs["Spine_3"]), accs[name])
        else:
            expected = locals_by_name[name]
        _same_rotation(pose[name]["quat"], W._hml_rotation_to_domain(expected))


def test_maya_threading_of_the_wire_rebuilds_the_engine_pose() -> None:
    root = W._quat_normalize(_yaw(0.2))
    locals_by_name = _locals_fixture()
    accs = _engine_accs(root, locals_by_name)
    pose = _wire_pose_of(root, locals_by_name)
    threaded = {"Pelvis": root}
    for name in W._OBSERVED_JOINTS[1:]:
        parent = W._JOINT_PARENTS[name]
        local_hml = W._hml_local_rotation_from_domain(tuple(pose[name]["quat"]))
        threaded[name] = W._quat_mul(threaded[parent], local_hml)
        _same_rotation(
            list(threaded[name]),
            W._quat_normalize(accs[name]),
        )


# ---------------------------------------------------------------------------
# The canonical facing (the conditioning must start facing +Z)
# ---------------------------------------------------------------------------


def _canonical_engine():
    import numpy as np  # noqa: PLC0415

    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    engine.np = np
    return engine, np


def _frame_with_across(across: tuple):
    """A world frame whose engine across-vector equals ``across``.

    ``extract_features`` derives the facing from
    ``p[r_hip] - p[l_hip] + p[sdr_r] - p[sdr_l]``; setting the hips/shoulders
    accordingly pins the across the engine's own convention reads. The frame
    arrives as a numpy ``(22, 3)`` array, as ``fill`` passes it.
    """
    import numpy as np  # noqa: PLC0415

    frame = [[0.0, 0.0, 0.0]] * len(W._OBSERVED_JOINTS)
    r_hip = W._FACE_JOINTS[0]
    frame[r_hip] = list(across)
    return np.asarray(frame, dtype=np.float32)


def test_canonical_yaw_reads_the_engine_facing_convention() -> None:
    engine, np = _canonical_engine()
    # across = -X: the engine's forward (cross(Y, across)) is +Z -> yaw 0.
    zero_yaw = engine._canonical_yaw(_frame_with_across((-1.0, 0.0, 0.0)))
    assert zero_yaw == pytest.approx(0.0, abs=1e-9)
    # across = +Z: forward = +X -> yaw +pi/2.
    assert engine._canonical_yaw(_frame_with_across((0.0, 0.0, 1.0))) == pytest.approx(
        np.pi / 2, abs=1e-9
    )
    # a degenerate (near-zero) across falls back to 0 instead of exploding.
    assert engine._canonical_yaw(np.zeros((len(W._OBSERVED_JOINTS), 3), dtype=np.float32)) == 0.0


def test_yaw_rotate_dense_preserves_the_world_and_turns_the_facing() -> None:
    import math  # noqa: PLC0415

    engine, np = _canonical_engine()
    r_hip = W._FACE_JOINTS[0]
    frame = [[0.0, 0.3, 0.0]] * len(W._OBSERVED_JOINTS)
    frame[r_hip] = [-1.0, 0.3, 0.0]  # across = -X: facing +Z, zero yaw
    dense = np.asarray([frame], dtype=np.float32)

    yaw = engine._canonical_yaw(dense[0])
    assert yaw == pytest.approx(0.0, abs=1e-9)

    # rotating by +90 deg about the root axis lands the facing at +90 deg...
    turned = engine._yaw_rotate_dense(dense, math.pi / 2)
    assert engine._canonical_yaw(turned[0]) == pytest.approx(
        np.pi / 2, abs=1e-6
    )
    # ...the root stays on the axis (its own vertical) and keeps its height...
    assert turned[0, 0, 1] == pytest.approx(float(dense[0, 0, 1]))
    # ...and rotating back by the measured yaw restores the input exactly.
    restored = engine._yaw_rotate_dense(turned, -math.pi / 2)
    assert float(np.abs(restored - dense).max()) < 1e-5


def test_yaw_rotate_dense_leaves_the_height_untouched() -> None:
    engine, np = _canonical_engine()
    count = len(W._OBSERVED_JOINTS)
    dense = np.asarray(
        [
            [[0.0, 0.97, -0.5]]
            + [[0.0, 0.4, i * 0.1] for i in range(1, count)]
        ],
        dtype=np.float32,
    )
    rotated = engine._yaw_rotate_dense(dense, 1.234)
    assert rotated[0, :, 1] == pytest.approx(dense[0, :, 1], abs=1e-6)
