"""Cache-local AutoKeyframe child process; invoked only by the adapter."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf

sys.path.insert(0, os.environ["AUTOKEYFRAME_SOURCE"])
os.chdir(os.environ["AUTOKEYFRAME_SOURCE"])
from lightning_modules import load_lightning  # noqa: E402

_PARENTS = [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20]
_MAX_KEYFRAMES = 64
_MAX_JOINTS_PER_KEYFRAME = 22
_MAX_PAYLOAD_BYTES = 256 * 1024
_MODEL_FRAMES = 219
_MODEL = None


def _load_model() -> object:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    source = Path(os.environ["AUTOKEYFRAME_SOURCE"])
    cfg = OmegaConf.load(source / "configs" / "KFG.yaml")
    stats_dir = (
        Path(os.environ["AUTOKEYFRAME_ROOT"])
        / "checkpoint" / "KeyframeGenerator" / "base_model_v2"
    )
    cfg.result_dir = str(stats_dir)
    cfg.lightning_cfg.result_dir = cfg.result_dir
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        model = load_lightning(
            cfg.lightning_module,
            os.environ["AUTOKEYFRAME_CHECKPOINT"],
            cfg.lightning_cfg,
        )
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.l_position = np.load(os.environ["AUTOKEYFRAME_L_POSITION"])
    model.mean = np.load(stats_dir / "mean.npy")
    model.std = np.load(stats_dir / "std.npy")
    _MODEL = model
    return model


def _base_global_positions(l_position: np.ndarray) -> np.ndarray:
    positions = np.zeros((22, 3), dtype=np.float32)
    positions[0] = l_position[0]
    for joint in range(1, 22):
        positions[joint] = positions[_PARENTS[joint]] + l_position[joint]
    return positions


def main() -> None:
    raw_request = sys.stdin.buffer.read(_MAX_PAYLOAD_BYTES + 1)
    if len(raw_request) > _MAX_PAYLOAD_BYTES:
        raise ValueError("request payload is too large")
    request = json.loads(raw_request)
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    raw_keyframes = request.get("keyframes")
    if not isinstance(raw_keyframes, list) or not raw_keyframes:
        raise ValueError("keyframes must be a non-empty list")
    if len(raw_keyframes) > _MAX_KEYFRAMES:
        raise ValueError("too many keyframes")
    duration = int(request.get("duration_frames", _MODEL_FRAMES))
    if not 1 <= duration <= _MODEL_FRAMES:
        raise ValueError("duration is out of bounds")
    if any(not isinstance(item, dict) or not isinstance(item.get("joints"), dict)
           or len(item["joints"]) > _MAX_JOINTS_PER_KEYFRAME for item in raw_keyframes):
        raise ValueError("malformed or oversized keyframe")
    model = _load_model()
    device = next(model.parameters()).device
    frames = _MODEL_FRAMES
    base = _base_global_positions(model.l_position)
    hint = np.repeat(base[None, None, ...], frames, axis=1)
    hint_mask = np.zeros_like(hint, dtype=np.float32)
    keyframes = sorted({
        max(9, min(218, int(item["frame"])))
        for item in request.get("keyframes", [])
    })
    for item in request.get("keyframes", []):
        frame = max(9, min(218, int(item["frame"])))
        for joint, point in item.get("joints", {}).items():
            if not isinstance(joint, str) or not joint.isascii() or not joint.isdecimal():
                continue
            ext = int(joint)
            if 0 <= ext < 22:
                hint[0, frame, ext] = point
                hint_mask[0, frame, ext] = 1.0
    traj = hint[0, :, 0]
    if not keyframes:
        raise ValueError("at least one valid keyframe is required")
    traj_tensor = torch.tensor(traj, dtype=torch.float32, device=device).unsqueeze(0)
    hint_tensor = torch.tensor(hint, dtype=torch.float32, device=device)
    mask_tensor = torch.tensor(hint_mask, dtype=torch.float32, device=device)
    action = torch.tensor([[int(request.get("action", 8))]], dtype=torch.float32, device=device)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with torch.no_grad():
            rotations, root_translations, generated_keys = model.generate_from_traj_and_hints(
                traj_tensor, hint_tensor, mask_tensor, action, None,
                keyframes_list=[keyframes],
            )
    rotations = rotations[0].detach()
    root_translations = root_translations[0].detach()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from utils.skeleton_torch import SkeletonMotionTorch

    skeleton = SkeletonMotionTorch()
    lpos = torch.tensor(
        np.repeat(model.l_position[None], rotations.shape[0], axis=0),
        dtype=torch.float32, device=device,
    ).unsqueeze(0)
    skeleton.from_parent_array(_PARENTS, lpos)
    skeleton.apply_pose(root_translations, rotations.unsqueeze(1))
    global_positions = skeleton.joints_global_positions[:, 0].detach().cpu().numpy()
    returned_keys = generated_keys[0]
    if hasattr(returned_keys, "detach"):
        returned_keys = returned_keys.detach().cpu().tolist()
    elif hasattr(returned_keys, "tolist"):
        returned_keys = returned_keys.tolist()
    returned_keys = [int(value) for value in returned_keys]
    output = json.dumps({"keyframes": returned_keys, "global_positions": global_positions.tolist()})
    if len(output.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("response payload is too large")
    print(output)


if __name__ == "__main__":
    main()
