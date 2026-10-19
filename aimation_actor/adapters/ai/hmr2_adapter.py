"""HMR2.0 adapter: the ``AIPort`` implementation bridging the out-of-process
engine (M5 T11/T12).

The application process never imports the engine stack: this adapter spawns
``adapters/ai/hmr2_worker.py`` inside the engine's own Python 3.10 environment
(``<engine>/.engine/venv``, the same isolation as the Blender read path, S14)
and talks to it over a line-JSON stdin/stdout protocol. The worker is
persistent — the 2.7 GB checkpoint loads once, then each ``K`` costs a single
inference (~84 ms measured in T10) — and it releases CUDA cache after every
request so VRAM does not grow across keys (FR-CAP-05).

Path discovery mirrors the Blender adapter's override convention:
explicit argument > ``AIMATION_ENGINE_ROOT`` environment variable > the
repository's ``.engine`` directory.

Everything that can go wrong before or during an extraction raises
:class:`Hmr2EngineError` with an actionable message naming the missing piece
and its fix (S6, S7, S16): a GPU-less or unconfigured machine gets a typed,
non-fatal report — the extraction marks nothing and the app keeps working.

This module is standard-library only: the weights live in the worker, so CI
never needs torch installed.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from aimation_actor.core.models import FrameImage, Quaternion, Vector3, WorldPose
from aimation_actor.ports.ai_port import AIPort

_READY_TIMEOUT_S = 300.0  # first load: 2.7 GB checkpoint + CUDA context init
_REQUEST_TIMEOUT_S = 120.0
_TERMINATE_GRACE_S = 5.0
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

#: The engine-side worker module, run by the engine's own interpreter.
_WORKER_MODULE = Path(__file__).resolve().parent / "hmr2_worker.py"

_SMPL_MODEL_NAME = "SMPL_NEUTRAL.pkl"
_CHECKPOINT_DEFAULT = "epoch=35-step=1000000.ckpt"  # variant b (L22)


class Hmr2EngineError(RuntimeError):
    """A typed, actionable failure of the HMR2.0 engine (S6, S7)."""


# -- pure rotation helpers (SMPL's Y-up frame -> the domain's Z-up frame) ------ #


def quaternion_from_matrix(matrix: Mapping[int, float]) -> Quaternion:
    """A row-major 3x3 rotation matrix as a unit quaternion ``(w, x, y, z)``."""
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = (float(matrix[k]) for k in range(9))
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return (
            0.25 * s,
            (m21 - m12) / s,
            (m02 - m20) / s,
            (m10 - m01) / s,
        )
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (
            (m21 - m12) / s,
            0.25 * s,
            (m01 + m10) / s,
            (m02 + m20) / s,
        )
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return (
            (m02 - m20) / s,
            (m01 + m10) / s,
            0.25 * s,
            (m12 + m21) / s,
        )
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return (
        (m10 - m01) / s,
        (m02 + m20) / s,
        (m12 + m21) / s,
        0.25 * s,
    )


def _quaternion_multiply(
    left: Quaternion,
    right: Quaternion,
) -> Quaternion:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def quaternion_rotate(
    quaternion: Quaternion,
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate a vector by a unit quaternion ``(w, x, y, z)``.

    ``v' = v + 2w(u x v) + 2u x (u x v)`` with ``u = (x, y, z)``.
    """
    w, x, y, z = quaternion
    vx, vy, vz = vector
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + y * tz - z * ty,
        vy + w * ty + z * tx - x * tz,
        vz + w * tz + x * ty - y * tx,
    )


def conjugate_y_up_to_z_up(quaternion: Quaternion) -> Quaternion:
    """Re-express a SMPL (Y-up) rotation in the domain's Z-up frame.

    ``q_domain = R_x(+90) q_smpl R_x(-90)``, which is exactly the inverse of
    what the FBX writer does: the writer converts domain (Z-up) rotations into
    FBX's Y-up frame with ``A = R_x(-90)`` as ``q_fbx = A q_domain A^-1``, and
    SMPL is Y-up like FBX — so conjugating here by ``A^-1`` and back there
    returns the engine's own rotation.
    """
    half = math.pi / 4.0  # a 90-degree rotation: the quaternion's angle is half
    x_up = (math.cos(half), math.sin(half), 0.0, 0.0)
    return _quaternion_multiply(
        x_up,
        _quaternion_multiply(quaternion, (x_up[0], -x_up[1], -x_up[2], -x_up[3])),
    )


# -- the adapter --------------------------------------------------------------- #


class Hmr2Adapter(AIPort):
    """The ``AIPort`` implementation backed by the out-of-process HMR2.0 engine."""

    def __init__(
        self,
        *,
        engine_root: str | os.PathLike[str] | None = None,
        python_executable: str | os.PathLike[str] | None = None,
        worker_script: str | os.PathLike[str] | None = None,
        checkpoint: str | os.PathLike[str] | None = None,
        smpl_dir: str | os.PathLike[str] | None = None,
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
        self.checkpoint = Path(
            checkpoint
            or self.engine_root
            / ".cache"
            / "4DHumans"
            / "logs"
            / "train"
            / "multiruns"
            / "hmr2"
            / "0"
            / "checkpoints"
            / _CHECKPOINT_DEFAULT
        )
        self.smpl_dir = Path(smpl_dir or self.engine_root / ".cache" / "4DHumans" / "data" / "smpl")
        self.half_precision = half_precision
        self.pid_file = Path(pid_file) if pid_file is not None else None
        self._env = dict(env) if env is not None else None
        self._worker: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] | None = None
        self._ready: dict | None = None

    # -- lifecycle ------------------------------------------------------------- #

    def shutdown(self) -> None:
        """Terminate the engine worker; idempotent (safe at app close)."""
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

    # -- AIPort ---------------------------------------------------------------- #

    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        """One frame -> one ``WorldPose``, blocking (the runner owns the thread)."""
        self._ensure_worker()
        with tempfile.TemporaryDirectory(prefix="aimation-frame-") as frame_dir:
            frame_path = _write_png(image, Path(frame_dir) / f"frame-{frame_index}.png")
            response = self._request({"image_path": str(frame_path), "frame_index": frame_index})
        if response.get("status") != "ok":
            message = str(response.get("message", "the engine request failed"))
            if response.get("fatal"):
                self._worker = None
                self._lines = None
            raise Hmr2EngineError(f"the HMR2.0 engine failed on frame {frame_index}: {message}")
        return self._to_world_pose(response)

    # -- the bridge ------------------------------------------------------------ #

    def _ensure_worker(self) -> dict:
        """Validate everything, spawn the worker, and wait for its ready line."""
        if self._ready is not None:
            return self._ready
        self._validate()
        self._spawn()
        line = self._next_protocol_line(_READY_TIMEOUT_S)
        if line is None:
            self._worker = None
            raise Hmr2EngineError(
                f"the HMR2.0 engine worker exited before becoming ready "
                f"(checkpoint: {self.checkpoint}); run the engine probe to diagnose it"
            )
        ready = json.loads(line)
        if ready.get("status") != "ready":
            self._worker = None
            self._lines = None
            raise Hmr2EngineError(f"the HMR2.0 engine cannot start: {ready.get('message', ready)}")
        self._ready = ready
        return ready

    def _validate(self) -> None:
        engine_root = self.engine_root
        if not self.python_executable.is_file():
            raise Hmr2EngineError(
                f"the engine's Python interpreter was not found at {self.python_executable}. "
                f"Install the engine environment (see AGENTS.md 'Pose engine decision'), or point "
                f"the adapter elsewhere with the AIMATION_ENGINE_ROOT environment variable "
                f"(current engine root: {engine_root})."
            )
        if not self.worker_script.is_file():
            raise Hmr2EngineError(f"the engine worker script is missing: {self.worker_script}")
        if not self.checkpoint.is_file():
            raise Hmr2EngineError(
                f"the HMR2.0 checkpoint was not found at {self.checkpoint}. It is user-supplied: "
                f"download it per AGENTS.md 'Pose engine decision' (weights are never vendored)."
            )
        body_model = self.smpl_dir / _SMPL_MODEL_NAME
        if not body_model.is_file():
            raise Hmr2EngineError(
                f"the SMPL body model was not found at {body_model}. It is user-supplied and "
                f"non-redistributable (register at https://smplify.is.tue.mpg.de/); "
                f"see spec.md 4.14."
            )

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
            "hmr2_root": str(self.engine_root / "hmr2"),
            "checkpoint": str(self.checkpoint),
            "smpl_dir": str(self.smpl_dir),
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
        """The next protocol line, skipping anything the engine printed.

        ``None`` means the worker exited before answering.
        """
        assert self._lines is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                self._worker = None
                self._lines = None
                raise Hmr2EngineError(
                    f"the HMR2.0 engine did not answer within {timeout:.0f} s; check the GPU and "
                    f"the engine environment"
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
        assert worker is not None and worker.stdin is not None and self._lines is not None
        try:
            worker.stdin.write(json.dumps(request) + "\n")
            worker.stdin.flush()
        except OSError:
            self._worker = None
            self._lines = None
            raise Hmr2EngineError(
                "the HMR2.0 engine worker stopped responding; the next extraction restarts it"
            ) from None
        line = self._next_protocol_line(_REQUEST_TIMEOUT_S)
        if line is None:
            self._worker = None
            self._lines = None
            return {
                "status": "error",
                "fatal": True,
                "message": "the engine worker exited mid-request",
            }
        return json.loads(line)

    # -- the conversion (T12) -------------------------------------------------- #

    def _to_world_pose(self, response: Mapping[str, object]) -> WorldPose:
        """The engine result -> ``WorldPose`` (domain: Z-up, centimetres).

        - the hip height is the template anchor (T10 verdict: the per-frame
          weak-perspective estimate is not keyable; the betas=0 template's
          pelvis-to-contact distance is exact by construction);
        - the per-joint rotations are SMPL's local quaternions re-expressed in
          the domain's Z-up frame — the production skeleton mirrors SMPL's
          chain under ``Main``, so the names carry over untouched;
        - the world displacement the engine recovered is deliberately dropped
          (``Main`` ships in place; see the domain invariants in AGENTS.md).
        """
        ready = self._ready or {}
        hip_height_cm = float(ready.get("template_hip_height_cm", 0.0))
        rotations: dict[str, Quaternion] = {}
        response_rotations = response.get("rotations") or {}
        for name, matrix in response_rotations.items():
            rotations[name] = conjugate_y_up_to_z_up(quaternion_from_matrix(matrix))
        return WorldPose(translation=Vector3(x=0.0, y=0.0, z=hip_height_cm), rotations=rotations)


# -- module-level helpers ------------------------------------------------------- #


def _default_engine_root() -> Path:
    """The repository's ``.engine`` directory (two levels above this module)."""
    return Path(__file__).resolve().parents[3] / ".engine"


def _engine_python(engine_root: Path) -> Path:
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return engine_root / "venv" / scripts / f"python{suffix}"


def _write_png(image: FrameImage, path: Path) -> Path:
    """A ``FrameImage``'s RGB888 bytes as a PNG, via the app's own Qt binding."""
    from PySide6.QtGui import QImage

    expected = image.width * image.height * 3
    if len(image.rgb) != expected:
        raise Hmr2EngineError(
            f"the captured frame is corrupt: {len(image.rgb)} RGB bytes for "
            f"{image.width}x{image.height} (expected {expected})"
        )
    qimage = QImage(
        image.rgb,
        image.width,
        image.height,
        image.width * 3,
        QImage.Format.Format_RGB888,
    )
    if not qimage.save(str(path), "PNG"):
        raise Hmr2EngineError(f"the captured frame could not be written for the engine: {path}")
    return path
