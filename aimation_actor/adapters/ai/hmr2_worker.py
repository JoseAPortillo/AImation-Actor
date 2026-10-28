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
               "projected_joints": {joint_name: [x_px, y_px]},
               "person_bbox": [x1, y1, x2, y2] | None, "detector": name,
               "rotations": {joint_name: [9 floats, row-major 3x3]}}
               | {"status": "error", "message", "fatal": false}  (worker stays up)

Person detection (M8, S7): the root-depth component ``tz`` comes from
``2 * focal_length / (box_size * pred_cam_scale)``, so the full-frame box the
worker used to hardcode pinned depth to a near-constant. Each request now
detects the largest high-scoring person with torchvision's Faster R-CNN
(MobileNetV3-FPN, COCO weights — the engine environment already ships
torchvision; the ~75 MB weights download once into the engine's torch cache on
first use), margins that box around its center, and feeds it to ViTDetDataset.
When no detector is usable (torchvision missing, weights unreachable, no
person found) the worker honestly falls back to the full-frame box and names
the fallback in ``"detector"`` — never a fabricated trajectory (S4).

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


# -- automatic person detection (M8, S7) --------------------------------------- #

#: COCO category id for ``person`` in torchvision's detection models.
COCO_PERSON_LABEL = 1

#: Below this the detection is not trusted as the capture subject.
MIN_PERSON_SCORE = 0.4

#: Padding around the detected box, about its center. The dataset re-expands
#: to the model's crop aspect itself (``expand_to_aspect_ratio``); this margin
#: only keeps limbs the tight detector box may clip.
DETECTION_MARGIN = 1.2

#: Name reported in the response when no detector is usable and the
#: historical full-frame box is kept.
FULL_FRAME_DETECTOR = "full-frame-fallback"

#: The torchvision model behind the ``detector`` callable.
_PERSON_MODEL_NAME = "fasterrcnn_mobilenet_v3_large_320_fpn"


def pick_best_person(boxes, scores, labels):
    """The largest-area box among persons scoring at least MIN_PERSON_SCORE.

    Score first filters, area then decides between several people: the capture
    subject fills a large share of a reference-video frame, background people
    are smaller (probed on the JACE clip: score 1.0, 65-73% frame height).
    Pure-Python over any sequence shape so tests need no torch.
    """
    best = None
    best_area = 0.0
    for box, score, label in zip(boxes, scores, labels, strict=True):
        if int(label) != COCO_PERSON_LABEL or float(score) < MIN_PERSON_SCORE:
            continue
        x1, y1, x2, y2 = (float(value) for value in box)
        if x2 <= x1 or y2 <= y1:
            continue  # degenerate detection
        area = (x2 - x1) * (y2 - y1)
        if area > best_area:
            best, best_area = [x1, y1, x2, y2], area
    return best


def _box_with_margin(box, image_size, *, margin: float = DETECTION_MARGIN) -> list[float]:
    """Grow a detection box by ``margin`` about its center, clamped to the image."""
    width, height = image_size
    x1, y1, x2, y2 = box
    center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    half_w, half_h = (x2 - x1) * margin / 2.0, (y2 - y1) * margin / 2.0
    return [
        max(0.0, center_x - half_w),
        max(0.0, center_y - half_h),
        min(float(width), center_x + half_w),
        min(float(height), center_y + half_h),
    ]


def detect_person_box(detector, image):
    """One detection pass -> the best person box, or ``None`` honestly.

    ``detector(image)`` returns the torchvision dict (``boxes``/``scores``/
    ``labels``). Any miss or failure is ``None`` — the caller falls back to
    the full-frame box and says so in the response (S4: no fake trajectory).
    The result read is duck-typed (``tolist`` when present) so the box logic
    stays testable without the torch stack.
    """
    if detector is None or image is None:
        return None
    try:
        try:
            import torch

            context = torch.no_grad()
        except ImportError:  # tests run without torch; fakes need no grad anyway
            context = _NullContext()
        with context:
            output = detector(image)[0]
        boxes = _as_plain_list(output["boxes"])
        scores = _as_plain_list(output["scores"])
        labels = _as_plain_list(output["labels"])
        return pick_best_person(boxes, scores, labels)
    except Exception:  # noqa: BLE001 - any detection miss is an honest fallback
        return None


def _as_plain_list(value):
    tolist = getattr(value, "tolist", None)
    return tolist() if tolist is not None else list(value)


def _resolve_request_box(detector, image, image_size, fallback_box, *, margin=DETECTION_MARGIN):
    """The crop box for one request, plus the detector name that produced it.

    A detection is margined around its center (clamped to the image); any miss
    keeps the historical full-frame box and names the fallback honestly.
    """
    found = detect_person_box(detector, image)
    if found is None:
        return list(fallback_box), FULL_FRAME_DETECTOR
    return _box_with_margin(found, image_size, margin=margin), _PERSON_MODEL_NAME


_PERSON_DETECTOR: object | None = None
_PERSON_DETECTOR_FAILED = False


def _get_person_detector():
    """Lazy-load the torchvision person detector (returns None once it failed).

    The returned callable takes the decoded BGR array from ``cv2.imread`` and
    hands the model the RGB float tensor it expects. The weights (~75 MB)
    download on first use into the engine's torch cache; a missing torchvision,
    unreachable download, or CUDA failure disables detection for the worker's
    whole life — the per-request fallback then keeps the historical behavior
    instead of erroring out every capture.
    """
    global _PERSON_DETECTOR, _PERSON_DETECTOR_FAILED
    if _PERSON_DETECTOR is not None or _PERSON_DETECTOR_FAILED:
        return _PERSON_DETECTOR
    try:
        import torch
        import torchvision

        model = torchvision.models.detection.fasterrcnn_mobilenet_v3_large_320_fpn(
            weights="COCO_V1"
        )
        model.eval()
        model.cuda()

        def detect(image_bgr):
            rgb = image_bgr[:, :, ::-1].copy()
            tensor = torch.as_tensor(rgb).permute(2, 0, 1).float().div_(255.0)
            return model([tensor.cuda(non_blocking=True)])

        _PERSON_DETECTOR = detect
    except Exception as error:  # noqa: BLE001 - the fallback must stay silent-but-named
        _PERSON_DETECTOR_FAILED = True
        # Not a protocol line (no "status"): the adapter skips it as engine
        # print. A detection miss must never fail an extraction request (S4).
        _emit(
            {
                "engine_notice": "person detection unavailable "
                f"({type(error).__name__}: {error}); "
                "root depth will keep the full-frame fallback box"
            }
        )
    return _PERSON_DETECTOR


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
    from hmr2.utils.renderer import cam_crop_to_full

    image_path = request["image_path"]
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return {
            "status": "error",
            "fatal": False,
            "message": f"the frame image is unreadable: {image_path}",
        }

    height, width = img_bgr.shape[:2]
    fallback_box = [0.0, 0.0, float(width), float(height)]
    box, detector_name = _resolve_request_box(
        _get_person_detector(), img_bgr, (width, height), fallback_box
    )
    dataset = ViTDetDataset(model_cfg, img_bgr, np.array(box, dtype=np.float32).reshape(1, 4))
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
    # ``pred_cam_t`` is already the translation of the SMPL model used by the
    # renderer. Adding ``joints[0]`` would apply the pelvis offset twice and
    # produced impossible multi-metre root jumps on real clips.
    # The focal must stay fp32: ``cam_crop_to_full`` computes ``2 * focal / bs``
    # and the halved img_size here gave an fp16 focal whose doubling overflowed
    # to +inf, so every depth came back invalid (measured, M8 S7 probe).
    scaled_focal_length = (
        model_cfg.EXTRA.FOCAL_LENGTH
        / model_cfg.MODEL.IMAGE_SIZE
        * batch["img_size"].float().max()
    )
    root_translation = cam_crop_to_full(
        output["pred_cam"].float(),
        batch["box_center"].float(),
        batch["box_size"].float(),
        batch["img_size"].float(),
        scaled_focal_length,
    )[0]
    axis = int(torch.tensor([
        abs(joints[8, k].item() - joints[19:25, k].min().item()) for k in range(3)
    ]).argmax().item())
    per_frame = joints[8, axis].item() - vertices[:, axis].min().item()

    # The video overlay's projection (pose-video-overlay S1): the engine's own
    # SMPL body joints projected onto the FULL frame with the engine's own
    # camera rule -- the vendored ``perspective_projection`` (imported, never
    # patched) with the same ``cam_crop_to_full`` translation and scaled focal
    # the engine's demo uses for its full-frame overlay, and the frame centre
    # as principal point. No extra flip: the projection's axes are the image's
    # (px = f*(x+tx)/z', py = f*(y+ty)/z' + centre), so head/feet land in
    # frame as the demo renders them. A joint whose depth or pixels are not
    # finite drops out of the mapping instead of poisoning it.
    from hmr2.utils.geometry import perspective_projection

    projected = perspective_projection(
        joints[:24].float().unsqueeze(0),
        translation=root_translation.float().unsqueeze(0),
        focal_length=torch.tensor([[float(scaled_focal_length), float(scaled_focal_length)]]),
        camera_center=torch.tensor([[width / 2.0, height / 2.0]]),
    )[0]
    finite = torch.isfinite(projected).all(dim=-1)
    projected_joints = {
        name: [float(pixel[0]), float(pixel[1])]
        for name, pixel in zip(
            ("Pelvis", *SMPL_BODY_JOINT_NAMES), projected[finite].tolist(), strict=False
        )
    }

    return {
        "status": "ok",
        "frame_index": request.get("frame_index"),
        "per_frame_hip_height_m": per_frame,
        "root_translation": [float(v) for v in root_translation],
        "projected_joints": projected_joints,
        "person_bbox": [float(v) for v in box],
        "detector": detector_name,
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
