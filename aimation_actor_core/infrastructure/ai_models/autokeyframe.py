"""Optional subprocess boundary for the cache-local AutoKeyframe model.

The main project deliberately has no torch dependency. The child process owns
all model imports and receives/returns only bounded JSON.

AutoKeyframe is a keyframe generator, not the project's MIB in-between model.
Its output is therefore accepted only when it stays close to the authored
golden joints; otherwise the endpoint safely uses its procedural path.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.motion_backend import MotionBackendUnavailable
from aimation_actor_core.domain.animation.neutral_motion import NeutralMeta, NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

# Proven LaFAN/AutoKeyframe order. External joint 10 (Spine1) is collapsed;
# external 11 (Spine2) is the neutral Chest.
_EXT_TO_NEUTRAL = {
    1: "LUpLeg", 2: "LLeg", 3: "LFoot", 4: "LToeBase",
    5: "RUpLeg", 6: "RLeg", 7: "RFoot", 8: "RToeBase",
    9: "Spine", 11: "Chest", 12: "Neck", 13: "Head",
    14: "LShoulder", 15: "LArm", 16: "LForeArm", 17: "LHand",
    18: "RShoulder", 19: "RArm", 20: "RForeArm", 21: "RHand",
}
_EXT_PARENTS = (-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20)
_MAX_KEYFRAMES = 64
_MAX_JOINTS_PER_KEYFRAME = 22
_MAX_PAYLOAD_BYTES = 256 * 1024
_MODEL_FRAMES = 219
_FIDELITY_THRESHOLD_CM = 40.0
_FIDELITY_FAILURE = "authored keyframe fidelity check failed"
_COCO_TO_EXT = {
    "left_hip": 1, "left_knee": 2, "left_ankle": 3,
    "right_hip": 5, "right_knee": 6, "right_ankle": 7,
    "nose": 13, "left_shoulder": 14, "left_elbow": 15,
    "left_wrist": 16, "right_shoulder": 18, "right_elbow": 19,
    "right_wrist": 20,
}


def _scene_to_model_coordinates(point: tuple[float, float, float]) -> list[float]:
    """Convert NeutralMotion scene coordinates to raw LaFAN coordinates.

    NeutralMotion is right-handed with ``(x, y, z)`` meaning horizontal, up,
    and depth. AutoKeyframe's raw LaFAN ``l_position`` is the pre-
    ``rotate_start_to`` skeleton: its X axis is up and its Z axis separates
    left and right. The adapter owns this single boundary transform; the
    isolated helper does not apply another orientation normalization.
    """
    scene_x, scene_y, scene_z = point
    return [-scene_y, scene_z, -scene_x]


def _model_to_scene_coordinates(point: list[float]) -> tuple[float, float, float]:
    """Convert raw LaFAN global positions back to NeutralMotion scene space."""
    model_x, model_y, model_z = point
    return (-model_z, -model_x, model_y)


class AutoKeyframeBackend:
    """Invoke the isolated AutoKeyframe runtime without importing it in-core."""

    def __init__(self, root: Path, timeout_seconds: float, helper: Path) -> None:
        self.root = root
        self.timeout_seconds = timeout_seconds
        self.helper = helper

    def generate(self, conditioning: dict[str, Any]) -> NeutralMotion:
        root = self.root.resolve()
        helper = self.helper.resolve()
        if not root.is_dir() or not helper.is_file():
            raise MotionBackendUnavailable("AutoKeyframe cache or helper is unavailable")
        venv_python = root / "venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        source = root / "source" / "AutoKeyframe-main"
        checkpoint = (
            root / "checkpoint" / "KeyframeGenerator" / "base_model_v2"
            / "checkpoint" / "best.ckpt"
        )
        l_position = root / "checkpoint" / "l_position.npy"
        if not all(path.is_file() for path in (venv_python, checkpoint, l_position)) \
                or not source.is_dir():
            raise MotionBackendUnavailable("AutoKeyframe runtime assets are unavailable")
        try:
            payload = json.dumps(
                _normalize_conditioning(conditioning),
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise MotionBackendUnavailable("AutoKeyframe conditioning is malformed") from exc
        if len(payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise MotionBackendUnavailable("AutoKeyframe conditioning is too large")
        env = os.environ.copy()
        env.update({
            "AUTOKEYFRAME_ROOT": str(root), "AUTOKEYFRAME_SOURCE": str(source),
            "AUTOKEYFRAME_CHECKPOINT": str(checkpoint),
            "AUTOKEYFRAME_L_POSITION": str(l_position),
            "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1",
        })
        try:
            completed = subprocess.run(
                [str(venv_python), str(helper)], input=payload, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds, check=False, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MotionBackendUnavailable("AutoKeyframe helper failed or timed out") from exc
        if completed.returncode != 0:
            raise MotionBackendUnavailable("AutoKeyframe helper returned an error")
        try:
            if len(completed.stdout.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
                raise ValueError("helper output is too large")
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            _validate_authored_fidelity(result, conditioning)
            return _motion_from_result(result, conditioning)
        except MotionBackendUnavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise MotionBackendUnavailable("AutoKeyframe helper returned malformed output") from exc


def _normalize_conditioning(conditioning: Mapping[str, Any]) -> dict[str, Any]:
    """Convert normalized COCO detections to bounded numeric ext-joint hints.

    Coordinates use the wizard convention first (normalized image x/y, with
    y flipped into scene up-Y), then cross the explicit scene-to-raw-LaFAN
    boundary. This is a conditioning approximation, not a visual retargeting
    claim.
    """
    raw_keyframes = conditioning.get("keyframes")
    if not isinstance(raw_keyframes, list) or len(raw_keyframes) > _MAX_KEYFRAMES:
        raise MotionBackendUnavailable("AutoKeyframe keyframe count is out of bounds")
    try:
        duration = int(conditioning.get("duration_frames", _MODEL_FRAMES))
    except (TypeError, ValueError, OverflowError) as exc:
        raise MotionBackendUnavailable("AutoKeyframe duration is malformed") from exc
    if not 1 <= duration <= _MODEL_FRAMES:
        raise MotionBackendUnavailable("AutoKeyframe duration is out of bounds")
    keyframes: list[dict[str, Any]] = []
    for raw in raw_keyframes:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("joints"), Mapping):
            raise MotionBackendUnavailable("AutoKeyframe keyframe is malformed")
        if len(raw["joints"]) > _MAX_JOINTS_PER_KEYFRAME:
            raise MotionBackendUnavailable("AutoKeyframe joint count is out of bounds")
        try:
            frame = max(9, min(218, int(raw["frame"])))
        except (TypeError, ValueError, OverflowError) as exc:
            raise MotionBackendUnavailable("AutoKeyframe keyframe frame is malformed") from exc
        joints: dict[str, list[float]] = {}
        for label, point in raw.get("joints", {}).items():
            ext = _COCO_TO_EXT.get(label)
            if ext is None:
                continue
            if not isinstance(point, list) or len(point) != 3:
                continue
            x, y, z = (float(value) for value in point)
            if any(not math.isfinite(value) or abs(value) > 2.0 for value in (x, y, z)):
                continue
            scene_point = (x * 172.0, (1.0 - y) * 172.0, z * 172.0)
            joints[str(ext)] = _scene_to_model_coordinates(scene_point)
        if "1" in joints and "5" in joints:
            joints["0"] = [
                (joints["1"][axis] + joints["5"][axis]) / 2.0 for axis in range(3)
            ]
        keyframes.append({"frame": frame, "joints": joints})
    return {"duration_frames": duration, "fps": float(conditioning.get("fps", 24.0)),
            "action": 8, "keyframes": keyframes}


def _validate_authored_fidelity(
    result: Mapping[str, Any], conditioning: Mapping[str, Any]
) -> None:
    """Reject model output that does not plausibly preserve authored joints.

    The comparison is made in NeutralMotion scene space at the model's clamped
    keyframe indices.  A 40 cm per-joint bound is deliberately conservative:
    it tolerates model noise but rejects the observed arm rotations.  Pairwise
    direction checks additionally reject left/right or up-axis inversions.
    """
    positions = result.get("global_positions")
    returned_keys = result.get("keyframes")
    raw_keyframes = conditioning.get("keyframes")
    if not isinstance(positions, list) or not isinstance(returned_keys, list):
        raise MotionBackendUnavailable(_FIDELITY_FAILURE)
    if len(positions) != len(returned_keys) or not positions:
        raise MotionBackendUnavailable(_FIDELITY_FAILURE)

    by_frame: dict[int, list[list[float]]] = {}
    for frame, points in zip(returned_keys, positions, strict=True):
        if not isinstance(frame, int) or not isinstance(points, list):
            raise MotionBackendUnavailable(_FIDELITY_FAILURE)
        by_frame[frame] = points

    if not isinstance(raw_keyframes, list):
        raise MotionBackendUnavailable(_FIDELITY_FAILURE)

    checked = 0
    for raw in raw_keyframes:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("joints"), Mapping):
            continue
        clamped = max(9, min(218, int(raw["frame"])))
        model_points = by_frame.get(clamped)
        if model_points is None:
            raise MotionBackendUnavailable(_FIDELITY_FAILURE)

        expected: dict[str, tuple[float, float, float]] = {}
        actual: dict[str, tuple[float, float, float]] = {}
        for label, point in raw["joints"].items():
            ext = _COCO_TO_EXT.get(label)
            if ext is None or not isinstance(point, list) or len(point) != 3:
                continue
            try:
                normalized = tuple(float(value) for value in point)
            except (TypeError, ValueError, OverflowError):
                continue
            if any(not math.isfinite(value) for value in normalized):
                continue
            if ext >= len(model_points) or not isinstance(model_points[ext], list):
                raise MotionBackendUnavailable(_FIDELITY_FAILURE)
            model_point = model_points[ext]
            if len(model_point) != 3:
                raise MotionBackendUnavailable(_FIDELITY_FAILURE)
            try:
                model_values = [float(value) for value in model_point]
            except (TypeError, ValueError, OverflowError):
                raise MotionBackendUnavailable(_FIDELITY_FAILURE) from None
            if any(not math.isfinite(value) for value in model_values):
                raise MotionBackendUnavailable(_FIDELITY_FAILURE)
            scene_point = _model_to_scene_coordinates(model_values)
            expected[label] = (
                normalized[0] * 172.0,
                (1.0 - normalized[1]) * 172.0,
                normalized[2] * 172.0,
            )
            actual[label] = scene_point
            distance = math.sqrt(sum(
                (scene_point[axis] - expected[label][axis]) ** 2 for axis in range(3)
            ))
            if distance > _FIDELITY_THRESHOLD_CM:
                raise MotionBackendUnavailable(_FIDELITY_FAILURE)

        if expected:
            checked += 1
            for left, right in (("left_shoulder", "right_shoulder"),
                                ("left_hip", "right_hip"),
                                ("left_hip", "left_shoulder"),
                                ("right_hip", "right_shoulder")):
                if left not in expected or right not in expected:
                    continue
                expected_vector = tuple(
                    expected[right][axis] - expected[left][axis] for axis in range(3)
                )
                actual_vector = tuple(
                    actual[right][axis] - actual[left][axis] for axis in range(3)
                )
                expected_length = math.sqrt(sum(value * value for value in expected_vector))
                actual_length = math.sqrt(sum(value * value for value in actual_vector))
                if (expected_length >= 10.0 and actual_length >= 10.0
                        and sum(expected_vector[i] * actual_vector[i] for i in range(3)) <= 0):
                    raise MotionBackendUnavailable(_FIDELITY_FAILURE)

    if checked == 0:
        raise MotionBackendUnavailable(_FIDELITY_FAILURE)


def _motion_from_result(result: dict[str, Any], conditioning: dict[str, Any]) -> NeutralMotion:
    positions = result.get("global_positions")
    keyframes = result.get("keyframes")
    if (not isinstance(positions, list) or not positions or len(positions) > _MAX_KEYFRAMES
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
        # The helper returns raw LaFAN globals. Convert exactly once before
        # deriving NeutralMotion locals; root translation is position only and
        # must not be interpreted as a facing rotation.
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
            local = tuple(float(point[i] - parent_point[i] - rest[i]) for i in range(3))
            transforms[name] = Transform3D(translation=local)
        transforms["Hips"] = Transform3D()
        source_frame = keyframes[index]
        frames.append(Frame(frame=source_frame, time=(source_frame - 1) / fps,
                            pose=Pose(transforms=transforms)))
    motion = NeutralMotion(
        meta=NeutralMeta(duration_frames=duration, fps=fps, source_type="autokeyframe"),
        skeleton=DEFAULT_NEUTRAL_SKELETON,
        frames=frames,
    )
    motion.validate_invariants()
    return motion
