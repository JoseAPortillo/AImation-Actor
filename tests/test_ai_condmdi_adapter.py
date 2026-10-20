"""Tests for the M6 T3 bridge: the ``CondMDIAdapter`` over a fake engine.

The real worker runs a pinned old stack (torch 1.13) out of process; the fake
(``tests/fake_condmdi_worker.py``) speaks the same line-JSON protocol on the
plain application interpreter, so the subprocess bridge, the gap orchestration
and the typed failures are testable without any engine dependency.

Wire contract being pinned here (M6 L8):

- bootstrap (adapter -> worker): {"engine_root", "repo_dir", "checkpoint",
  "mean_path", "std_path", "half_precision"}
- ready (worker -> adapter): {"status": "ready", "gpu", "vram_total_mib",
  "motion_fps", "max_frames"}
- request (adapter -> worker): {"span_frames", "keys": [{"sample", "pose"}],
  "bind_offsets"}
- response: {"status": "ok", "poses": [{"frame", "pose"}]}
  | {"status": "error", "message", "fatal"}

The fake returns a deterministic turning motion (pelvis rotating z by
``0.05`` rad per motion sample at the model's 20 fps clock), so every expected
rotation is computable from the frame mapping alone: frame ``f`` of a gap
anchored at ``left`` samples the mutex at ``(f - left) * 20 / 24``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from aimation_actor.adapters.ai.condmdi_adapter import CondMDIAdapter, CondMDIEngineError
from aimation_actor.core.models import JointPose, Keyframe, Quaternion, TimelineState, Vector3
from aimation_actor.core.production_skeleton import production_skeleton
from tests.fake_hmr2_worker import _CANNED_BIND_OFFSETS as _FAKE_BIND_OFFSETS

_TEST_ROOT = Path(__file__).resolve().parent
_FAKE_WORKER = _TEST_ROOT / "fake_condmdi_worker.py"

_MOTION_STEP = 0.05  # the fake's radians per motion sample
_MOTION_HEIGHT = 90.0  # the fake's canned pelvis height (cm)

# The canned step (0.05 rad) is small enough that slerp takes its NLERP branch
# (normalized lerp below the acos knee): angle-exact only to ~1e-6 radians,
# which is invisible at any frame rate. Interpolations between larger turns
# are angle-exact to float precision.
_MOTION_TOL = 1e-6

_BIND_OFFSETS = {name: Vector3(*point) for name, point in _FAKE_BIND_OFFSETS.items()}


def _qz(angle_radians: float) -> Quaternion:
    return Quaternion(
        w=math.cos(angle_radians / 2.0),
        x=0.0,
        y=0.0,
        z=math.sin(angle_radians / 2.0),
    )


def _almost(quaternion: Quaternion, expected: Quaternion, *, tol: float = 1e-9) -> None:
    assert quaternion.w == pytest.approx(expected.w, abs=tol)
    assert quaternion.x == pytest.approx(expected.x, abs=tol)
    assert quaternion.y == pytest.approx(expected.y, abs=tol)
    assert quaternion.z == pytest.approx(expected.z, abs=tol)


def _timeline(*frames: int) -> TimelineState:
    keys = tuple(
        Keyframe(
            frame=frame,
            pose={"Pelvis": JointPose(rotation=_qz(frame * 0.1))},
        )
        for frame in sorted(frames)
    )
    skeleton = production_skeleton(_BIND_OFFSETS)
    return TimelineState(skeleton=skeleton, keyframes=keys, fps=24.0, frame_end=frames[-1])


def _wire(pose: JointPose) -> dict:
    """The domain pose as the request wire format carries it."""
    return {
        "Pelvis": {
            "quat": [pose.rotation.w, pose.rotation.x, pose.rotation.y, pose.rotation.z],
            "trans": [
                pose.translation.x,
                pose.translation.y,
                pose.translation.z,
            ],
        }
    }


def _workspace(tmp_path: Path) -> None:
    """Files the adapter validates before spawning, minus any engine stack."""
    (tmp_path / "condmdi_repo").mkdir(exist_ok=True)
    (tmp_path / "model000750000.pt").write_text("checkpoint bytes go here", encoding="utf-8")


def _adapter(
    tmp_path: Path,
    mode: str = "ok",
    *,
    missing_python: bool = False,
    extra_env: dict[str, str] | None = None,
) -> CondMDIAdapter:
    """An adapter pointed at the fake worker, running on this interpreter."""
    _workspace(tmp_path)
    env = {"FAKE_CONDMDI_WORKER_MODE": mode}
    env.update(extra_env or {})
    return CondMDIAdapter(
        engine_root=tmp_path / "engine",
        python_executable=(
            tmp_path / "missing" / "python.exe" if missing_python else sys.executable
        ),
        worker_script=_FAKE_WORKER,
        repo_dir=tmp_path / "condmdi_repo",
        checkpoint=tmp_path / "model000750000.pt",
        mean_path=tmp_path / "Mean.npy",
        std_path=tmp_path / "Std.bin",
        env=env,
    )


# -- the S1 result ---------------------------------------------------------------- #


def test_a_two_key_timeline_ends_up_filled_by_the_engine(tmp_path) -> None:
    state = _timeline(10, 22)
    filled = _adapter(tmp_path).inbetween(state)

    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    # The human keys come back untouched (S1 hard constraints).
    assert keyed[10] == state.keyframes[0]
    assert keyed[22] == state.keyframes[1]
    # Nothing outside the span; every empty frame of the gap carries motion.
    assert set(keyed) == set(range(10, 23))
    for frame in range(11, 22):
        expected = _qz((frame - 10) * 20.0 / 24.0 * _MOTION_STEP)
        received = keyed[frame].pose["Pelvis"]
        _almost(received.rotation, expected, tol=_MOTION_TOL)
        assert received.translation.z == _MOTION_HEIGHT
    assert 9 not in keyed and 23 not in keyed
    assert filled.fps == state.fps


def test_each_key_gap_gets_its_own_model_request(tmp_path) -> None:
    state = _timeline(10, 20, 40)
    count_file = tmp_path / "fill-requests.count"
    filled = _adapter(
        tmp_path, extra_env={"FAKE_CONDMDI_COUNT_FILE": str(count_file)}
    ).inbetween(state)

    assert count_file.exists()
    assert len(count_file.read_text(encoding="utf-8").splitlines()) == 2

    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    assert keyed[10] == state.keyframes[0]
    assert keyed[20] == state.keyframes[1]
    assert keyed[40] == state.keyframes[2]
    # Each gap restarts the fake's motion at sample 0, anchored at its left key.
    _almost(
        keyed[15].pose["Pelvis"].rotation, _qz(5 * 20.0 / 24.0 * _MOTION_STEP), tol=_MOTION_TOL
    )
    _almost(
        keyed[30].pose["Pelvis"].rotation, _qz(10 * 20.0 / 24.0 * _MOTION_STEP), tol=_MOTION_TOL
    )


# -- refusals that never reach the engine ------------------------------------------- #


def test_a_lone_key_needs_no_generation(tmp_path) -> None:
    state = _timeline(10)
    with pytest.raises(ValueError, match="two keys"):
        _adapter(tmp_path, missing_python=True).inbetween(state)


def test_a_gap_beyond_the_model_window_is_refused_before_spawning(tmp_path) -> None:
    # 400 timeline frames -> 333 motion samples at 20 fps; the window is 196.
    # The interpreter is deliberately broken, so anything that spawned would
    # fail differently: this error can only come from the pre-spawn check.
    state = _timeline(10, 410)
    with pytest.raises(CondMDIEngineError, match="333"):
        _adapter(tmp_path, missing_python=True).inbetween(state)


# -- the engine bridge's failure paths ----------------------------------------------- #


def test_a_failed_ready_line_is_a_typed_actionable_failure(tmp_path) -> None:
    state = _timeline(10, 22)
    with pytest.raises(CondMDIEngineError, match="no CondMDI GPU on this box"):
        _adapter(tmp_path, mode="ready_error").inbetween(state)


def test_a_worker_that_dies_mid_fill_is_respawned_the_next_time(tmp_path) -> None:
    marker = tmp_path / "died.txt"
    state = _timeline(10, 22)
    adapter = _adapter(tmp_path, mode="die_once", extra_env={"FAKE_DIED_MARKER": str(marker)})

    with pytest.raises(CondMDIEngineError):
        adapter.inbetween(state)

    filled = adapter.inbetween(state)
    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    assert set(keyed) == set(range(10, 23))


def test_a_request_level_error_is_reported_with_the_engine_message(tmp_path) -> None:
    state = _timeline(10, 22)
    with pytest.raises(CondMDIEngineError, match="sampling diverged"):
        _adapter(tmp_path, mode="fill_error").inbetween(state)
