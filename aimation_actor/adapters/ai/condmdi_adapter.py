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
- request (adapter -> worker): {"span_frames", "keys", "bind_offsets",
  "guide_frames"?} — keys in **domain** form (quaternions + pelvis height);
  ``guide_frames`` (S6) carries captured anchors between the keys in the
  same domain form at engine-sample indices; the engine-native
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

import os
import sys
from collections.abc import Mapping, Set
from pathlib import Path

from aimation_actor.adapters.ai.engine_bridge import EngineWorkerBridge
from aimation_actor.core.models import JointPose, Quaternion, TimelineState, Vector3
from aimation_actor.core.resampling import fill_gap_synthetically, resample_dense_poses
from aimation_actor.core.services import key_frames
from aimation_actor.ports.ai_port import InbetweeningPort

__all__ = ["CondMDIAdapter", "CondMDIEngineError"]

_READY_TIMEOUT_S = 300.0  # the checkpoint + CLIP load takes minutes (T5 measures)
_REQUEST_TIMEOUT_S = 600.0  # diffusion sampling per gap: budgeted, T5 measures

#: The engine-side worker module, run by the engine's own interpreter.
_WORKER_MODULE = Path(__file__).resolve().parent / "condmdi_worker.py"

_CHECKPOINT_DEFAULT = "model000750000.pt"  # the official keyframe-conditioned save
_MOTION_FPS = 20.0  # HumanML3D's clock (the ready line re-states it)
_MAX_SAMPLES_DEFAULT = 196  # ~9.8 s at 20 fps; the model's trained window
# M9 (S4): an engine-filled gap whose request carries capture data between
# the keys seeds the diffusion with its own dense capture prior and starts
# this many timesteps down the vendored chain (1000 total, no respacing).
# Measured default (T3 probe, `_e2e_wide_gap_prior.py`, keys 40/87 of
# JACE_REF_04, guides {58, 76}): the sweep 0/300/500/700/850 showed the
# interior content is nearly skip-INSENSITIVE (arm columns within ~1.5 deg,
# facing positive share constant 85.1%), because the per-step observation
# replant dominates the free rows — the L23 "model's free-joint content"
# verdict reconfirmed at the init level. What the prior/skip DOES change
# is cost: 70.6 -> 44.2 -> 31.6 -> 19.0 -> 9.6 s per fill. 500 is the
# halfway-noise start: the largest latency saving (2.2x) among values whose
# output stayed stat-noise-close to the unskipped baseline. Unguided gaps
# keep free generation. Quality tuning of the free rows is the "afinar"
# phase (see spec.md: anchor-vs-fill seam is the next visible defect).
_CAPTURE_PRIOR_SKIP_TIMESTEPS = 500


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


def _guides_for_gap(
    guides: Mapping[int, Mapping[str, JointPose]],
    left: int,
    right: int,
    timeline_fps: float,
    motion_fps: float,
    keyed: Set[int] | None,
) -> tuple[list[dict], dict[int, Mapping[str, JointPose]]]:
    """One gap's guides as the request payload plus its timeline anchors.

    A guide survives only strictly inside the gap, never on a keyed frame,
    and never when its motion-clock sample rounds onto the keyed endpoints
    (``0``/``span``) — that guide is dropped for this gap instead of
    poisoning the request, because the worker refuses sample collisions
    (T6). The payload is sample-sorted; the anchors keep the timeline frame
    so ``fill_gap_synthetically`` can reassert the capture byte-exact.
    """
    span = _samples_between(left, right, timeline_fps, motion_fps)
    keyed = frozenset(keyed) if keyed else frozenset()
    payload: list[dict] = []
    anchors: dict[int, Mapping[str, JointPose]] = {}
    for frame in sorted(guides):
        if not left < frame < right:
            continue
        if frame in keyed:
            continue
        sample = _samples_between(left, frame, timeline_fps, motion_fps)
        if not 0 < sample < span:
            continue
        payload.append({"sample": sample, "pose": _pose_to_wire(guides[frame])})
        anchors[frame] = guides[frame]
    return payload, anchors


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
        self._bridge = EngineWorkerBridge(
            python_executable=self.python_executable,
            worker_script=self.worker_script,
            env=self._env,
            ready_timeout_s=_READY_TIMEOUT_S,
            request_timeout_s=_REQUEST_TIMEOUT_S,
            engine_label="CondMDI",
            activity="fill",
            checkpoint=self.checkpoint,
            error=CondMDIEngineError,
        )

    # -- lifecycle ------------------------------------------------------------- #

    def shutdown(self) -> None:
        """Terminate the engine worker; idempotent (safe at app close)."""
        self._bridge.shutdown()

    # -- InbetweeningPort ------------------------------------------------------- #

    def inbetween(
        self, timeline: TimelineState, guides: Mapping[int, Mapping[str, JointPose]] | None = None
    ) -> TimelineState:
        """Fill every gap between consecutive keys; keys stay byte-identical.

        ``guides`` (S6, optional) maps a timeline frame to its captured pose:
        guides inside each gap enter the engine request as extra observation
        rows (the capture's dynamics between the keys) and are reasserted
        byte-exact at their frames by ``fill_gap_synthetically``. When the
        guides cover every interior frame of a gap (T9), the capture IS that
        gap's fill: no engine request is made for it, and a timeline whose
        gaps are all covered never spawns the engine at all.
        """
        frames = key_frames(timeline)
        if len(frames) < 2:
            raise ValueError(
                "inbetweening needs at least two keys: a timeline with fewer "
                "keys has no gap to fill (S1: nothing outside the keys)"
            )

        filled = timeline
        motion_fps: float | None = None
        max_samples: int | None = None
        for left, right in zip(frames, frames[1:], strict=False):
            guides_map = guides or {}
            interior = range(left + 1, right)
            if all(frame in guides_map for frame in interior):
                # T9: the capture covers the whole interior - the inbetween IS
                # the capture, reasserted byte-exact frame by frame. No engine
                # request for this gap (vacuously true for adjacent keys).
                anchors = {frame: guides_map[frame] for frame in interior}
                filled = fill_gap_synthetically(filled, left, right, anchors, anchors=anchors)
                continue
            if motion_fps is None:
                # The first gap that actually needs the engine spawns it:
                # nothing generation-wise is set up for capture-only fills.
                # An oversized window is a caller-visible configuration fact,
                # not an engine event, and is still refused before spawning.
                self._refuse_oversized_gaps(
                    frames, timeline, motion_fps=_MOTION_FPS, max_samples=_MAX_SAMPLES_DEFAULT
                )
                ready = self._bridge.ensure_ready(self._validate, self._bootstrap)
                motion_fps = float(ready.get("motion_fps") or _MOTION_FPS)
                max_samples = int(ready.get("max_frames") or _MAX_SAMPLES_DEFAULT)
                self._refuse_oversized_gaps(
                    frames, timeline, motion_fps=motion_fps, max_samples=max_samples
                )
            assert motion_fps is not None and max_samples is not None
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
            guide_payload, guide_anchors = _guides_for_gap(
                guides or {}, left, right, timeline.fps, motion_fps,
                keyed={keyframe.frame for keyframe in timeline.keyframes},
            )
            request = {
                "span_frames": span,
                "keys": keys_payload,
                "bind_offsets": bind_offsets,
                "guide_frames": guide_payload,
            }
            if guide_payload:
                # M9 S4: capture data inside this gap — the worker seeds the
                # diffusion with the request's own dense prior and starts part
                # of the way down the chain. A gap with no guides inside keeps
                # free generation (a bare keys-lerp prior risks trading the
                # splay for a static glide).
                request["skip_timesteps"] = _CAPTURE_PRIOR_SKIP_TIMESTEPS
            response = self._bridge.request(request)
            if response.get("status") != "ok":
                message = str(response.get("message", "the engine request failed"))
                if response.get("fatal"):
                    self._bridge.discard()
                raise CondMDIEngineError(
                    f"the CondMDI engine failed to fill the gap {left}..{right}: {message}"
                )
            dense = self._dense_motion(response)
            generated = resample_dense_poses(
                dense, motion_fps, timeline.fps, frame_start=left
            )
            filled = fill_gap_synthetically(
                filled, left, right, generated, anchors=guide_anchors or None
            )
        return filled

    # -- the bridge (R4: the subprocess mechanics live in engine_bridge) -------- #

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

    def _bootstrap(self) -> dict:
        """The adapter -> worker launch payload (the wire contract, M6)."""
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
        return bootstrap
