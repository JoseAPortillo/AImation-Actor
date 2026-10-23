"""HMR2.0 engine worker: the engine-side half of the adapter bridge.

This script runs in the engine's own Python 3.10 environment — never in the
application process (S14, the same isolation as the Blender read path). It
speaks a line-JSON protocol over stdin/stdout:

    bootstrap (adapter -> worker): {"hmr2_root", "checkpoint", "smpl_dir",
                                    "half_precision"}
    ready     (worker -> adapter): {"status": "ready", "gpu", "vram_total_mib",
                                    "template_hip_height_cm", "bind_offsets_cm"}
    request   (adapter -> worker): {"image_path", "frame_index"}
    response: {"status": "ok", "per_frame_hip_height_m",
               "root_translation": [x, y, z],
               "rotations": {joint_name: [9 floats, row-major 3x3]}}
               | {"status": "error", "message", "fatal": false}  (worker stays up)

The worker owns every Windows fix the engine stack needs (recorded in
``odd/tasks/m5-pose-extraction.md`` L21/L23; no vendored engine line changes):

- ``HOME`` must point at the engine root, because ``hmr2/configs`` builds its
  cache from ``HOME/.cache`` and Windows supplies no ``HOME``;
- ``PYOPENGL_PLATFORM`` must be pre-set (``win32``), because
  ``hmr2/utils/renderer`` forces ``egl`` unless it is already set and EGL does
  not exist on Windows — note ``win32`` only satisfies the *import*: the model
  is loaded with ``init_renderer=False`` because pyrender's
  ``OffscreenRenderer`` supports egl/osmesa only, and this tool never renders;
- ``torch.load`` is overridden to ``weights_only=False``: torch >= 2.6 defaults
  to True and the checkpoint carries omegaconf objects;
- half precision runs under ``torch.autocast``: the backbone and the SMPL
  recovery both need mixed-input handling (plain ``half()`` inputs raise
  ``mat1/mat2`` dtype mismatches — measured, T13 probe);
- the SMPL body model and the checkpoint are **user-supplied** (S16); their
  existence is validated before anything loads.

The ready line also carries the **bind offsets** of the production skeleton:
SMPL's T-pose joint positions from the body model (``J_regressor @
v_template``), parent-relative, named for SMPL's canonical order — real model
data no caller may invent.

The worker is persistent: the checkpoint (2.7 GB) loads once, then every
request is a single inference (~84 ms measured). ``empty_cache()`` runs after
each successful inference so VRAM does not grow across keys (FR-CAP-05).
"""

from __future__ import annotations

import json
import os
import sys


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


class _NullContext:
    """The no-op stand-in for ``torch.autocast`` on the fp32 path."""

    def __enter__(self) -> _NullContext:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


#: The 23 body joints after the pelvis, in SMPL's canonical order (joints
#: 1..23 of the 24-joint body model). The pelvis itself is ``global_orient``
#: and is emitted as ``"Pelvis"``. These names are the production skeleton's
#: names too: the production hierarchy mirrors SMPL's chain under ``Main``.
SMPL_BODY_JOINT_NAMES = (
    "L_Hip",
    "R_Hip",
    "Spine_1",
    "L_Knee",
    "R_Knee",
    "Spine_2",
    "L_Ankle",
    "R_Ankle",
    "Spine_3",
    "L_Foot",
    "R_Foot",
    "Neck",
    "L_Collar",
    "R_Collar",
    "Head",
    "L_Shoulder",
    "R_Shoulder",
    "L_Elbow",
    "R_Elbow",
    "L_Wrist",
    "R_Wrist",
    "L_Hand",
    "R_Hand",
)


def _prepare_environment(engine_root: str) -> None:
    """Set the env the engine stack requires before any engine import."""
    os.environ.setdefault("HOME", engine_root)
    os.environ.setdefault("PYOPENGL_PLATFORM", "win32")


def _template_hip_height_cm(model) -> tuple[float, int]:
    """The betas=0 template's pelvis-to-contact distance, in centimetres.

    This is the adapter's hip-height anchor: the per-frame weak-perspective
    estimate is not keyable (measured, T10 — 0.59-0.99 m within one person),
    while this constant is exact by construction. The axis is discovered, not
    assumed: SMPL's canonical frame is Y-up, but the discovery keeps the
    constant honest if that ever changes. The axis is returned because the
    bind-offset conversion needs the same discovery.
    """
    import torch

    # a half-precision model needs the same mixed-input handling as a request:
    # the identity forward runs under autocast (measured, T13 probe)
    half = next(model.parameters()).dtype == torch.float16
    context = (
        torch.autocast(device_type="cuda", dtype=torch.float16)
        if half
        else _NullContext()
    )
    identity = torch.eye(3, device=next(model.parameters()).device).reshape(1, 1, 3, 3)
    with torch.no_grad(), context:
        output = model.smpl(
            global_orient=identity,
            body_pose=identity.reshape(1, 1, 3, 3).repeat(1, 23, 1, 1),
            betas=torch.zeros(1, 10, device=identity.device),
            pose2rot=False,
        )
    joints = output.joints[0]  # OpenPose BODY_25 order: 8=MidHip, 19-24 feet
    vertices = output.vertices[0]
    axis = int(torch.tensor([
        abs(joints[8, k].item() - joints[19:25, k].min().item()) for k in range(3)
    ]).argmax().item())
    pelvis = joints[8, axis].item()
    contact = vertices[:, axis].min().item()
    return (pelvis - contact) * 100.0, axis


def _template_bind_offsets_cm(model, hip_height_cm: float, up_axis: int) -> dict[str, list[float]]:
    """The production skeleton's bind offsets, from the body model's template.

    SMPL's T-pose joint positions come from the wrapper's own buffers
    (``J_regressor @ v_template`` — measured identical to the OpenPose pelvis
    row of the anchor call): body offsets are parent-relative and the pelvis's
    vertical is the hip-height anchor, because ``Main`` sits on the ground
    plane. They are reported in **SMPL's own Y-up frame, in centimetres** — the
    same engine-speak rule as the rotations: the worker never converts frames,
    the adapter owns the SMPL -> domain conversion. Real model data; nothing
    invented.
    """

    if up_axis != 1:
        raise RuntimeError(
            f"the body model's template is not Y-up (discovered vertical axis {up_axis}); "
            "the hip-height anchor assumes SMPL's canonical frame"
        )

    wrapper = model.smpl
    positions = (wrapper.J_regressor.float() @ wrapper.v_template.float()).cpu()
    parents = [int(p) for p in wrapper.parents.cpu().tolist()]
    if positions.shape != (len(SMPL_BODY_JOINT_NAMES) + 1, 3):
        raise RuntimeError(
            f"the body model's template joints are malformed: {positions.shape}"
        )

    names = ("Pelvis", *SMPL_BODY_JOINT_NAMES)
    offsets: dict[str, list[float]] = {}
    for index, name in enumerate(names):
        source = positions[index] if index == 0 else positions[index] - positions[parents[index]]
        x, y, z = (float(value) * 100.0 for value in source)
        offsets[name] = [x, y, z]
    # ``Main`` sits on the ground: the pelvis's height above the contact plane
    # is the anchor the hip heights key against, not the template's raw ordinate.
    offsets["Pelvis"][1] = hip_height_cm
    return offsets


def _load_model(hmr2_root: str, checkpoint: str, smpl_dir: str, half_precision: bool):
    sys.path.insert(0, hmr2_root)


    import torch

    original_load = torch.load

    def forced_weights_only_load(path, *args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(path, *args, **kwargs)

    torch.load = forced_weights_only_load

    from hmr2.configs import get_config
    from hmr2.models import check_smpl_exists
    from hmr2.models.hmr2 import HMR2

    model_cfg = get_config(
        str(os.path.join(os.path.dirname(checkpoint), os.pardir, "model_config.yaml")),
        update_cachedir=True,
    )
    if (model_cfg.MODEL.BACKBONE.TYPE == "vit") and ("BBOX_SHAPE" not in model_cfg.MODEL):
        model_cfg.defrost()
        model_cfg.MODEL.BBOX_SHAPE = [192, 256]
        model_cfg.freeze()
    if not os.path.isfile(os.path.join(smpl_dir, "SMPL_NEUTRAL.pkl")):
        raise FileNotFoundError(
            f"the SMPL body model was not found at {smpl_dir} — it is user-supplied"
            " (register at https://smplify.is.tue.mpg.de/)"
        )
    check_smpl_exists()
    model = HMR2.load_from_checkpoint(
        checkpoint, strict=False, cfg=model_cfg, init_renderer=False
    ).cuda().eval()
    if half_precision:
        model.half()
    return model, model_cfg


def _run_request(model, model_cfg, request: dict, torch) -> dict:
    import cv2
    import numpy as np
    from hmr2.datasets.vitdet_dataset import ViTDetDataset

    image_path = request["image_path"]
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return {
            "status": "error",
            "fatal": False,
            "message": f"the frame image is unreadable: {image_path}",
        }

    height, width = img_bgr.shape[:2]
    box = np.array([0.0, 0.0, float(width), float(height)], dtype=np.float32)
    dataset = ViTDetDataset(model_cfg, img_bgr, box.reshape(1, 4))
    from torch.utils.data.dataloader import default_collate

    batch = default_collate([dataset[0]])
    batch = {k: v.cuda() if torch.is_tensor(v) else v for k, v in batch.items()}

    # Half precision runs under autocast with half inputs: the backbone and
    # the SMPL recovery both need mixed-input handling (plain half inputs
    # raise dtype mismatches through the ViTDet stack — measured, T13 probe).
    half = next(model.parameters()).dtype == torch.float16
    if half:
        batch = {k: (v.half() if v.is_floating_point() else v) for k, v in batch.items()}
    autocast = (
        torch.autocast(device_type="cuda", dtype=torch.float16)
        if half
        else _NullContext()
    )

    with torch.no_grad(), autocast:
        output = model(batch)
        params = {k: v.float() for k, v in output["pred_smpl_params"].items()}
        pred_cam_t = output["pred_cam_t"].float()
        smpl_output = model.smpl(**params, pose2rot=False)
    torch.cuda.empty_cache()

    rotations = {}
    global_orient = params["global_orient"].reshape(-1, 3, 3)[0]
    rotations["Pelvis"] = [float(v) for v in global_orient.reshape(-1)]
    body = params["body_pose"].reshape(-1, 3, 3)
    for index, name in enumerate(SMPL_BODY_JOINT_NAMES, start=1):
        rotations[name] = [float(v) for v in body[index - 1].reshape(-1)]

    # The per-frame distance is informational (the anchor is the template's).
    joints = smpl_output.joints[0]
    vertices = smpl_output.vertices[0]
    root_translation = joints[0] + pred_cam_t[0]
    axis = int(torch.tensor([
        abs(joints[8, k].item() - joints[19:25, k].min().item()) for k in range(3)
    ]).argmax().item())
    per_frame = joints[8, axis].item() - vertices[:, axis].min().item()

    return {
        "status": "ok",
        "frame_index": request.get("frame_index"),
        "per_frame_hip_height_m": per_frame,
        "root_translation": [float(v) for v in root_translation],
        "vram_allocated_mib": torch.cuda.memory_allocated() / 1024**2,
        "rotations": rotations,
    }


def main() -> None:
    bootstrap = json.loads(sys.stdin.readline())
    engine_root = bootstrap["engine_root"]
    hmr2_root = bootstrap["hmr2_root"]
    checkpoint = bootstrap["checkpoint"]
    smpl_dir = bootstrap["smpl_dir"]
    half_precision = bool(bootstrap.get("half_precision", True))

    _prepare_environment(engine_root)

    try:
        import torch
    except Exception as error:  # noqa: BLE001 - the protocol needs a message
        _emit({
            "status": "error",
            "fatal": True,
            "message": f"torch is unavailable in the engine environment: "
                       f"{type(error).__name__}: {error}",
        })
        return

    try:
        model, model_cfg = _load_model(hmr2_root, checkpoint, smpl_dir, half_precision)
    except Exception as error:  # noqa: BLE001 - the protocol needs a message
        _emit({"status": "error", "fatal": True, "message": f"{type(error).__name__}: {error}"})
        return

    try:
        total_vram = torch.cuda.get_device_properties(0).total_memory / 1024**2
        gpu_name = torch.cuda.get_device_name(0)
    except Exception:  # noqa: BLE001 - diagnostics only
        gpu_name, total_vram = "unknown", 0.0

    # R4-4 (the review's advisory): the template section runs outside the
    # model-load guard — a failure here must not blame the checkpoint; it is
    # a body-model problem, and it is fatal because the hip-height anchor is
    # the template's.
    try:
        hip_height_cm, up_axis = _template_hip_height_cm(model)
        bind_offsets_cm = _template_bind_offsets_cm(model, hip_height_cm, up_axis)
    except Exception as error:  # noqa: BLE001 - the protocol needs a message
        _emit({
            "status": "error",
            "fatal": True,
            "message": f"the body model's template is unusable: {type(error).__name__}: {error}\n"
                       "this is the hip-height anchor and the production rig's bind; "
                       "check that the SMPL body model is the one the adapter configures",
        })
        return

    _emit({
        "status": "ready",
        "gpu": gpu_name,
        "vram_total_mib": total_vram,
        "template_hip_height_cm": hip_height_cm,
        "bind_offsets_cm": bind_offsets_cm,
    })

    for line in sys.stdin:
        request = json.loads(line)
        try:
            _emit(_run_request(model, model_cfg, request, torch))
        except Exception as error:  # noqa: BLE001 - the protocol needs a message
            _emit({
                "status": "error",
                "fatal": False,
                "message": f"{type(error).__name__}: {error}",
            })


if __name__ == "__main__":
    main()
