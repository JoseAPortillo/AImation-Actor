"""CondMDI adapter: generative inbetweening engine (M6 T3, FR-GEN-01/02/03).

The keyframe-conditioned motion diffusion model trained on HumanML3D
(Cohan et al., SIGGRAPH 2024; official MIT code, checkpoint user-supplied).
It runs **out of process** — its stack pins Python 3.7-era dependencies
(torch 1.13, CLIP) — over the same line-JSON worker protocol the HMR2.0
capture engine uses (``hmr2_adapter.py``/``hmr2_worker.py``).

Wire contract (tests/test_ai_condmdi_adapter.py pins it):

- bootstrap (adapter -> worker): {"engine_root", "repo_dir", "checkpoint",
  "mean_path", "std_path", "half_precision"}
- ready (worker -> adapter): {"status": "ready", "gpu", "vram_total_mib",
  "motion_fps", "max_frames"}
- request (adapter -> worker): {"span_frames", "keys", "bind_offsets"} — keys
  in **domain** form (quaternions + pelvis height); the engine-native
  HumanML3D-263 conversion is the worker's job, built on the official
  vendored code (M6 L6: engine conventions are never reimplemented here)
- response: {"status": "ok", "poses": [{"frame", "pose"}]}
  | {"status": "error", "message", "fatal"}

Orchestration per gap between consecutive keys (S1 is structural here):

1. the gap is refused *before spawning* when its span in motion samples
   exceeds the model window (single-window MVP; window splitting for longer
   gaps is measured work, M6 T5 follow-up);
2. the gap's keys enter as conditioning at their rounded motion-sample
   indices of the engine's own clock (``motion_fps``, 20.0 for HumanML3D);
3. the reply's dense motion is resampled back onto the timeline's clock
   through ``core.resampling`` and filled between the keys;
4. the core's ``fill_gap_synthetically`` guarantees the keys return
   byte-identical and nothing lands outside the span, whatever the engine
   said.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from aimation_actor.core.models import JointPose, Quaternion, TimelineState, Vector3
from aimation_actor.core.resampling import fill_gap_synthetically, resample_dense_poses
from aimation_actor.core.services import key_frames
from aimation_actor.ports.ai_port import InbetweeningPort

__all__ = ["CondMDIAdapter", "CondMDIEngineError"]

_READY_TIMEOUT_S = 300.0  # the checkpoint + CLIP load takes minutes (T5 measures)
_REQUEST_TIMEOUT_S = 600.0  # diffusion sampling per gap: budgeted, T5 measures
_TERMINATE_GRACE_S = 5.0
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

#: The engine-side worker module, run by the engine's own interpreter.
_WORKER_MODULE = Path(__file__).resolve().parent / "condmdi_worker.py"

_CHECKPOINT_DEFAULT = "model000750000.pt"  # the official keyframe-conditioned save
_MOTION_FPS = 20.0  # HumanML3D's clock (the ready line re-states it)
_MAX_SAMPLES_DEFAULT = 196  # ~9.8 s at 20 fps; the model's trained window


class CondMDIEngineError(RuntimeError):
    """A typed, actionable failure of the CondMDI engine (S3)."""


def _default_engine_root() -> Path:
    return Path(__file__).resolve().parents[3] / ".engine"


def _engine_python(engine_root: Path) -> Path:
    """The CondMDI stack's interpreter: its own venv under the engine root.

    A dedicated venv, not the capture engine's ``venv``: CondMDI pins
    torch 1.13-era dependencies that conflict with the HMR2.0 stack's.
    """
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return engine_root / "condmdi-venv" / scripts / f"python{suffix}"


def _samples_between(
    left_frame: int, right_frame: int, timeline_fps: float, motion_fps: float
) -> int:
    """The gap's span in motion-clock samples (the right key's sample index)."""
    return round((right_frame - left_frame) * motion_fps / timeline_fps)


def _pose_to_wire(pose: Mapping[str, JointPose]) -> dict:
    """A domain pose as the request/response wire carries it.

    ``trans`` is ``null`` for the rotation-only joints — body bones carry
    rotation only, and the pelvis its height, by the domain's invariants.
    """
    wire: dict[str, dict] = {}
    for name, joint in pose.items():
        translation = joint.translation
        moved = (translation.x, translation.y, translation.z) != (0.0, 0.0, 0.0)
        wire[name] = {
            "quat": [
                joint.rotation.w,
                joint.rotation.x,
                joint.rotation.y,
                joint.rotation.z,
            ],
            "trans": (
                [translation.x, translation.y, translation.z] if moved else None
            ),
        }
    return wire


def _pose_from_wire(raw: Mapping[str, object]) -> dict[str, JointPose]:
    """A wire pose back into domain types (raw tuples crash every consumer).

    A joint whose ``trans`` is ``null`` — or missing — keeps the zero
    translation the domain reads as bind/no-offset behaviour.
    """
    pose: dict[str, JointPose] = {}
    for name, entry in raw.items():
        assert isinstance(entry, dict), "each wire joint entry must be a mapping"
        quat = entry["quat"]
        rotation = Quaternion(
            w=float(quat[0]), x=float(quat[1]), y=float(quat[2]), z=float(quat[3])
        )
        translation = Vector3()
        raw_translation = entry.get("trans")
        if raw_translation is not None:
            translation = Vector3(
                x=float(raw_translation[0]),
                y=float(raw_translation[1]),
                z=float(raw_translation[2]),
            )
        pose[name] = JointPose(rotation=rotation, translation=translation)
    return pose


class CondMDIAdapter(InbetweeningPort):
    """Fills a ``TimelineState``'s gaps with CondMDI-generated motion.

    All engine paths resolve lazily and validate on first use — constructing
    an adapter spawns nothing, probes nothing, imports no engine stack.
    """

    def __init__(
        self,
        *,
        engine_root: str | os.PathLike[str] | None = None,
        python_executable: str | os.PathLike[str] | None = None,
        worker_script: str | os.PathLike[str] | None = None,
        repo_dir: str | os.PathLike[str] | None = None,
        checkpoint: str | os.PathLike[str] | None = None,
        mean_path: str | os.PathLike[str] | None = None,
        std_path: str | os.PathLike[str] | None = None,
        half_precision: bool = True,
        env: Mapping[str, str] | None = None,
        pid_file: str | os.PathLike[str] | None = None,
    ) -> None:
        self.engine_root = Path(
            engine_root
            or os.environ.get("AIMATION_ENGINE_ROOT")
            or _default_engine_root()
        )
        self.python_executable = Path(python_executable or _engine_python(self.engine_root))
        self.worker_script = Path(worker_script or _WORKER_MODULE)
        self.repo_dir = Path(repo_dir or self.engine_root / "condmdi")
        self.checkpoint = Path(
            checkpoint
            or self.engine_root / "condmdi_random_joints" / _CHECKPOINT_DEFAULT
        )
        self.mean_path = Path(mean_path) if mean_path is not None else None
        self.std_path = Path(std_path) if std_path is not None else None
        self.half_precision = half_precision
        self.pid_file = Path(pid_file) if pid_file is not None else None
        self._env = dict(env) if env is not None else None
        self._worker: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] | None = None
        self._ready: dict | None = None

    # -- lifecycle ------------------------------------------------------------- #

    def _discard_worker(self) -> None:
        """Tear the worker down: terminate the process, forget all state.

        Same reason as the capture engine's: an orphaned worker holds VRAM
        no one can reach, and a stale ``ready`` would block respawning.
        """
        worker = self._worker
        self._worker = None
        self._lines = None
        self._ready = None
        if worker is None:
            return
        with contextlib.suppress(OSError):
            worker.stdin.close()
        try:
            worker.wait(timeout=_TERMINATE_GRACE_S)
        except subprocess.TimeoutExpired:
            worker.terminate()
            try:
                worker.wait(timeout=_TERMINATE_GRACE_S)
            except subprocess.TimeoutExpired:
                worker.kill()

    def shutdown(self) -> None:
        """Terminate the engine worker; idempotent (safe at app close)."""
        self._discard_worker()

    # -- InbetweeningPort ------------------------------------------------------- #

    def inbetween(self, timeline: TimelineState) -> TimelineState:
        """Fill every gap between consecutive keys; keys stay byte-identical."""
        frames = key_frames(timeline)
        if len(frames) < 2:
            raise ValueError(
                "inbetweening needs at least two keys: a timeline with fewer "
                "keys has no gap to fill (S1: nothing outside the keys)"
            )
        # Before anything spawns: an oversized window is a caller-visible
        # configuration fact, not an engine event.
        self._refuse_oversized_gaps(
            frames, timeline, motion_fps=_MOTION_FPS, max_samples=_MAX_SAMPLES_DEFAULT
        )
        ready = self._ensure_worker()
        motion_fps = float(ready.get("motion_fps") or _MOTION_FPS)
        max_samples = int(ready.get("max_frames") or _MAX_SAMPLES_DEFAULT)
        self._refuse_oversized_gaps(
            frames, timeline, motion_fps=motion_fps, max_samples=max_samples
        )

        filled = timeline
        for left, right in zip(frames, frames[1:], strict=False):
            span = _samples_between(left, right, timeline.fps, motion_fps)
            keys_payload = []
            for keyed in (left, right):
                keyframe = next(k for k in timeline.keyframes if k.frame == keyed)
                keys_payload.append(
                    {
                        "sample": round((keyed - left) * motion_fps / timeline.fps),
                        "pose": _pose_to_wire(keyframe.pose),
                    }
                )
            bind_offsets = {
                joint.name: [
                    joint.rest_translation.x,
                    joint.rest_translation.y,
                    joint.rest_translation.z,
                ]
                for joint in timeline.skeleton.joints
            }
            request = {
                "span_frames": span,
                "keys": keys_payload,
                "bind_offsets": bind_offsets,
            }
            response = self._request(request)
            if response.get("status") != "ok":
                message = str(response.get("message", "the engine request failed"))
                if response.get("fatal"):
                    self._discard_worker()
                raise CondMDIEngineError(
                    f"the CondMDI engine failed to fill the gap {left}..{right}: {message}"
                )
            dense = self._dense_motion(response)
            generated = resample_dense_poses(
                dense, motion_fps, timeline.fps, frame_start=left
            )
            filled = fill_gap_synthetically(filled, left, right, generated)
        return filled

    # -- the bridge (mirrors the HMR2.0 adapter's subprocess lifecycle) --------- #

    def _refuse_oversized_gaps(
        self,
        frames: tuple[int, ...],
        timeline: TimelineState,
        *,
        motion_fps: float,
        max_samples: int,
    ) -> None:
        for left, right in zip(frames, frames[1:], strict=False):
            span = _samples_between(left, right, timeline.fps, motion_fps)
            if span > max_samples:
                raise CondMDIEngineError(
                    f"the gap between frames {left} and {right} needs {span} motion "
                    f"samples, beyond the model window of {max_samples} at "
                    f"{motion_fps:.0f} fps; longer gaps need window splitting, "
                    f"not yet implemented (M6 T5 follow-up)"
                )

    def _dense_motion(self, response: Mapping[str, object]) -> list[dict[str, JointPose]]:
        """The reply's poses, ordered by their motion-sample frame index."""
        entries = list(response.get("poses") or [])
        entries.sort(key=lambda entry: int(entry["frame"]))  # type: ignore[index]
        return [_pose_from_wire(entry["pose"]) for entry in entries]  # type: ignore[index]

    def _validate(self) -> None:
        if not self.python_executable.is_file():
            raise CondMDIEngineError(
                f"the CondMDI engine python was not found at {self.python_executable}; "
                f"create the engine environment per AGENTS.md (a dedicated venv: "
                f"its pinned torch 1.13 stack conflicts with the capture engine's)"
            )
        if not self.worker_script.is_file():
            raise CondMDIEngineError(f"the engine worker script is missing: {self.worker_script}")
        if not self.repo_dir.is_dir():
            raise CondMDIEngineError(
                f"the official CondMDI repo was not found at {self.repo_dir}; clone it "
                f"(setarehc/diffusion-motion-inbetweening) — its conversion code is "
                f"vendored by reference, never reimplemented (M6 L6)"
            )
        if not self.checkpoint.is_file():
            raise CondMDIEngineError(
                f"the CondMDI checkpoint was not found at {self.checkpoint}. It is "
                f"user-supplied: download the keyframe-conditioned save per the "
                f"feature document (weights are never vendored)."
            )

    def _ensure_worker(self) -> dict:
        """Validate everything, spawn the worker, and wait for its ready line."""
        if self._ready is not None:
            return self._ready
        self._validate()
        self._spawn()
        line = self._next_protocol_line(_READY_TIMEOUT_S)
        if line is None:
            self._discard_worker()
            raise CondMDIEngineError(
                f"the CondMDI engine worker exited before becoming ready "
                f"(checkpoint: {self.checkpoint}); run the engine probe to diagnose it"
            )
        ready = json.loads(line)
        if ready.get("status") != "ready":
            self._discard_worker()
            raise CondMDIEngineError(
                f"the CondMDI engine cannot start: {ready.get('message', ready)}"
            )
        self._ready = ready
        return ready

    def _spawn(self) -> None:
        self._worker = subprocess.Popen(
            [str(self.python_executable), str(self.worker_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=self._env,
            creationflags=_CREATE_NO_WINDOW,
        )
        collected = queue.Queue()
        threading.Thread(target=self._read_lines, args=(collected,), daemon=True).start()
        self._lines = collected
        bootstrap = {
            "engine_root": str(self.engine_root),
            "repo_dir": str(self.repo_dir),
            "checkpoint": str(self.checkpoint),
            "mean_path": str(self.mean_path) if self.mean_path else None,
            "std_path": str(self.std_path) if self.std_path else None,
            "half_precision": self.half_precision,
        }
        if self.pid_file is not None:
            bootstrap["fake_pid_file"] = str(self.pid_file)
        assert self._worker.stdin is not None
        self._worker.stdin.write(json.dumps(bootstrap) + "\n")
        self._worker.stdin.flush()

    def _read_lines(self, collected: queue.Queue[str | None]) -> None:
        worker = self._worker
        if worker is None or worker.stdout is None:
            collected.put(None)
            return
        for line in worker.stdout:
            collected.put(line)
        collected.put(None)  # EOF: the worker exited

    def _next_protocol_line(self, timeout: float) -> str | None:
        """The next protocol line, skipping anything the engine printed."""
        assert self._lines is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                self._discard_worker()
                raise CondMDIEngineError(
                    f"the CondMDI engine did not answer within {timeout:.0f} s; check "
                    f"the GPU and the engine environment"
                )
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue  # stray engine print, not a protocol line
            if isinstance(payload, dict) and "status" in payload:
                return line

    def _request(self, request: dict) -> dict:
        worker = self._worker
        if worker is None or worker.stdin is None:
            raise CondMDIEngineError("the CondMDI engine worker is not running")
        try:
            worker.stdin.write(json.dumps(request) + "\n")
            worker.stdin.flush()
        except OSError:
            self._discard_worker()
            raise CondMDIEngineError(
                "the CondMDI engine worker stopped responding; the next fill restarts it"
            ) from None
        line = self._next_protocol_line(_REQUEST_TIMEOUT_S)
        if line is None:
            self._discard_worker()
            return {
                "status": "error",
                "fatal": True,
                "message": "the engine worker exited mid-request",
            }
        return json.loads(line)
