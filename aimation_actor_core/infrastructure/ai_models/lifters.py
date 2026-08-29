"""3D lifting backends for the pose-3d node (REQ-2).

Backends convert a list of :class:`Keypoints2D` frames into a list of
:class:`Keypoints3D` frames. The default ``SyntheticLiftingBackend`` is
deterministic (CI truth); ``HeuristicLiftingBackend`` adds anthropometric
depth; ``OnnxLiftingBackend`` is a lazy placeholder seam for a future trained
model. ``depth_mode`` values multiply the depth deviation; unknown values
degrade to the default (spec REQ-2/REQ-3).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Protocol, runtime_checkable

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.keypoints3d import Keypoint3D, Keypoints3D

#: Depth-deviation multiplier per ``depth_mode``. ``proportional`` is the
#: default; ``flat`` collapses every joint onto the camera plane.
DEPTH_MODES: dict[str, float] = {"proportional": 1.0, "flat": 0.0}

#: z values around the camera plane (0.5) per COCO label — documented table:
#: torso/head joints sit on the camera plane (0.5); wrists/ankles deviate to
#: 0.55-0.65 (farther from the camera); elbows/knees sit between.
Z_TABLE: dict[str, float] = {
    "nose": 0.50,
    "left_eye": 0.50,
    "right_eye": 0.50,
    "left_ear": 0.50,
    "right_ear": 0.50,
    "left_shoulder": 0.50,
    "right_shoulder": 0.50,
    "left_hip": 0.50,
    "right_hip": 0.50,
    "left_elbow": 0.55,
    "right_elbow": 0.55,
    "left_knee": 0.55,
    "right_knee": 0.55,
    "left_wrist": 0.60,
    "right_wrist": 0.60,
    "left_ankle": 0.65,
    "right_ankle": 0.65,
}

#: Camera-plane z used for labels absent from :data:`Z_TABLE`.
DEFAULT_Z = 0.50

#: Per-joint depth priors (camera plane = 0.5) for the heuristic backend.
DEPTH_PRIOR: dict[str, float] = {
    "nose": 0.50,
    "left_eye": 0.50,
    "right_eye": 0.50,
    "left_ear": 0.50,
    "right_ear": 0.50,
    "left_shoulder": 0.50,
    "right_shoulder": 0.50,
    "left_hip": 0.50,
    "right_hip": 0.50,
    "left_elbow": 0.53,
    "right_elbow": 0.53,
    "left_knee": 0.53,
    "right_knee": 0.53,
    "left_wrist": 0.56,
    "right_wrist": 0.56,
    "left_ankle": 0.60,
    "right_ankle": 0.60,
}

DEFAULT_PRIOR = 0.50

#: Gain scaling how strongly a joint's vertical position (y) and the person's
#: 2D scale push z away from the camera plane.
Y_DRIFT_GAIN = 0.30

#: Person-scale fallback when shoulder keypoints are missing.
DEFAULT_SCALE = 0.50

#: Adjacent joint pairs used by the bone-length consistency clamp.
BONES: list[tuple[str, str]] = [
    ("left_shoulder", "left_elbow"),
    ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"),
    ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"),
    ("right_knee", "right_ankle"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
]

#: |dz| along a bone may not exceed this fraction of the observed 2D bone length.
BONE_Z_CLAMP_RATIO = 0.50


def depth_multiplier(depth_mode: str) -> float:
    """Resolve a ``depth_mode`` name to a deviation multiplier.

    Unknown values resolve to the default ``proportional`` (1.0), per spec
    REQ-2 ("unknown depth_mode -> defaults").
    """
    return DEPTH_MODES.get(depth_mode, 1.0)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` into ``[low, high]``."""
    return min(high, max(low, value))


@runtime_checkable
class LiftingBackend(Protocol):
    """Protocol for 3D lifting backends (spec REQ-2)."""

    def lift(self, keypoints_2d: list[Keypoints2D]) -> list[Keypoints3D]:
        """Lift 2D keypoints into normalized 3D keypoints.

        Args:
            keypoints_2d: Input frames, one :class:`Keypoints2D` per frame.

        Returns:
            One :class:`Keypoints3D` per input frame, minus confidence-filtered
            joints applied by the caller; empty input yields [].
        """
        ...


class SyntheticLiftingBackend:
    """Deterministic per-joint z-table lifting (default backend, REQ-2).

    Every joint keeps its 2D ``x``/``y`` geometry, gets a fixed ``z`` from
    :data:`Z_TABLE` (deviation from 0.5 multiplied by the ``depth_mode``
    multiplier, clamped to [0, 1]), confidence 0.95 and ``visible=True``.
    """

    def __init__(self, depth_mode: str = "proportional") -> None:
        self._multiplier = depth_multiplier(depth_mode)

    def lift(self, keypoints_2d: list[Keypoints2D]) -> list[Keypoints3D]:
        """Lift every frame deterministically from the z-table."""
        frames: list[Keypoints3D] = []
        for kp2d in keypoints_2d:
            keypoints = [
                Keypoint3D(
                    label=kp.label,
                    x=kp.x,
                    y=kp.y,
                    z=_clamp(
                        DEFAULT_Z
                        + (Z_TABLE.get(kp.label, DEFAULT_Z) - DEFAULT_Z) * self._multiplier
                    ),
                    confidence=0.95,
                    visible=True,
                )
                for kp in kp2d.keypoints
            ]
            frames.append(Keypoints3D(frame_index=kp2d.frame_index, keypoints=keypoints))
        return frames


class HeuristicLiftingBackend:
    """Anthropometric depth lifting (REQ-2).

    Person scale is estimated from the 2D shoulder extent; per-joint depth
    priors drift with vertical position (y) and scale; bone-length consistency
    clamps keep 3D joint spread plausible; final clamp keeps z in [0, 1].
    Deterministic given the input.
    """

    def __init__(self, depth_mode: str = "proportional") -> None:
        self._multiplier = depth_multiplier(depth_mode)

    def lift(self, keypoints_2d: list[Keypoints2D]) -> list[Keypoints3D]:
        """Lift every frame using heuristics over its 2D geometry."""
        frames: list[Keypoints3D] = []
        for kp2d in keypoints_2d:
            by_label = {kp.label: kp for kp in kp2d.keypoints}
            if not by_label:
                # Missing labels: empty per-frame output, never crash (REQ-2).
                frames.append(Keypoints3D(frame_index=kp2d.frame_index, keypoints=[]))
                continue
            scale = self._person_scale(by_label)
            keypoints = [self._lift_joint(kp, scale) for kp in kp2d.keypoints]
            keypoints = self._clamp_bones(keypoints)
            frames.append(Keypoints3D(frame_index=kp2d.frame_index, keypoints=keypoints))
        return frames

    def _person_scale(self, by_label: dict[str, Keypoint]) -> float:
        """Estimate person scale from the 2D shoulder separation."""
        left = by_label.get("left_shoulder")
        right = by_label.get("right_shoulder")
        if left is not None and right is not None:
            return abs(left.x - right.x)
        return DEFAULT_SCALE

    def _lift_joint(self, kp: Keypoint, scale: float) -> Keypoint3D:
        """Lift a single 2D joint into 3D.

        ``z`` = prior + (y - 0.5) * scale * gain, whole deviation multiplied
        by the ``depth_mode`` multiplier, then clamped to [0, 1].
        """
        raw_z = DEPTH_PRIOR.get(kp.label, DEFAULT_PRIOR) + (kp.y - 0.5) * scale * Y_DRIFT_GAIN
        z = _clamp(DEFAULT_Z + (raw_z - DEFAULT_Z) * self._multiplier)
        return Keypoint3D(
            label=kp.label,
            x=kp.x,
            y=kp.y,
            z=z,
            confidence=kp.confidence,
            visible=True,
        )

    def _clamp_bones(self, keypoints: list[Keypoint3D]) -> list[Keypoint3D]:
        """Clamp z-spread along known bones to the observed 2D bone length.

        Iterates :data:`BONES` in fixed order, so the result is deterministic.
        """
        by_label = {kp.label: kp for kp in keypoints}
        for label_a, label_b in BONES:
            a = by_label.get(label_a)
            b = by_label.get(label_b)
            if a is None or b is None:
                continue
            bone_2d = math.hypot(a.x - b.x, a.y - b.y)
            if bone_2d <= 1e-9:
                continue
            limit = BONE_Z_CLAMP_RATIO * bone_2d
            z_b = _clamp(b.z, a.z - limit, a.z + limit)
            if z_b != b.z:
                by_label[label_b] = Keypoint3D(
                    label=b.label,
                    x=b.x,
                    y=b.y,
                    z=z_b,
                    confidence=b.confidence,
                    visible=b.visible,
                )
        # Every keypoint label is present in ``by_label`` (it was built from
        # the same list), so this preserves input order with clamped z values.
        return [by_label[kp.label] for kp in keypoints]


class OnnxLiftingBackend:
    """Lazy ONNX Runtime lifting seam (REQ-2).

    Importing onnxruntime happens at construction time so a missing package
    surfaces a clear ImportError (spec REQ-2); inference is a placeholder.
    """

    def __init__(self, model_path: str | Path = "models/pose3d.onnx") -> None:
        """Initialize the ONNX backend with a model path.

        Args:
            model_path: Path to the ONNX model file.

        Raises:
            ImportError: If onnxruntime is not installed.
        """
        self.model_path = Path(model_path)
        try:
            import onnxruntime  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "onnxruntime is required for OnnxLiftingBackend but is not installed. "
                "Install it with: pip install onnxruntime"
            ) from e

    def lift(self, keypoints_2d: list[Keypoints2D]) -> list[Keypoints3D]:
        """Lift 2D keypoints using ONNX Runtime.

        Args:
            keypoints_2d: Input frames.

        Raises:
            NotImplementedError: ONNX inference is not yet implemented.
        """
        # TODO: implement actual ONNX lifting once a model is committed.
        raise NotImplementedError(
            f"ONNX lifting not yet implemented. Model path: {self.model_path}"
        )
