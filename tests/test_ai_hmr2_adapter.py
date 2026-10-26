"""Tests for the HMR2.0 adapter (M5 T11/T12): the subprocess bridge, the typed
actionable failures (S6, S7, S14, S16), and the engine-result -> WorldPose
conversion.

The real engine needs CUDA and 2.7 GB of weights, so these tests drive the
bridge through ``tests/fake_hmr2_worker.py`` on the plain interpreter; the real
engine is exercised by an untracked manual probe, like the Blender read path
(NFR-04).
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

from aimation_actor.adapters.ai.hmr2_adapter import (
    Hmr2Adapter,
    Hmr2EngineError,
    _quaternion_multiply,
    conjugate_y_up_to_z_up,
    quaternion_from_matrix,
    quaternion_rotate,
)
from aimation_actor.core.models import FrameImage, Quaternion


def _assert_same_rotation(got: Quaternion, w: float, x: float, y: float, z: float) -> None:
    """Quaternion identity up to the double cover: same rotated vectors."""
    got_tuple = (got.w, got.x, got.y, got.z)
    for vector in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        rotated = quaternion_rotate(got_tuple, vector)
        reference = quaternion_rotate((w, x, y, z), vector)
        assert rotated == pytest.approx(reference)

_FAKE_WORKER = Path(__file__).resolve().parent / "fake_hmr2_worker.py"
_TEMPLATE_HIP_CM = 93.85


def _frame() -> FrameImage:
    return FrameImage(width=4, height=4, rgb=bytes(48))


def _adapter(tmp_path: Path, mode: str) -> Hmr2Adapter:
    """An adapter whose 'engine' is the fake worker on this interpreter."""
    checkpoint = tmp_path / "checkpoint.ckpt"
    checkpoint.write_bytes(b"fake")
    smpl_dir = tmp_path / "smpl"
    smpl_dir.mkdir(exist_ok=True)
    (smpl_dir / "SMPL_NEUTRAL.pkl").write_bytes(b"fake")
    pid_file = tmp_path / "worker.pid"
    died_marker = tmp_path / "died.marker"
    return Hmr2Adapter(
        engine_root=None,
        python_executable=sys.executable,
        worker_script=_FAKE_WORKER,
        checkpoint=checkpoint,
        smpl_dir=smpl_dir,
        env=dict(
            os.environ,
            FAKE_HMR2_WORKER_MODE=mode,
            FAKE_PID_FILE=str(pid_file),
            FAKE_DIED_MARKER=str(died_marker),
        ),
        pid_file=pid_file,
    )


# -- typed, actionable failures (S6, S7, S16) --------------------------------- #


def test_a_missing_engine_python_names_the_fix(tmp_path: Path) -> None:
    adapter = Hmr2Adapter(engine_root=tmp_path / "nowhere")
    with pytest.raises(Hmr2EngineError) as raised:
        adapter.extract_pose(_frame(), frame_index=0)
    message = str(raised.value)
    assert "python" in message.lower()
    assert "AIMATION_ENGINE_ROOT" in message


def test_a_missing_checkpoint_is_actionable(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    adapter.checkpoint = tmp_path / "absent.ckpt"
    with pytest.raises(Hmr2EngineError) as raised:
        adapter.extract_pose(_frame(), frame_index=0)
    assert "absent.ckpt" in str(raised.value)


def test_a_missing_body_model_is_actionable(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    adapter.smpl_dir = tmp_path / "absent-smpl"
    with pytest.raises(Hmr2EngineError) as raised:
        adapter.extract_pose(_frame(), frame_index=0)
    assert "SMPL" in str(raised.value)


def test_a_ready_error_surfaces_as_a_typed_failure(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ready_error")
    with pytest.raises(Hmr2EngineError) as raised:
        adapter.extract_pose(_frame(), frame_index=0)
    assert "no CUDA GPU" in str(raised.value)


# -- the bridge --------------------------------------------------------------- #


def test_a_request_returns_a_world_pose(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    try:
        pose = adapter.extract_pose(_frame(), frame_index=7)
        assert pose.translation.z == pytest.approx(_TEMPLATE_HIP_CM)
        # The world displacement the engine recovered is deliberately dropped.
        assert (pose.translation.x, pose.translation.y) == (0.0, 0.0)
        # The pose is a DOMAIN pose: a joint name maps to the domain's
        # ``Quaternion``, not the adapter's internal ``(w, x, y, z)`` tuples.
        # A tuple here crashes the pure domain downstream (``kinematics``
        # reads ``.w``), so the contract of ``WorldPose.rotations`` is the
        # regression this pins (found by the real-engine UI check, M5 L27).
        rotation = pose.rotations["Pelvis"]
        assert isinstance(rotation, Quaternion)
        # The pelvis's rotation is the engine's global orientation minus the
        # camera-frame half-turn the network bakes into it (T15): the canned
        # upright person lands at the identity in the domain.
        _assert_same_rotation(rotation, 1.0, 0.0, 0.0, 0.0)
    finally:
        adapter.shutdown()


def test_a_second_extraction_reuses_the_same_worker(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    try:
        adapter.extract_pose(_frame(), frame_index=0)
        first_pid = int(adapter.pid_file.read_text())
        adapter.extract_pose(_frame(), frame_index=1)
        second_pid = int(adapter.pid_file.read_text())
        assert first_pid == second_pid
    finally:
        adapter.shutdown()


def test_a_worker_death_mid_request_is_a_typed_failure_and_then_respawns(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "die_once")
    with pytest.raises(Hmr2EngineError):
        adapter.extract_pose(_frame(), frame_index=0)
    # The dead worker is discarded, so the next call starts a fresh one.
    assert adapter._worker is None
    first_pid = int(adapter.pid_file.read_text())
    try:
        pose = adapter.extract_pose(_frame(), frame_index=1)
        assert pose.translation.z == pytest.approx(_TEMPLATE_HIP_CM)
        # The serving process is a new one: the respawn is real, not replayed.
        respawned_pid = int(adapter.pid_file.read_text())
        assert respawned_pid != first_pid
    finally:
        adapter.shutdown()


def test_a_timed_out_worker_is_terminated_not_orphaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # R3/R4-2: a hung engine must not survive the timeout holding its VRAM.
    monkeypatch.setattr("aimation_actor.adapters.ai.hmr2_adapter._REQUEST_TIMEOUT_S", 0.5)
    adapter = _adapter(tmp_path, "hang")
    with pytest.raises(Hmr2EngineError):
        adapter.extract_pose(_frame(), frame_index=0)
    adapter.shutdown()  # must be a no-op for cleanup: the process is already gone
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(adapter.pid_file.read_text()))
    assert not handle, "the timed-out worker process should be terminated"


def test_shutdown_terminates_the_worker(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    adapter.extract_pose(_frame(), frame_index=0)
    worker_pid = int(adapter.pid_file.read_text())
    adapter.shutdown()
    # The fake's durable witness: its pid file. The process must be gone.
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, worker_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    assert not handle, "the worker process should be terminated"


# -- the conversion (T12) ----------------------------------------------------- #


def test_a_rotation_matrix_becomes_a_unit_quaternion() -> None:
    angle = math.radians(90.0)
    matrix = [
        1.0, 0.0, 0.0,
        0.0, math.cos(angle), -math.sin(angle),
        0.0, math.sin(angle), math.cos(angle),
    ]
    w, x, y, z = quaternion_from_matrix(matrix)
    assert (w, x, y, z) == pytest.approx((math.cos(angle / 2), math.sin(angle / 2), 0.0, 0.0))


def test_the_axis_conjugation_keeps_rotations_about_x_unchanged() -> None:
    # Both frames' X axes agree; SMPL's Y-up axis change only swaps Y and Z.
    angle = math.radians(90.0)
    matrix = [
        1.0, 0.0, 0.0,
        0.0, math.cos(angle), -math.sin(angle),
        0.0, math.sin(angle), math.cos(angle),
    ]
    q_smpl = quaternion_from_matrix(matrix)
    q_domain = conjugate_y_up_to_z_up(q_smpl)
    assert tuple(q_domain) == pytest.approx(tuple(q_smpl))


def test_a_y_rotation_becomes_the_same_rotation_about_the_domain_up_axis() -> None:
    # SMPL: a +90-degree rotation about the up axis (+Y, right-handed) turns
    # forward (+Z) into right (+X). In the Z-up domain the same physical
    # rotation must be a +90-degree rotation about +Z.  The domain's forward is
    # -Y under the axis change; both must take forward to right.
    angle = math.radians(90.0)
    y_up = [
        math.cos(angle), 0.0, math.sin(angle),
        0.0, 1.0, 0.0,
        -math.sin(angle), 0.0, math.cos(angle),
    ]
    z_up_same_turn = [
        0.0, -1.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 0.0, 1.0,
    ]
    q_smpl = quaternion_from_matrix(y_up)
    q_domain = conjugate_y_up_to_z_up(q_smpl)
    assert tuple(q_domain) == pytest.approx(tuple(quaternion_from_matrix(z_up_same_turn)))
    # Behavioral mirror: forward goes to right in both frames.
    smpl_forward_to_right = quaternion_rotate(q_smpl, (0.0, 0.0, 1.0))
    # The domain's forward is (0, -1, 0) under the axis change: the FBX writer's
    # A = R_x(-90) sends domain (x, y, z) to SMPL space.
    domain_forward_to_right = quaternion_rotate(q_domain, (0.0, -1.0, 0.0))
    assert tuple(domain_forward_to_right) == pytest.approx(tuple(smpl_forward_to_right))


def test_the_fbx_writer_conjugates_back_to_the_smpl_rotation() -> None:
    # Pipeline invariant: the FBX writer converts domain (Z-up) rotations into
    # FBX's Y-up frame with A = R_x(-90°)  (q_fbx = A q_domain A^-1).  SMPL is
    # Y-up like FBX, so conjugating the adapted pose back must reproduce the
    # engine's rotation exactly.
    angle = math.radians(37.0)
    arbitrary = [
        math.cos(angle), 0.0, math.sin(angle),
        0.0, 1.0, 0.0,
        -math.sin(angle), 0.0, math.cos(angle),
    ]
    q_smpl = quaternion_from_matrix(arbitrary)
    q_domain = conjugate_y_up_to_z_up(q_smpl)
    half = math.radians(-90.0)
    fbx_axis_change = quaternion_from_matrix([
        1.0, 0.0, 0.0,
        0.0, math.cos(half), -math.sin(half),
        0.0, math.sin(half), math.cos(half),
    ])
    aw, ax, ay, az = fbx_axis_change
    inverse_axis = (aw, -ax, -ay, -az)  # A's conjugate: A^-1 = R_x(+90)
    q_fbx = _quaternion_multiply(fbx_axis_change, _quaternion_multiply(q_domain, inverse_axis))
    assert tuple(q_fbx) == pytest.approx(tuple(q_smpl))


# -- the global-orient frame convention (T15: the upside-down capture) --------- #


def _upright_global_orient_matrix() -> list[float]:
    """R_x(180) — the global orient the real engine reports for a person
    standing upright in the image (measured on the bundled clip: 179.2 deg)."""
    return [
        1.0, 0.0, 0.0,
        0.0, -1.0, 0.0,
        0.0, 0.0, -1.0,
    ]


def _world_pose_adapter(tmp_path: Path) -> Hmr2Adapter:
    """An adapter without the subprocess, ready-line-only, for conversion tests."""
    adapter = _adapter(tmp_path, "ok")
    adapter._ready = {
        "template_hip_height_cm": _TEMPLATE_HIP_CM,
        "bind_offsets_cm": {},
    }
    adapter._worker = None
    return adapter


def test_an_upright_person_stays_upright(tmp_path: Path) -> None:
    """The engine's output frame is the camera's (Y down); for an upright
    person it encodes the vertical flip inside the global orient, so the
    adapter must undo it on the pelvis only. Measured: global orient
    ~179-180 deg, Head below Pelvis in the raw axes, demo renderer applies
    R_x(180) to the mesh (the bundled `adjudicate frame` probes)."""
    adapter = _world_pose_adapter(tmp_path)
    try:
        pose = adapter._to_world_pose(
            {
                "rotations": {
                    "Pelvis": _upright_global_orient_matrix(),
                    "L_Hip": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                },
            }
        )
        pelvis = pose.rotations["Pelvis"]
        # ±1 double cover: F @ F is the identity as a rotation
        _assert_same_rotation(pelvis, 1.0, 0.0, 0.0, 0.0)
    finally:
        adapter.shutdown()


def test_body_pose_locals_bypass_the_global_frame_flip(tmp_path: Path) -> None:
    """The camera-frame flip lives in the global orient alone: the body-pose
    locals are parent-relative and keep the pre-existing conversion."""
    adapter = _world_pose_adapter(tmp_path)
    try:
        angle = math.radians(30.0)
        cos, sin = math.cos(angle), math.sin(angle)
        matrix = [
            1.0, 0.0, 0.0,
            0.0, cos, -sin,
            0.0, sin, cos,
        ]
        pose = adapter._to_world_pose(
            {
                "rotations": {
                    "Pelvis": _upright_global_orient_matrix(),
                    "L_Hip": matrix,
                },
            }
        )
        expected = Quaternion(*conjugate_y_up_to_z_up(quaternion_from_matrix(matrix)))
        got = pose.rotations["L_Hip"]
        assert (got.w, got.x, got.y, got.z) == pytest.approx(
            (expected.w, expected.x, expected.y, expected.z)
        )
    finally:
        adapter.shutdown()


def test_root_translation_is_converted_to_domain_axes(tmp_path: Path) -> None:
    """The engine reports translations in its camera's Y-down frame (T15).

    The camera frame first flips by ``R_x(180)`` (Y down -> up), then reads
    into the domain through the shared ``A`` convention: domain depth is
    ``+tz`` (a person in front of the camera sits at positive depth, facing
    the canonical ``-Y`` front) and domain height is ``-ty``
    (image up = ``-ty`` because the camera's Y points down).
    """
    adapter = _world_pose_adapter(tmp_path)
    try:
        pose = adapter._to_world_pose(
            {
                # 12 cm camera-right, 5 cm below the camera centre, 1 m in front.
                "root_translation": [0.12, 0.05, 1.0],
                "rotations": {},
            }
        )
        actual = (
            pose.root_translation.x,
            pose.root_translation.y,
            pose.root_translation.z,
        )
        assert actual == pytest.approx(
            (12.0, 100.0, -5.0)
        )
    finally:
        adapter.shutdown()


# -- the bind offsets of the production skeleton (T13) -------------------------- #


def test_bind_offsets_arrive_with_the_ready_line(tmp_path: Path) -> None:
    """The template bind offsets are real body-model data, in the domain frame."""
    adapter = _adapter(tmp_path, "ok")
    try:
        adapter.extract_pose(_frame(), frame_index=0)  # spawns, reads the ready line
        offsets = adapter.bind_offsets()
        assert offsets is not None
        assert len(offsets) == 24
        assert offsets["Pelvis"].x == pytest.approx(-0.18)
        assert offsets["Pelvis"].y == pytest.approx(-2.822)
        assert offsets["Pelvis"].z == pytest.approx(93.851)
        # L_Hip's canned SMPL frame offset converts (x, -z, y): -9.141 -> +y
        assert offsets["L_Hip"].y == pytest.approx(0.682)
        assert offsets["L_Hip"].z == pytest.approx(-9.141)
        assert offsets["Head"].y == pytest.approx(-5.135)
        assert offsets["Head"].z == pytest.approx(6.497)
    finally:
        adapter.shutdown()


def test_bind_offsets_are_none_before_and_without_a_ready_line(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ok")
    try:
        assert adapter.bind_offsets() is None  # the worker is not even spawned yet
    finally:
        adapter.shutdown()
    adapter._ready = {}  # a ready line without bind data keeps the honest None
    assert adapter.bind_offsets() is None
