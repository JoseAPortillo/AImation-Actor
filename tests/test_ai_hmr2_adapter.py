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
from aimation_actor.core.models import FrameImage

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
    return Hmr2Adapter(
        engine_root=None,
        python_executable=sys.executable,
        worker_script=_FAKE_WORKER,
        checkpoint=checkpoint,
        smpl_dir=smpl_dir,
        env=dict(os.environ, FAKE_HMR2_WORKER_MODE=mode, FAKE_PID_FILE=str(pid_file)),
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
        # The pelvis's rotation is the engine's global orientation.
        assert pose.rotations["Pelvis"] == pytest.approx((1.0, 0.0, 0.0, 0.0))
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


def test_a_worker_death_mid_request_is_a_typed_failure(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "die_mid_request")
    with pytest.raises(Hmr2EngineError):
        adapter.extract_pose(_frame(), frame_index=0)
    # The dead worker is discarded, so the next call starts a fresh one.
    assert adapter._worker is None
    adapter.shutdown()


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
