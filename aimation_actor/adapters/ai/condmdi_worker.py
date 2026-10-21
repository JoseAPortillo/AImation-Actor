"""The real CondMDI inbetweening worker: the HumanML3D-263 frontend.

Runs in the engine interpreter (``.engine/condmdi-venv`` — Python 3.10 with the
pinned torch 1.13 / CLIP stack per ``AGENTS.md``) and speaks the same line-JSON
protocol as the fake worker (``tests/fake_condmdi_worker.py``) that the
``CondMDIAdapter`` drives:

    bootstrap line (adapter -> worker):
        {"engine_root", "repo_dir", "checkpoint", "mean_path", "std_path",
         "half_precision"}
    ready line (worker -> adapter):
        {"status": "ready", ...} | {"status": "error", ...}
    request line (adapter -> worker):
        {"span_frames", "keys", "bind_offsets"}
    response line:
        {"status": "ok", "poses": [...]} | {"status": "error", ...}

``repo_dir`` is the vendored official CondMDI clone (``.engine/condmdi``); the
wire carries keys in DOMAIN form (Z-up centimetres, quats-only body joints,
pelvis height) and every engine-native conversion happens here, composing the
engine's own code (L6 — never a hand-rolled re-implementation). References
while each convention was fixed:

- features from world joints (rel-263 + the abs swap): ``extract_features``
  (``data_loaders/humanml/scripts/motion_process.py:50``) mirroring
  ``HumanML3D.motion_to_abs_data`` (``data_loaders/humanml/data/dataset.py:1253``) —
  cols 0..3 become the absolute root Y-angle and x/z; normalization uses the
  vendored ``dataset/HumanML3D_abs/Mean_abs_3d.npy`` / ``Std_abs_3d.npy``.
- skeleton retarget onto HumanML3D's standard skeleton:
  ``uniform_skeleton`` (``motion_process.py:24``) with the METRIC target
  offsets measured from the vendored reference motion ``dataset/000021.npy``
  (the engine's own ``process_file`` recipe; the raw ``t2m_raw_offsets`` are
  unit directions and must never stand in for them).
- conditioning: the unet plants ``obs_x0`` where ``obs_mask`` is true and
  concatenates the mask channel (``model/mdm_unet.py:767``); classifier-free
  guidance lives in ``model/cfg_sampler.py:25`` and both branches keep the
  keyframe condition, so ``y['text_scale']`` must always be set.
- sampling: ``diffusion.p_sample_loop`` exactly as ``sample/conditional_synthesis.py:214``
  calls it.- decoding: world positions from ``recover_from_ric(..., abs_3d=True)``
  (``motion_process.py:474``); per-joint local rotations from the ``rot_data``
  cont6d columns, whose chain convention is ``Skeleton``'s own (
  ``forward_kinematics``/``inverse_kinematics`` restart the accumulated chain
  rotation at the root quat per ``kinematic_tree`` chain — arm collars are
  local to the pelvis frame, never threaded through the spine quats). The
  wire re-expresses them as Maya parent-relative locals (only the collars
  move). Pelvis height is col 3 directly.
- the domain frame bridge is the measured M5 convention: positions go to the
  HumanML3D frame as ``(x, z, -y) / 100`` and local rotations conjugate by
  ``A = R_x(+90)`` (``A q A^-1`` per joint), the inverse of
  ``hmr2_adapter.conjugate_y_up_to_z_up``.

Determinism: ``fixseed`` before every sample, so a request line replays to the
same motion. Frame ``L = span_frames + 1`` covers both keyframe samples.
Measured on-box (T5): the real checkpoint boots in ~6 s warm (CLIP cached
after the one-off ~340 MB download) and fills the full 193-sample window in
~64 s of sampling at a ~1.8 GB VRAM peak on a 10 GB card; see
``.engine/_probe_condmdi_e2e.py``.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

# ---------------------------------------------------------------------------
# Fixed engine conventions (verified against the vendored code, see the header)
# ---------------------------------------------------------------------------

_REPO_DEFAULT = "condmdi"
_CHECKPOINT_NAME = "model000750000.pt"
_MEAN_NAME = "Mean_abs_3d.npy"
_STD_NAME = "Std_abs_3d.npy"
_MOTION_FPS = 20.0
_MAX_SAMPLES = 196  # the trained window the ready line reports

#: The 22 observed joints: SMPL 0..21 in canonical order — HumanML3D's kintree.
#: The rig's ``L_Hand``/``R_Hand`` tips are SMPL 22/23 and drop out; the wire
#: pose maps are name subsets, so the response simply omits them.
_OBSERVED_JOINTS = (
    "Pelvis",
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
)

#: The engine's kinematic chains in this rig's names. The accumulated chain
#: rotation RESTARTS at the root quat for every chain (``skeleton.py``'s
#: ``forward_kinematics``/``inverse_kinematics`` loops re-seed ``R`` per
#: ``self._kinematic_tree``), so the arm chains — which leave ``Spine_3`` —
#: carry collars that are local to the pelvis-accumulated frame and never
#: thread through the spine quats. Verified on the engine's own FK by the
#: probe P3 and pinned by ``tests/test_ai_condmdi_worker_wire.py``.
_MOTION_CHAINS = (
    ("R_Hip", "R_Knee", "R_Ankle", "R_Foot"),
    ("L_Hip", "L_Knee", "L_Ankle", "L_Foot"),
    ("Spine_1", "Spine_2", "Spine_3", "Neck", "Head"),
    ("L_Collar", "L_Shoulder", "L_Elbow", "L_Wrist"),
    ("R_Collar", "R_Shoulder", "R_Elbow", "R_Wrist"),
)

#: SMPL's kintree parents for the observed joints ("Pelvis" hangs under the
#: ground root ``Main``, which only fixes the ground origin).
_JOINT_PARENTS = {
    "Pelvis": "Main",
    "L_Hip": "Pelvis",
    "R_Hip": "Pelvis",
    "Spine_1": "Pelvis",
    "L_Knee": "L_Hip",
    "R_Knee": "R_Hip",
    "Spine_2": "Spine_1",
    "L_Ankle": "L_Knee",
    "R_Ankle": "R_Knee",
    "Spine_3": "Spine_2",
    "L_Foot": "L_Ankle",
    "R_Foot": "R_Ankle",
    "Neck": "Spine_3",
    "L_Collar": "Spine_3",
    "R_Collar": "Spine_3",
    "Head": "Neck",
    "L_Shoulder": "L_Collar",
    "R_Shoulder": "R_Collar",
    "L_Elbow": "L_Shoulder",
    "R_Elbow": "R_Shoulder",
    "L_Wrist": "L_Elbow",
    "R_Wrist": "R_Elbow",
}

_FEET_THRESH = 0.002  # extract_features' default (metres)
_FACE_JOINTS = (2, 1, 17, 16)  # r_hip, l_hip, sdr_r, sdr_l
_FID_RIGHT = (8, 11)
_FID_LEFT = (7, 10)
#: columns 4..66: root-relative joint positions; 67..192: cont6d local chain
#: rotations; 193..258: local velocities; 259..262: foot contacts
#: (``motion_process.py:396`` documents the layout).
_RIC_START = 4
_ROT_START = 67
_ROT_END = 193
_SEED = 10

# ---------------------------------------------------------------------------
# Small self-contained rotation math: the ``(w, x, y, z)`` Hamilton layout the
# domain's ``Quaternion`` uses (and the engine's quaternion.py too).
# ---------------------------------------------------------------------------


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _fail(message: str, *, fatal: bool = True) -> None:
    _emit({"status": "error", "message": message, "fatal": fatal})


def _quat_mul(left, right):
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _quat_inverse(quat):
    w, x, y, z = quat
    return (w, -x, -y, -z)


def _quat_from_matrix(m00, m01, m02, m10, m11, m12, m20, m21, m22):
    """Row-major 3x3 rotation matrix -> unit quaternion ``(w, x, y, z)``."""
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return (0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return ((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s)


def _quat_normalize(quat):
    w, x, y, z = quat
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / norm, x / norm, y / norm, z / norm)


def _quat_rotate(quat, vec):
    w, x, y, z = quat
    vx, vy, vz = vec
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + y * tz - z * ty,
        vy + w * ty + z * tx - x * tz,
        vz + w * tz + x * ty - y * tx,
    )


#: ``A`` re-expresses a HumanML3D (Y-up) rotation in the domain (Z-up) frame:
#: ``q_domain = A q_hml A^-1``, distributing over chain products so the same
#: conjugation maps body locals too. The inverse reading of the FBX writer's
#: ``A = R_x(-90)``; mirrors ``hmr2_adapter.conjugate_y_up_to_z_up``.
_A_CONJ = (math.cos(math.pi / 4.0), math.sin(math.pi / 4.0), 0.0, 0.0)


def _hml_rotation_to_domain(quat):
    return _quat_mul(
        _A_CONJ, _quat_mul(quat, (_A_CONJ[0], -_A_CONJ[1], -_A_CONJ[2], -_A_CONJ[3]))
    )


def _hml_local_rotation_from_domain(quat):
    inv_a = (_A_CONJ[0], -_A_CONJ[1], -_A_CONJ[2], -_A_CONJ[3])
    return _quat_mul(inv_a, _quat_mul(quat, _A_CONJ))


def _domain_to_hml_offset(vec):
    """Domain (Z-up cm) parent-relative offset -> HumanML3D (Y-up m)."""
    x, y, z = vec
    return (x * 0.01, z * 0.01, -y * 0.01)


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


class _EngineError(Exception):
    """A bootstrap-time engine problem: reported as a fatal ready error."""


class _RequestError(Exception):
    """A per-request problem: reported as a non-fatal error line."""


class _CondMDIEngine:
    def __init__(self) -> None:
        self.np = None
        self.torch = None
        self.model = None
        self.diffusion = None
        self.device = None
        self.cpu_device = None
        self.motion_process = None
        self.editing_util = None
        self.n_raw_offsets = None
        self.tgt_offsets = None
        self.kinematic_chain = None
        self.mean = None
        self.std = None
        self.guidance = 2.5

    # -- bootstrap ---------------------------------------------------------- #

    def bootstrap(self, boot: dict) -> None:
        engine_root = Path(boot.get("engine_root") or ".engine")
        repo_dir = Path(boot.get("repo_dir") or engine_root / _REPO_DEFAULT)
        checkpoint = Path(
            boot.get("checkpoint") or engine_root / "condmdi_random_joints" / _CHECKPOINT_NAME
        )
        mean_path = Path(
            boot.get("mean_path") or repo_dir / "dataset" / "HumanML3D_abs" / _MEAN_NAME
        )
        std_path = Path(
            boot.get("std_path") or repo_dir / "dataset" / "HumanML3D_abs" / _STD_NAME
        )
        if not repo_dir.is_dir():
            raise _EngineError(f"the vendored CondMDI repo was not found at {repo_dir}")
        if not checkpoint.is_file():
            raise _EngineError(
                f"the CondMDI checkpoint was not found at {checkpoint}; it is "
                "user-supplied and never vendored (see AGENTS.md)"
            )
        if not mean_path.is_file():
            raise _EngineError(f"the HumanML3D mean file was not found at {mean_path}")
        if not std_path.is_file():
            raise _EngineError(f"the HumanML3D std file was not found at {std_path}")
        args_path = checkpoint.parent / "args.json"
        if not args_path.is_file():
            raise _EngineError(f"the checkpoint's args.json was not found at {args_path}")

        os.chdir(repo_dir)  # the engine's config treats cwd-relative paths
        sys.path.insert(0, str(repo_dir))

        self.np = __import__("numpy")
        self.torch = __import__("torch")
        self._stub_unused_smpl_backend()

        from data_loaders.humanml.scripts import motion_process
        from data_loaders.humanml.utils import paramUtil
        from utils.editing_util import joint_to_full_mask
        from utils.model_util import create_model_and_diffusion, load_saved_model

        self.motion_process = motion_process
        self._joint_to_full_mask = joint_to_full_mask

        saved = json.loads(args_path.read_text(encoding="utf-8"))
        args = SimpleNamespace(**saved)
        self.guidance = float(getattr(args, "guidance_param", 2.5))
        self.n_raw_offsets = self.torch.from_numpy(paramUtil.t2m_raw_offsets)
        self.kinematic_chain = paramUtil.t2m_kinematic_chain
        # The retarget's target offsets must be METRIC canonical skeleton
        # lengths, measured from the vendored reference motion exactly as the
        # engine's own ``process_file`` does. ``paramUtil.t2m_raw_offsets``
        # are unit direction vectors (legs measure 2.0), not lengths — passing
        # them as the target inflated every retargeted motion ~2.5x and pushed
        # the conditioning out of the model's training distribution.
        reference_path = repo_dir / "dataset" / "000021.npy"
        if not reference_path.is_file():
            raise _EngineError(
                f"the canonical reference motion was not found at {reference_path}; "
                "it measures the retarget's target skeleton (the vendored repo carries it)"
            )
        reference = self.np.load(str(reference_path))
        from data_loaders.humanml.common.skeleton import Skeleton
        tgt_skeleton = Skeleton(self.n_raw_offsets, self.kinematic_chain, "cpu")
        self.tgt_offsets = tgt_skeleton.get_offsets_joints(self.torch.from_numpy(reference[0]))
        self.cpu_device = self.torch.device("cpu")
        if not self.torch.cuda.is_available():
            raise _EngineError(
                "the CondMDI engine needs a CUDA device; no usable GPU was found"
            )
        self.device = self.torch.device("cuda:0")

        fake_data = SimpleNamespace(dataset=SimpleNamespace(num_actions=1))
        self.model, self.diffusion = create_model_and_diffusion(args, fake_data)
        load_saved_model(self.model, str(checkpoint))
        # The official inference pipeline (sample/conditional_synthesis.py,
        # eval/eval_humanml_condmdi.py) never converts to fp16 — both run the
        # loaded weights as they come. ``half_precision`` stays a boot field
        # for wire compatibility only.
        self.model.to(self.device)
        self.model.eval()

        self.mean = self.np.asarray(self.np.load(str(mean_path)), dtype=self.np.float32)
        self.std = self.np.asarray(self.np.load(str(std_path)), dtype=self.np.float32)
        if self.mean.shape[-1] != 263 or self.std.shape[-1] != 263:
            raise _EngineError(
                "the HumanML3D abs mean/std payloads must each carry 263 features "
                f"(got mean {self.mean.shape}, std {self.std.shape})"
            )

    def _stub_unused_smpl_backend(self) -> None:
        """Bypass the SMPL body-model backend the sampling path never reaches.

        ``Rotation2xyz.__init__`` (``model/rotation2xyz.py:15``) instantiates
        the SMPL layer, dragging in ``smplx`` plus the non-redistributable SMPL
        files; ``MDM_UNET`` builds it only for its own ``rot2xyz`` surface,
        which the 263 feature path never touches. This stub keeps every
        engine code path we use live and only replaces that unused component.
        """
        stub = ModuleType("model.rotation2xyz")
        stub.JOINTSTYPES = ["smpl"]

        class _NoopSmplModel:
            """A device/training shell for the stubbed SMPL layer.

            ``MDM_UNET._apply`` (``mdm_unet.py:853``) and ``.train``
            (``mdm_unet.py:857``) always delegate to
            ``self.rot2xyz.smpl_model`` — the no-op keeps those live engine
            paths working without the SMPL payload.
            """

            def _apply(self, fn):
                return self

            def train(self, mode=True):
                return self

        class _StubRotation2xyz:
            def __init__(self, device, dataset="amass"):
                self.device = device
                self.dataset = dataset
                self.smpl_model = _NoopSmplModel()

        stub.Rotation2xyz = _StubRotation2xyz
        sys.modules["model.rotation2xyz"] = stub

    # -- ready -------------------------------------------------------------- #

    def ready(self) -> dict:
        gpu = self.torch.cuda.get_device_name(0)
        vram_total_mib = int(
            self.torch.cuda.get_device_properties(0).total_memory / 1024 / 1024
        )
        return {
            "status": "ready",
            "gpu": gpu,
            "vram_total_mib": vram_total_mib,
            "motion_fps": _MOTION_FPS,
            "max_frames": _MAX_SAMPLES,
        }

    # -- the request flow --------------------------------------------------- #

    def fill(self, request: dict) -> dict:
        """One gap-fill request: dense domain poses for the whole span."""
        span = int(request.get("span_frames") or 0)
        keys = request.get("keys") or []
        if span < 1 or len(keys) != 2:
            raise _RequestError("a gap fill needs span_frames and exactly two keys")
        length = span + 1
        if length > _MAX_SAMPLES:
            raise _RequestError(
                f"the requested span needs {length} motion samples, beyond the "
                f"model window of {_MAX_SAMPLES}"
            )
        rig = self._rig(request)

        # 1. the two keyframe keyframes' FK positions in HumanML3D frame
        key_positions = [self._fk_positions_hml(rig, key["pose"]) for key in keys]
        key_samples = [int(key.get("sample") or 0) for key in keys]
        for index, sample in enumerate(key_samples):
            if not 0 <= sample < length:
                raise _RequestError(f"key {index} sample {sample} outside 0..{length - 1}")
        if key_samples[0] != 0 or key_samples[1] != span:
            raise _RequestError(
                "the gap fill expects the keys at samples 0 and span_frames; "
                f"got {key_samples}"
            )

        # 2. the dense prior: keys exact, the span a straight world-space lerp
        #    (velocities/contacts columns derived from it stay self-consistent)
        dense = self.np.zeros((length, 22, 3), dtype=self.np.float32)
        for sample in range(length):
            alpha = sample / span
            dense[sample] = (
                key_positions[0] * (1.0 - alpha) + key_positions[1] * alpha
            )

        # 3. retarget to HumanML3D's standard skeleton, then featurize.
        #    The target offsets are the METRIC lengths measured from the
        #    vendored reference motion (see ``bootstrap``); the template arg
        #    stays the raw unit directions the engine's own code expects.
        retargeted = self.motion_process.uniform_skeleton(
            dense,
            self.tgt_offsets,
            self.n_raw_offsets,
            self.kinematic_chain,
        )

        # 3b. Canonicalize the facing: the engine's abs-3d convention carries
        #     the root angle RELATIVE TO THE SAMPLE'S FIRST FRAME, so the
        #     condition must start facing +Z or the decode loses the keys'
        #     absolute facing (the pelvis quat would come out relative and the
        #     body would thread on a rotated chain frame). Rotate the retargeted
        #     motion about the root's vertical axis, and remember the yaw so
        #     every wire pose rotates back into the user's world.
        canonical_yaw = self._canonical_yaw(retargeted[0])
        if abs(canonical_yaw) > 1e-9:
            retargeted = self._yaw_rotate_dense(retargeted, -canonical_yaw)
        features = self._featurize_abs(retargeted)

        # 4. the observation: every joint, only the keyframe samples. The
        #    engine's own full-feature expansion (``pos_rot_vel``, the same
        #    default the training loop masks with) — anything else leaves part
        #    of the keyframe features as noise the model never saw in training.
        #    Normalization runs per feature BEFORE shaping: the tensor is
        #    feature-major [263, L], so torch broadcasting on the trailing
        #    axis would smear the mean/std across the wrong axis.
        norm_rows = ((features.T - self.mean) / self.std).T
        obs_x0 = self.torch.from_numpy(
            self.np.ascontiguousarray(norm_rows, dtype=self.np.float32)
        ).unsqueeze(0).unsqueeze(2).float()
        if not self.torch.isfinite(obs_x0).all():
            raise _RequestError("featurizing the keys produced non-finite features")
        obs_x0 = obs_x0.to(self.device)

        joint_mask = self.torch.zeros((1, 22, 1, length), dtype=self.torch.bool)
        for sample in key_samples:
            joint_mask[0, :, :, sample] = True
        obs_mask = self._joint_to_full_mask(joint_mask, mode="pos_rot_vel")
        obs_mask = obs_mask.to(self.device)

        # 5. sample exactly like sample/conditional_synthesis.py does
        from model.cfg_sampler import ClassifierFreeSampleModel
        from utils.fixseed import fixseed

        fixseed(_SEED)
        wrapped = ClassifierFreeSampleModel(self.model)
        model_kwargs = {
            "y": {
                "lengths": self.torch.tensor([length], device=self.device),
                "mask": self.torch.ones((1, 1, 1, length), device=self.device),
                "text": [""],
                "text_scale": self.torch.tensor(
                    [self.guidance], device=self.device
                ),
            },
            "obs_x0": obs_x0,
            "obs_mask": obs_mask,
        }
        self.torch.cuda.empty_cache()
        self.torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        sample = self.diffusion.p_sample_loop(
            wrapped,
            (1, self.model.njoints, self.model.nfeats, length),
            clip_denoised=False,
            progress=False,
            model_kwargs=model_kwargs,
            skip_timesteps=0,
            init_image=None,
            dump_steps=None,
            noise=None,
            const_noise=False,
        )
        latency_s = time.perf_counter() - started
        peak_mib = int(self.torch.cuda.max_memory_allocated() / 1024 / 1024)

        # 6. decode: normalized 263 -> absolute features -> world positions
        #    (recover_from_ric, abs_3d) and per-joint locals from rot_data
        sample = sample.cpu().permute(0, 2, 3, 1).float()
        sample = sample * self.torch.from_numpy(self.std) + self.torch.from_numpy(self.mean)
        positions = self.motion_process.recover_from_ric(sample, 22, abs_3d=True)
        positions = positions.view(length, 22, 3).cpu().numpy().astype(self.np.float32)
        root_quats, root_positions = self.motion_process.recover_root_rot_pos(
            sample, abs_3d=True
        )
        root_quats = root_quats.view(length, 4).cpu().numpy()
        root_positions = root_positions.view(length, 3).cpu().numpy()
        locals_ = self._decode_locals(sample)

        poses = []
        for frame_index in range(length):
            pose = self._frame_to_wire(
                rig,
                tuple(float(v) for v in root_quats[frame_index]),
                float(root_positions[frame_index, 1]),
                locals_[frame_index],
            )
            # The sample decodes in the canonical frame (facing +Z at sample
            # 0); rotate the pelvis back into the user's world. Body locals
            # are parent-relative and need no change: rotating the root
            # propagates through the Maya threading unchanged.
            if abs(canonical_yaw) > 1e-9:
                back = (math.cos(canonical_yaw * 0.5), 0.0, math.sin(canonical_yaw * 0.5), 0.0)
                wire_pelvis = pose["Pelvis"]["quat"]
                pose["Pelvis"]["quat"] = list(
                    _hml_rotation_to_domain(
                        _quat_mul(
                            back,
                            _hml_local_rotation_from_domain(
                                tuple(float(v) for v in wire_pelvis)
                            ),
                        )
                    )
                )
            poses.append({"frame": frame_index, "pose": pose})

        return {
            "poses": poses,
            "measure": {"latency_s": round(latency_s, 3), "vram_peak_mib": peak_mib},
        }

    # -- conversion helpers -------------------------------------------------- #

    def _rig(self, request: dict) -> dict:
        """The rig's bind offsets in the HumanML3D frame, validated per joint."""
        raw = request.get("bind_offsets") or {}
        offsets = {}
        missing = []
        for name in _OBSERVED_JOINTS:
            offset = raw.get(name)
            if offset is None:
                missing.append(name)
                continue
            offsets[name] = _domain_to_hml_offset(
                (float(offset[0]), float(offset[1]), float(offset[2]))
            )
        if missing:
            raise _RequestError(
                f"the request's bind_offsets are missing for: {', '.join(missing)}"
            )
        pelvis_rest = offsets["Pelvis"][1]
        return {"offsets": offsets, "pelvis_rest": pelvis_rest}

    def _fk_positions_hml(self, rig, pose) -> dict[str, dict]:
        """One keyframe's rig FK pass.

        Returns the 22 observed joints' world positions in the HumanML3D
        frame. Body rotations arrive as domain locals and conjugate back to
        the Y-up frame; the pelvis ``trans.z`` is the height offset from its
        bind, so the absolute height is ``rest.y + trans.z``.
        """
        entries = pose or {}
        missing = [name for name in _OBSERVED_JOINTS if name not in entries]
        if missing:
            raise _RequestError(
                f"the request pose is missing joints: {', '.join(missing)}"
            )
        pelvis = entries["Pelvis"]
        trans = pelvis.get("trans")
        if trans is None:
            raise _RequestError("the request pose carries no Pelvis height")
        hip_height = rig["offsets"]["Pelvis"][1] + float(trans[2]) * 0.01
        pelvis_quat = _hml_local_rotation_from_domain(
            _quat_normalize(tuple(float(v) for v in (pelvis.get("quat") or (1, 0, 0, 0))))
        )

        locals_hml = {}
        for name in _OBSERVED_JOINTS:
            if name == "Pelvis":
                locals_hml[name] = pelvis_quat
                continue
            raw = entries[name].get("quat") or (1.0, 0.0, 0.0, 0.0)
            locals_hml[name] = _hml_local_rotation_from_domain(
                _quat_normalize(tuple(float(v) for v in raw))
            )

        positions = {"Main": (0.0, 0.0, 0.0), "Pelvis": (0.0, hip_height, 0.0)}
        quats = {"Main": (1.0, 0.0, 0.0, 0.0), "Pelvis": pelvis_quat}
        for name in _OBSERVED_JOINTS[1:]:
            parent = _JOINT_PARENTS[name]
            parent_quat = quats[parent]
            parent_pos = positions[parent]
            offset = rig["offsets"][name]
            rotated = _quat_rotate(parent_quat, offset)
            positions[name] = (
                parent_pos[0] + rotated[0],
                parent_pos[1] + rotated[1],
                parent_pos[2] + rotated[2],
            )
            quats[name] = _quat_mul(parent_quat, locals_hml[name])
        return self.np.asarray(
            [positions[name] for name in _OBSERVED_JOINTS], dtype=self.np.float32
        )

    def _canonical_yaw(self, frame) -> float:
        """One frame's facing angle, the engine's own across-vector convention,
        as a signed yaw in radians.

        ``extract_features`` derives the root facing from
        ``p[r_hip] - p[l_hip] + p[sdr_r] - p[sdr_l]`` (``face_joint_indx``)
        crossed with Y; the signed yaw of that forward vector is what a
        ``-yaw`` rotation about the vertical aligns to +Z — the sample-start
        convention the abs-3d encode/decode pair assumes.
        """
        r_hip, l_hip, sdr_r, sdr_l = _FACE_JOINTS
        across = (
            frame[r_hip] - frame[l_hip] + frame[sdr_r] - frame[sdr_l]
        )
        norm = float(self.np.linalg.norm(across))
        if norm < 1e-9:
            return 0.0
        forward = self.np.cross(
            self.np.asarray([0.0, 1.0, 0.0]), across / norm
        )
        norm = float(self.np.linalg.norm(forward))
        if norm < 1e-9:
            return 0.0
        forward = forward / norm
        return math.atan2(float(forward[0]), float(forward[2]))

    def _yaw_rotate_dense(self, positions, yaw):
        """Rotate a motion's world joints about each frame's root vertical
        axis by ``yaw`` radians. The root sits on the axis and stays put; the
        facing turns by ``yaw`` (+yaw maps facing angle ``a`` to ``a + yaw``).
        A zero-yaw call returns the input array unchanged by identity of the
        math, so callers may always rotate.
        """
        root = positions[:, 0:1, :]
        rotated = positions - root
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        rotated_x = rotated[..., 0] * cos_y + rotated[..., 2] * sin_y
        rotated_z = -rotated[..., 0] * sin_y + rotated[..., 2] * cos_y
        rotated[..., 0] = rotated_x
        rotated[..., 2] = rotated_z
        return rotated + root

    def _featurize_abs(self, dense) -> object:
        """Dense world joints -> normalized absolute 263 per frame.

        Mirrors ``HumanML3D.motion_to_abs_data`` (``dataset.py:1253``):
        ``extract_features`` builds the relative rep, the last row duplicates
        to restore one feature row per frame, and the first four columns swap
        in the absolute root rot/pos. Returns ``numpy [263, L]``.
        """
        np = self.np
        # ``extract_features`` mutates its input in place (``get_rifke``'s
        # ``positions[..., {0, 2}] -= ...``, motion_process.py:91-92), and the
        # vendored code is never patched (M6 L6) — the caller's dense
        # positions survive featurization only through this copy.
        extract = self.motion_process.extract_features(
            dense.copy(),
            _FEET_THRESH,
            self.n_raw_offsets,
            self.kinematic_chain,
            list(_FACE_JOINTS),
            list(_FID_RIGHT),
            list(_FID_LEFT),
        )
        rel = np.concatenate([extract, extract[-1:, :]], axis=0)  # [L, 263]
        rel_t = self.torch.from_numpy(rel).unsqueeze(0).float()
        _, root_pos, rot_ang = self.motion_process.recover_root_rot_pos(
            rel_t, abs_3d=False, return_rot_ang=True
        )
        abs_features = rel_t.clone()
        abs_features[..., 0] = rot_ang
        abs_features[..., [1, 2]] = root_pos[..., [0, 2]]
        return abs_features[0].permute(1, 0).float().cpu().numpy()

    def _decode_locals(self, sample_abs) -> list[list[tuple]]:
        """Per-frame chain locals from the ``rot_data`` columns.

        The columns are ``Skeleton``'s per-chain rotations, local to the
        chain's accumulated frame with a ROOT restart per ``kinematic_tree``
        chain (so arm collars are local to the pelvis frame, not to their
        Maya parent). ``_frame_to_wire`` re-expresses them as Maya
        parent-relative locals.
        Returns, per frame, the 21 body quats ``(w, x, y, z)`` in the
        HumanML3D frame.
        """
        dims = sample_abs[..., _ROT_START:_ROT_END].view(-1, 21, 6).cpu().numpy()
        # ``quaternion_to_cont6d_np`` stores the rotation matrix's columns 0
        # and 1 contiguously per joint (quaternion.py:308-311); the matrix
        # rows interleave the two axes, so the basis vectors enter as matrix
        # columns for ``_quat_from_matrix`` below.
        frames = []
        for index in range(dims.shape[0]):
            frame = dims[index].reshape(21, 6)
            locals_frame = []
            for joint in frame:
                xx, xy, xz, yx, yy, yz = (float(v) for v in joint)
                x_axis = (xx, xy, xz)
                y_axis = (yx, yy, yz)
                z_axis = (
                    x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
                    x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
                    x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
                )
                quaternions = _quat_from_matrix(
                    x_axis[0], y_axis[0], z_axis[0],
                    x_axis[1], y_axis[1], z_axis[1],
                    x_axis[2], y_axis[2], z_axis[2],
                )
                locals_frame.append(_quat_normalize(quaternions))
            frames.append(locals_frame)
        return frames

    def _frame_to_wire(self, rig, root_quat, hip_height, frame_locals) -> dict:
        """One frame's decoded state -> the response's domain pose subset.

        ``root_quat`` and ``hip_height`` come straight from the engine's own
        ``recover_root_rot_pos(abs_3d=True)`` output; ``frame_locals`` carries
        the 21 body locals in the engine's chain convention. The body values
        re-express as Maya-style parent-relative locals (the chain restart
        divides every joint by its Maya parent's accumulation — only the L/R
        collars change) and conjugate into the domain frame; the pelvis writes
        the height offset from its bind.
        """
        locals_by_name = dict(zip(_OBSERVED_JOINTS[1:], frame_locals, strict=True))
        base = _quat_normalize(tuple(float(v) for v in root_quat))
        # The engine's accumulated chain rotations, root-restart per chain.
        accs = {"Pelvis": base}
        for chain in _MOTION_CHAINS:
            running = base
            for name in chain:
                running = _quat_mul(running, locals_by_name[name])
                accs[name] = running
        pose = {}
        main_entry = {"quat": [1.0, 0.0, 0.0, 0.0], "trans": [0.0, 0.0, 0.0]}
        pose["Pelvis"] = {
            "quat": list(_hml_rotation_to_domain(base)),
            "trans": [0.0, 0.0, hip_height * 100.0 - rig["offsets"]["Pelvis"][1] * 100.0],
        }
        # Main belongs to the wire's pose map as the ground root it is; the
        # rig cannot rotate it and this worker never writes it (proven by the
        # capture tests guided by S1).
        pose["Main"] = main_entry
        for name in _OBSERVED_JOINTS[1:]:
            # Maya threading: parent-relative = own accumulation / parent's.
            local = _quat_mul(_quat_inverse(accs[_JOINT_PARENTS[name]]), accs[name])
            quat = _hml_rotation_to_domain(local)
            pose[name] = {"quat": list(quat), "trans": None}
        return pose


def main() -> None:
    bootstrap = json.loads(sys.stdin.readline())
    engine = _CondMDIEngine()
    try:
        engine.bootstrap(bootstrap)
    except Exception as error:  # noqa: BLE001 - the protocol is the only surface
        _emit({"status": "error", "message": str(error), "fatal": True})
        return
    try:
        ready = engine.ready()
    except Exception as error:  # noqa: BLE001
        _emit({"status": "error", "message": str(error), "fatal": True})
        return
    _emit(ready)

    for line in sys.stdin:
        request = json.loads(line)
        try:
            response = engine.fill(request)
        except _RequestError as error:
            _emit({"status": "error", "message": str(error), "fatal": False})
            continue
        except Exception as error:  # noqa: BLE001
            engine.torch.cuda.empty_cache()
            _emit({"status": "error", "message": str(error), "fatal": False})
            continue
        _emit({"status": "ok", **response})


if __name__ == "__main__":
    main()
