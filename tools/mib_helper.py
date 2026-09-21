"""Cache-local MIB (motion in-betweening) child process; invoked only by the adapter.

Loads the pretrained MIB models ("lafan1_context_model_release" and
"lafan1_detail_model_release", TOG 2022) inside a private cache-local venv
and generates a transition between every consecutive pair of authored
keyframes.

Protocol
--------
Reads a single bounded JSON request (max 256 KiB) from stdin:

    {"duration_frames": int, "fps": float,
     "keyframes": [{"frame": int, "joints": {"0": [x, y, z], ...}}, ...]}

Keyframe joint indices are external decimal strings "0".."21"; the
coordinates are raw LaFAN global positions in cm (the adapter already
converted scene coordinates into raw LaFAN space; no axis conversion is done
here). Writes a single JSON object to stdout:

    {"keyframes": [int, ...], "global_positions": [[[x, y, z] x 22], ...]}

The output frame indices are strictly increasing and clamped to 9..218.

Conditioning approximation
-------------------------
The model reads only the root position and the local rotations (6D flattened);
non-root local positions never enter ``get_model_input``, they only matter for
forward kinematics of the output. The authored pose is therefore encoded in
rotations. For the context and target frames we set ``R_local = I`` and use
"deformed" local positions ``pose[j] - pose[parent]``. With identity global
rotations the LaFAN FK (``gp_j = gp_parent + gr_parent @ lpos_j``) then
reproduces the authored global pose exactly from those local positions —
without solving an underdetermined rigid-retargeting problem. This is a
conditioning approximation (the frames are not poses a rigid LaFAN skeleton
could produce with constant offsets), but it is the minimal representation
that keeps the 40 cm authored-fidelity gate meaningful.

Transition length
-----------------
Between keyframes A (frame fA) and B (frame fB) the transition length is
``fB - fA - 1``. It is clamped up to 5 frames, and a length above 53 frames
raises ``ValueError("transition too long")`` so the adapter can fall back to
procedural interpolation. With ``context_len = 10``, ``window_len =
context_len + trans_len + 2`` stays within the model's ``max_seq_len = 65``.

The two-stage evaluation (context transformer, then detail transformer) runs
in the start-centered frame as required by the models; the FK output is
transformed back to the authored/raw frame using the recorded centering
offsets before being emitted.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, os.environ["MIB_SOURCE"])
sys.path.insert(0, os.path.join(os.environ["MIB_SOURCE"], "packages"))
os.chdir(os.environ["MIB_SOURCE"])
from motion_inbetween.config import Config  # noqa: E402
from motion_inbetween.data import utils_torch as data_utils  # noqa: E402
from motion_inbetween.model import ContextTransformer, DetailTransformer  # noqa: E402
from motion_inbetween.train import context_model as ctx_mdl  # noqa: E402
from motion_inbetween.train import detail_model as det_mdl  # noqa: E402

_PARENTS = [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20]
_NUM_JOINTS = 22
_MAX_KEYFRAMES = 64
_MAX_JOINTS_PER_KEYFRAME = 22
_MAX_PAYLOAD_BYTES = 256 * 1024
_MODEL_FRAMES = 219
_CONTEXT_LEN = 10
_MIN_TRANS = 5
# window_len = context_len + trans_len + 2 <= model max_seq_len = 65
_MAX_TRANS = 53
_MODEL = None


class _ModelBundle:
    """Loaded MIB models, release configs, train stats and l-position offsets."""

    def __init__(self, context_model: object, detail_model: object,
                 ctx_config: dict, det_config: dict,
                 mean_ctx: torch.Tensor, std_ctx: torch.Tensor,
                 mean_state: torch.Tensor, std_state: torch.Tensor,
                 device: str, l_position: np.ndarray) -> None:
        self.context_model = context_model
        self.detail_model = detail_model
        self.ctx_config = ctx_config
        self.det_config = det_config
        self.mean_ctx = mean_ctx
        self.std_ctx = std_ctx
        self.mean_state = mean_state
        self.std_state = std_state
        self.device = device
        self.l_position = l_position


def _load_model() -> _ModelBundle:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    source = Path(os.environ["MIB_SOURCE"])
    pretrained = Path(os.environ["MIB_PRETRAINED"])
    ctx_dir = pretrained / "lafan1_context_model_release"
    det_dir = pretrained / "lafan1_detail_model_release"
    ctx_cfg_path = str(source / "configs" / "lafan1_context_model.json")
    det_cfg_path = str(source / "configs" / "lafan1_detail_model.json")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ctx_config = Config(json.load(open(ctx_cfg_path)), ctx_cfg_path)
        det_config = Config(json.load(open(det_cfg_path)), det_cfg_path)
        mean_ctx, std_ctx = ctx_mdl.get_train_stats(
            ctx_config, use_cache=True, stats_folder=str(ctx_dir))
        mean_state, std_state, _, _ = det_mdl.get_train_stats(
            det_config, use_cache=True, stats_folder=str(det_dir))
        context_model = ContextTransformer(ctx_config["model"]).to(device)
        detail_model = DetailTransformer(det_config["model"]).to(device)
        context_model.load_state_dict(torch.load(
            str(ctx_dir / "checkpoint_lafan1_context_model_release.pth"),
            map_location=device)["model"])
        detail_model.load_state_dict(torch.load(
            str(det_dir / "checkpoint_lafan1_detail_model_release.pth"),
            map_location=device)["model"])
        context_model.eval()
        detail_model.eval()
    dtype = torch.float32
    l_position = np.asarray(np.load(os.environ["MIB_L_POSITION"]), dtype=np.float64)
    bundle = _ModelBundle(
        context_model, detail_model, ctx_config, det_config,
        torch.tensor(mean_ctx, dtype=dtype, device=device),
        torch.tensor(std_ctx, dtype=dtype, device=device),
        torch.tensor(mean_state, dtype=dtype, device=device),
        torch.tensor(std_state, dtype=dtype, device=device),
        device, l_position,
    )
    _MODEL = bundle
    return bundle


def _base_global_positions(l_position: np.ndarray) -> np.ndarray:
    """Rest-pose global positions built from the constant l-position offsets."""
    positions = np.zeros((_NUM_JOINTS, 3), dtype=np.float64)
    positions[0] = l_position[0]
    for joint in range(1, _NUM_JOINTS):
        positions[joint] = positions[_PARENTS[joint]] + l_position[joint]
    return positions


def _offset_local_pose(pose: np.ndarray) -> np.ndarray:
    """Local positions (22, 3) that the LaFAN FK reproduces as the authored pose.

    ``gp_j = gp_parent + gr_parent @ lpos_j``; with identity global rotations,
    setting ``lpos_j = pose[j] - pose[parent]`` yields FK output exactly equal
    to ``pose``, avoiding an underdetermined rigid-retargeting solve.
    """
    local = np.zeros((_NUM_JOINTS, 3), dtype=np.float64)
    local[0] = pose[0]
    for joint in range(1, _NUM_JOINTS):
        local[joint] = pose[joint] - pose[_PARENTS[joint]]
    return local


def _ease(t: float, v: float = 0.8) -> float:
    """Hermite easing with residual endpoint velocity.

    ``p(0) = 0``, ``p(1) = 1``, ``p'(0) = p'(1) = v > 0``: the curve flows
    through the keyframe instead of stopping (smoothstep would freeze at each
    golden pose). Monotonic and overshoot-free for ``0 < v <= 1``.
    """
    return (2 * v - 2) * t ** 3 + (3 - 3 * v) * t ** 2 + v * t


def _build_window(pose_a: np.ndarray, pose_b: np.ndarray, trans_len: int,
                  l_position: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build a MIB input window (local positions + local rotations) for a pair.

    pose_a/pose_b are authored (22, 3) global positions in cm. Context frames
    carry pose A, the target frame and the extra post-process frame carry
    pose B, and in-between frames carry the eased interpolation of
    pose A->B for ALL joints (the motion flows through poses instead of
    stopping at them: endpoint velocity is non-zero). Non-root local positions
    are parent-frame deltas ``pose[j] - pose[parent]`` so the LaFAN FK
    reproduces the authored globals exactly in the context/target frames
    (which ``get_new_positions`` never overwrites), and the interpolated deltas
    keep the in-between skeleton shaped like the author's motion instead of
    the LaFAN rest pose. Rotations are identity: the model reads rotated poses
    from local rotations, not from non-root positions.
    """
    target_idx = _CONTEXT_LEN + trans_len
    window_len = _CONTEXT_LEN + trans_len + 2
    local_a = _offset_local_pose(pose_a)
    local_b = _offset_local_pose(pose_b)
    positions = np.repeat(l_position[None, ...], window_len, axis=0)
    positions[:_CONTEXT_LEN, :, :] = local_a
    for frame in range(_CONTEXT_LEN, target_idx):
        t = _ease((frame - (_CONTEXT_LEN - 1)) / (target_idx - (_CONTEXT_LEN - 1)))
        positions[frame, :, :] = local_a + (local_b - local_a) * t
    positions[target_idx:, :, :] = local_b  # target frame + extra frame

    rotations = np.tile(np.eye(3, dtype=np.float64), (window_len, _NUM_JOINTS, 1, 1))
    return positions.astype(np.float32), rotations.astype(np.float32)


def _uncenter_global_positions(gp: torch.Tensor,
                               root_pos_offset: torch.Tensor,
                               root_rot_offset: torch.Tensor) -> torch.Tensor:
    """Reverse the start-centering on FK output (returns the raw frame)."""
    yaw_inv = root_rot_offset.transpose(-1, -2)
    gp = torch.matmul(yaw_inv, gp.unsqueeze(-1)).squeeze(-1)
    out = gp.clone()
    out[..., 0] = out[..., 0] + root_pos_offset[..., 0]
    out[..., 2] = out[..., 2] + root_pos_offset[..., 1]
    return out


def _process_pair(bundle: _ModelBundle, pose_a: np.ndarray, pose_b: np.ndarray,
                  trans_len: int) -> np.ndarray:
    """Run the two-stage MIB evaluation for one transition window."""
    device = bundle.device
    dtype = torch.float32
    target_idx = _CONTEXT_LEN + trans_len
    window_len = _CONTEXT_LEN + trans_len + 2
    seq_slice = slice(_CONTEXT_LEN, target_idx)

    positions, rotations = _build_window(pose_a, pose_b, trans_len, bundle.l_position)
    positions_t = torch.tensor(positions[None, ...], dtype=dtype, device=device)
    rotations_t = torch.tensor(rotations[None, ...], dtype=dtype, device=device)
    with torch.no_grad():
        positions_t, rotations_t, root_pos_offset, root_rot_offset = \
            data_utils.to_start_centered_data(
                positions_t, rotations_t, _CONTEXT_LEN, return_offset=True)
    foot_contact = torch.ones((1, window_len, 4), dtype=dtype, device=device)

    indices = bundle.ctx_config["indices"]
    atten_mask_ctx = ctx_mdl.get_attention_mask(
        window_len, _CONTEXT_LEN, target_idx, device)
    atten_mask = det_mdl.get_attention_mask(window_len, target_idx, device)

    with torch.no_grad(), \
            contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        ctx_mdl.evaluate(
            bundle.context_model, positions_t, rotations_t, seq_slice,
            indices, bundle.mean_ctx, bundle.std_ctx, atten_mask_ctx,
            post_process=True)
        pos_new, rot_new, _ = det_mdl.evaluate(
            bundle.detail_model, bundle.context_model, positions_t,
            rotations_t, foot_contact, seq_slice, indices,
            bundle.mean_ctx, bundle.std_ctx, bundle.mean_state,
            bundle.std_state, atten_mask, atten_mask_ctx, post_process=True)
        _, gp = data_utils.fk_torch(
            rot_new, pos_new,
            torch.tensor(_PARENTS, dtype=torch.long, device=device))
        gp = _uncenter_global_positions(gp, root_pos_offset, root_rot_offset)
    return gp.detach().cpu().numpy()[0]


def _parse_keyframes(request: dict,
                     l_position: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Validate the request and return sorted, deduplicated (frame, pose) pairs."""
    raw_keyframes = request.get("keyframes")
    if not isinstance(raw_keyframes, list) or not raw_keyframes:
        raise ValueError("keyframes must be a non-empty list")
    if len(raw_keyframes) > _MAX_KEYFRAMES:
        raise ValueError("too many keyframes")
    if any(not isinstance(item, dict) or not isinstance(item.get("joints"), dict)
           or len(item["joints"]) > _MAX_JOINTS_PER_KEYFRAME
           for item in raw_keyframes):
        raise ValueError("malformed or oversized keyframe")
    parsed = {}
    for item in raw_keyframes:
        frame = max(9, min(218, int(item["frame"])))
        pose = _base_global_positions(l_position)
        for key, point in item["joints"].items():
            if not isinstance(key, str) or not key.isascii() or not key.isdecimal():
                continue
            ext = int(key)
            if not 0 <= ext < _NUM_JOINTS:
                continue
            if (not isinstance(point, (list, tuple)) or len(point) != 3
                    or any(not isinstance(value, (int, float))
                           or isinstance(value, bool) for value in point)):
                raise ValueError("malformed joint coordinate")
            values = [float(value) for value in point]
            if any(not math.isfinite(value) for value in values):
                raise ValueError("non-finite joint coordinate")
            pose[ext] = values
        parsed[frame] = pose
    return sorted(parsed.items())


def main() -> None:
    raw_request = sys.stdin.buffer.read(_MAX_PAYLOAD_BYTES + 1)
    if len(raw_request) > _MAX_PAYLOAD_BYTES:
        raise ValueError("request payload is too large")
    request = json.loads(raw_request)
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    duration = int(request.get("duration_frames", _MODEL_FRAMES))
    if not 1 <= duration <= _MODEL_FRAMES:
        raise ValueError("duration is out of bounds")
    fps = request.get("fps")
    if fps is not None and (not isinstance(fps, (int, float))
                            or isinstance(fps, bool)
                            or not math.isfinite(fps) or fps <= 0.0):
        raise ValueError("fps is invalid")
    bundle = _load_model()
    keyframes = _parse_keyframes(request, bundle.l_position)
    if len(keyframes) < 2:
        raise ValueError("at least two valid keyframes are required")

    entries = {}
    for index in range(len(keyframes) - 1):
        frame_a, pose_a = keyframes[index]
        frame_b, pose_b = keyframes[index + 1]
        trans_len = frame_b - frame_a - 1
        if trans_len > _MAX_TRANS:
            raise ValueError("transition too long")
        if trans_len < _MIN_TRANS:
            trans_len = _MIN_TRANS
        gp = _process_pair(bundle, pose_a, pose_b, trans_len)
        target_idx = _CONTEXT_LEN + trans_len
        # Only the generated in-between frames and the target frame are
        # emitted; the first keyframe of the sequence keeps its single pose
        # A frame (setdefault: already written targets win). The 9 preceding
        # frozen context frames stay internal to the model window: emitting
        # them made the preview freeze on each golden pose.
        entries.setdefault(frame_a, gp[_CONTEXT_LEN - 1])
        for window_frame, absolute in zip(
                range(_CONTEXT_LEN, target_idx), range(frame_a + 1, frame_b),
                strict=True):
            entries.setdefault(absolute, gp[window_frame])
        entries.setdefault(frame_b, gp[target_idx])

    frames = sorted(entries)
    # Round to 3 decimals: keeps the payload far below the size bound while
    # avoiding long float32->float64 reprs.
    global_positions = [
        [[round(float(value), 3) for value in point] for point in entries[frame]]
        for frame in frames
    ]
    output = json.dumps({"keyframes": frames, "global_positions": global_positions})
    if len(output.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("response payload is too large")
    print(output)


if __name__ == "__main__":
    main()