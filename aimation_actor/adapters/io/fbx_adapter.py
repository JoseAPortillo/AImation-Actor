"""FBX storage adapter.

Writing uses the in-repo pure-Python writer (:mod:`binary` + :mod:`document`),
so the application never links Autodesk's FBX SDK. Reading drives Blender as an
external subprocess (:mod:`blender_import`): Blender imports the file and dumps
its animation to JSON, which is converted back into the domain here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from aimation_actor.adapters.io.fbx import binary, document
from aimation_actor.adapters.io.fbx.transform import (
    quaternion_conjugate,
    quaternion_multiply,
    quaternion_normalized,
    rotate_vector,
)
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)
from aimation_actor.ports.io_port import IOPort

_BRIDGE_SCRIPT = Path(__file__).with_name("fbx") / "blender_import.py"
_EXECUTABLE_ENV_VAR = "AIMATION_BLENDER"
_DEFAULT_EXECUTABLES = (
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
)
_DEFAULT_TIMEOUT_SECONDS = 300.0
#: FBX centimetres per Blender world unit (Blender measures in metres).
_CENTIMETRES_PER_METRE = 100.0


class BlenderError(RuntimeError):
    """Blender could not be found, crashed, or produced no usable animation."""


class BlenderFbxAdapter(IOPort):
    """Reads FBX through Blender; writes it with the built-in writer."""

    def __init__(
        self,
        blender_executable: str | os.PathLike[str] | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._blender_executable = blender_executable
        self._timeout = timeout

    # ----------------------------------------------------------------- #
    # IOPort
    # ----------------------------------------------------------------- #

    def save(self, state: TimelineState, path: Path) -> None:
        """Write ``state`` to a binary FBX with sparse, stepped keys."""
        path = Path(path)
        path.write_bytes(binary.serialize(document.build_document(state)))

    def load(self, path: Path) -> TimelineState:
        """Read ``path`` into the domain timeline via Blender."""
        path = Path(path)
        executable = self._resolve_executable()
        with tempfile.TemporaryDirectory(prefix="aimation-fbx-") as workspace:
            payload_path = Path(workspace) / "fbx.json"
            self._run_bridge(executable, path, payload_path)
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        return state_from_payload(payload)

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _resolve_executable(self) -> str:
        if self._blender_executable is not None:
            return str(self._blender_executable)
        from_env = os.environ.get(_EXECUTABLE_ENV_VAR)
        if from_env:
            return from_env
        on_path = shutil.which("blender")
        if on_path:
            return on_path
        for candidate in _DEFAULT_EXECUTABLES:
            if Path(candidate).is_file():
                return candidate
        raise BlenderError(
            "Blender was not found: pass `blender_executable`, set "
            f"{_EXECUTABLE_ENV_VAR}, or put `blender` on PATH"
        )

    def _run_bridge(self, executable: str, input_path: Path, output_path: Path) -> None:
        command = [
            executable,
            "--background",
            "--factory-startup",
            "--python",
            str(_BRIDGE_SCRIPT),
            "--",
            str(input_path),
            str(output_path),
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell.
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except OSError as error:
            raise BlenderError(f"could not run Blender ({executable}): {error}") from error
        except subprocess.TimeoutExpired as error:
            raise BlenderError(f"Blender timed out after {self._timeout:g}s") from error

        if completed.returncode != 0 or not output_path.is_file():
            raise BlenderError(
                f"Blender failed to read {input_path.name} "
                f"(exit code {completed.returncode}):\n{completed.stderr.strip()}"
            )


def state_from_payload(payload: dict) -> TimelineState:
    """Convert the Blender bridge's JSON payload into a :class:`TimelineState`.

    Kept free of Blender so the armature-space -> domain conversion can be tested
    directly.
    """
    world_rotation = Quaternion(*payload["world_quaternion"])
    world_rotation_inverse = quaternion_conjugate(world_rotation)
    # Armature-space lengths are in FBX units; ``world_scale`` maps them to
    # metres, so multiply by 100 for the domain's centimetres.
    unit_scale = float(payload["world_scale"]) * _CENTIMETRES_PER_METRE

    def to_domain_translation(values) -> Vector3:
        rotated = rotate_vector(world_rotation, Vector3(*values))
        return Vector3(rotated.x * unit_scale, rotated.y * unit_scale, rotated.z * unit_scale)

    def to_domain_rotation(values) -> Quaternion:
        local = Quaternion(*values)
        return quaternion_normalized(
            quaternion_multiply(quaternion_multiply(world_rotation, local), world_rotation_inverse)
        )

    joints = tuple(
        JointData(
            name=bone["name"],
            parent=bone["parent"],
            rest_translation=to_domain_translation(bone["rest_t"]),
        )
        for bone in payload["bones"]
    )
    skeleton = Skeleton(joints=_root_first(joints))
    rest_by_name = {joint.name: joint.rest_translation for joint in skeleton.joints}

    keyframes = []
    for entry in payload["keyframes"]:
        pose: dict[str, JointPose] = {}
        for name, bone in entry["bones"].items():
            rest = rest_by_name.get(name, Vector3())
            total = to_domain_translation(bone["t"])
            pose[name] = JointPose(
                rotation=to_domain_rotation(bone["q"]),
                translation=Vector3(total.x - rest.x, total.y - rest.y, total.z - rest.z),
            )
        keyframes.append(Keyframe(frame=int(entry["frame"]), pose=pose))
    keyframes.sort(key=lambda keyframe: keyframe.frame)

    # Blender reports its own default scene range (1..250), so the keyed frames
    # are the only trustworthy span for a sparse timeline.
    frames = [keyframe.frame for keyframe in keyframes]
    frame_start = frames[0] if frames else int(payload["frame_start"])
    frame_end = frames[-1] if frames else int(payload["frame_end"])

    return TimelineState(
        skeleton=skeleton,
        keyframes=tuple(keyframes),
        fps=float(payload["fps"]),
        frame_start=frame_start,
        frame_end=frame_end,
    )


def _root_first(joints: tuple[JointData, ...]) -> tuple[JointData, ...]:
    """Order joints so every parent precedes its children (Blender does not)."""
    pending = list(joints)
    ordered: list[JointData] = []
    placed: set[str] = set()
    while pending:
        ready = [joint for joint in pending if joint.parent is None or joint.parent in placed]
        if not ready:  # orphaned/cyclic hierarchy: keep the remaining order.
            ordered.extend(pending)
            break
        ready_names = {joint.name for joint in ready}
        ordered.extend(ready)
        placed.update(ready_names)
        pending = [joint for joint in pending if joint.name not in ready_names]
    return tuple(ordered)
