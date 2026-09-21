"""MIB (motion in-betweening) backend adapter.

Invokes the isolated MIB runtime (``tools/mib_helper.py``) as a child
process without importing torch in-core. The MIB transformer models generate
a natural transition between every consecutive pair of authored keyframes.

Reuses:
- The AutoKeyframe cache venv (``tools/.cache/autokeyframe/venv``) — it
  already provides the torch version the release checkpoints load under.
- The AutoKeyframe conditioning normalizer and the authored-fidelity gate —
  the MIB helper consumes the same bounded raw-LaFAN ext-joint payload and
  returns the same ``{keyframes, global_positions}`` envelope.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.motion_backend import MotionBackendUnavailable
from aimation_actor_core.domain.animation.neutral_motion import (
    NeutralMeta,
    NeutralMotion,
)
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.infrastructure.ai_models.autokeyframe import (
    _EXT_PARENTS,
    _EXT_TO_NEUTRAL,
    _MAX_PAYLOAD_BYTES,
    _model_to_scene_coordinates,
    _normalize_conditioning,
    _validate_authored_fidelity,
)

#: MIB emits every generated transition frame (dense motion), unlike
#: AutoKeyframe which emits at most 64 authored keys. Bounded by the helper's
#: 256 KiB JSON cap in practice (roughly 350 frames at 22 joints).
_MAX_MIB_FRAMES = 1024
_NAME = "mib"


class MibBackend:
    """Invoke the isolated MIB runtime without importing it in-core."""

    name = _NAME

    def __init__(
        self, root: Path, autokeyframe_root: Path, timeout_seconds: float, helper: Path
    ) -> None:
        self.root = root
        self.autokeyframe_root = autokeyframe_root
        self.timeout_seconds = timeout_seconds
        self.helper = helper

    def generate(self, conditioning: dict[str, Any]) -> NeutralMotion:
        root = self.resolve_assets()
        try:
            payload = json.dumps(
                _normalize_conditioning(conditioning),
                separators=(",", ":"),
                allow_nan=False,
            )
        except MotionBackendUnavailable:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise MotionBackendUnavailable("MIB conditioning is malformed") from exc
        if len(payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise MotionBackendUnavailable("MIB conditioning is too large")
        env = os.environ.copy()
        env.update({
            "MIB_SOURCE": str(root["source"]),
            "MIB_PRETRAINED": str(root["pretrained"]),
            "MIB_L_POSITION": str(root["l_position"]),
            "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1",
        })
        try:
            completed = subprocess.run(
                [str(root["venv_python"]), str(self.helper)], input=payload, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds, check=False, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MotionBackendUnavailable("MIB helper failed or timed out") from exc
        if completed.returncode != 0:
            raise MotionBackendUnavailable("MIB helper returned an error")
        try:
            if len(completed.stdout.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
                raise ValueError("helper output is too large")
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            _validate_authored_fidelity(result, conditioning)
            return _motion_from_result(result, conditioning)
        except MotionBackendUnavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise MotionBackendUnavailable("MIB helper returned malformed output") from exc

    def resolve_assets(self) -> dict[str, Path]:
        """Resolve and validate the MIB runtime assets, raising when missing."""
        root = self.root.resolve()
        helper = self.helper.resolve()
        autokeyframe_root = self.autokeyframe_root.resolve()
        source = root / "source"
        pretrained = root / "pretrained"
        venv_python = autokeyframe_root / "venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        l_position = autokeyframe_root / "checkpoint" / "l_position.npy"
        if not source.is_dir() or not pretrained.is_dir():
            raise MotionBackendUnavailable("MIB source or pretrained assets are unavailable")
        if not helper.is_file() or not venv_python.is_file() or not l_position.is_file():
            raise MotionBackendUnavailable("MIB runtime assets are unavailable")
        return {
            "source": source,
            "pretrained": pretrained,
            "venv_python": venv_python,
            "l_position": l_position,
        }


def _motion_from_result(result: dict[str, Any], conditioning: dict[str, Any]) -> NeutralMotion:
    """Same conversion as the AutoKeyframe adapter, but dense and sourced MIB."""
    positions = result.get("global_positions")
    keyframes = result.get("keyframes")
    if (not isinstance(positions, list) or not positions or len(positions) > _MAX_MIB_FRAMES
            or not isinstance(keyframes, list) or len(keyframes) != len(positions)):
        raise ValueError("bounded keyframes and global_positions are required")
    if any(not isinstance(frame, list) or len(frame) != 22 for frame in positions):
        raise ValueError("global_positions must contain 22 joints")
    if any(not isinstance(index, int) or not 9 <= index <= 218
           for index in keyframes):
        raise ValueError("keyframes must be valid padded source indices")
    if any(a >= b for a, b in zip(keyframes, keyframes[1:], strict=False)):
        raise ValueError("keyframes must be strictly increasing")
    if any(
        not isinstance(point, list) or len(point) != 3
        or any(
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(value) > 100000
            for value in point
        )
        for frame in positions for point in frame
    ):
        raise ValueError("global_positions contains invalid coordinates")
    duration = max(keyframes)
    fps = float(conditioning.get("fps", 24.0))
    frames: list[Frame] = []
    for index, model_frame in enumerate(positions):
        external_frame = [_model_to_scene_coordinates(point) for point in model_frame]
        transforms = {"Root": Transform3D(translation=external_frame[0])}
        for external, name in _EXT_TO_NEUTRAL.items():
            neutral_parent = DEFAULT_NEUTRAL_SKELETON.bones[name].parent
            parent_external = {
                "Hips": 0, "Spine": 0, "Chest": 9, "Neck": 11, "Head": 12,
            }.get(name, _EXT_PARENTS[external])
            if neutral_parent == "Hips" and name in ("LUpLeg", "RUpLeg"):
                parent_external = 0
            point = external_frame[external]
            parent_point = external_frame[parent_external]
            rest = DEFAULT_NEUTRAL_SKELETON.bones[name].rest_position
            local = (
                float(point[0] - parent_point[0] - rest[0]),
                float(point[1] - parent_point[1] - rest[1]),
                float(point[2] - parent_point[2] - rest[2]),
            )
            transforms[name] = Transform3D(translation=local)
        transforms["Hips"] = Transform3D()
        source_frame = keyframes[index]
        frames.append(Frame(frame=source_frame, time=(source_frame - 1) / fps,
                            pose=Pose(transforms=transforms)))
    motion = NeutralMotion(
        meta=NeutralMeta(duration_frames=duration, fps=fps, source_type=_NAME),
        skeleton=DEFAULT_NEUTRAL_SKELETON,
        frames=frames,
    )
    motion.validate_invariants()
    return motion