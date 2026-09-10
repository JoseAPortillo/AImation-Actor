"""Pose estimator backends for pose-2d node."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import cv2
import numpy as np

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D

if TYPE_CHECKING:
    from aimation_actor_core.infrastructure.models.registry import ModelRegistry

logger = logging.getLogger(__name__)

# COCO-17 keypoint labels (order matches RTMPose output).
COCO17_LABELS: list[str] = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

_NUM_KEYPOINTS: int = 17

# ImageNet normalization in 0-255 scale (COCO convention).
_IMAGENET_MEAN: np.ndarray = np.array([123.675, 116.28, 103.53], dtype=np.float32)
_IMAGENET_STD: np.ndarray = np.array([58.395, 57.12, 57.375], dtype=np.float32)

_INSTALL_HINT: str = (
    "Model file not found.  Install the RTMPose-S model with:\n"
    "  aimation-models install rtmpose-light "
    "--accept-license Apache-2.0 --trust-on-first-use"
)


@runtime_checkable
class PoseEstimator(Protocol):
    """Protocol for pose estimation backends."""

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Estimate 2D keypoints for each frame.

        Args:
            frames: List of video frames as numpy arrays (BGR format).

        Returns:
            List of Keypoints2D, one per input frame.
        """
        ...


class SyntheticBackend:
    """Deterministic synthetic backend for testing and CI.

    Produces fixed, scripted keypoints regardless of input frames.
    Useful for deterministic graph e2e tests.
    """

    # Standard COCO-style keypoints (17 points)
    KEYPOINT_LABELS: list[str] = list(COCO17_LABELS)

    # Fixed normalized coordinates for a standing person (centered)
    FIXED_KEYPOINTS: list[tuple[float, float]] = [
        (0.50, 0.20),  # nose
        (0.48, 0.18),  # left_eye
        (0.52, 0.18),  # right_eye
        (0.45, 0.20),  # left_ear
        (0.55, 0.20),  # right_ear
        (0.40, 0.35),  # left_shoulder
        (0.60, 0.35),  # right_shoulder
        (0.35, 0.50),  # left_elbow
        (0.65, 0.50),  # right_elbow
        (0.30, 0.65),  # left_wrist
        (0.70, 0.65),  # right_wrist
        (0.45, 0.60),  # left_hip
        (0.55, 0.60),  # right_hip
        (0.45, 0.75),  # left_knee
        (0.55, 0.75),  # right_knee
        (0.45, 0.90),  # left_ankle
        (0.55, 0.90),  # right_ankle
    ]

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Generate deterministic keypoints for each frame.

        Args:
            frames: List of video frames (ignored, output is fixed).

        Returns:
            List of Keypoints2D with fixed keypoints, one per frame.
        """
        result: list[Keypoints2D] = []
        for frame_idx in range(len(frames)):
            keypoints = [
                Keypoint(
                    label=label,
                    x=x,
                    y=y,
                    confidence=0.95,  # High confidence for synthetic data
                )
                for (label, (x, y)) in zip(self.KEYPOINT_LABELS, self.FIXED_KEYPOINTS, strict=True)
            ]
            result.append(Keypoints2D(frame_index=frame_idx, keypoints=keypoints))
        return result


class OnnxBackend:
    """ONNX Runtime backend for real pose estimation (RTMPose-S).

    Uses lazy import of onnxruntime so the module can be imported even if
    onnxruntime is not installed.  The session is created once on the first
    call to :meth:`estimate` and reused for subsequent calls.

    The model expects preprocessed NCHW float32 input and produces SimCC
    (Simulated Coordinate Classification) outputs that are decoded into
    normalized [0, 1] keypoints.

    Top-down MVP: the bounding box is assumed to be the entire frame (no
    person detector yet).
    """

    def __init__(self, model_path: str | Path) -> None:
        """Initialize ONNX backend with model path.

        Args:
            model_path: Path to the ONNX model file.
        """
        self.model_path = Path(model_path)
        self._session: Any = None
        self._input_name: str = ""
        self._input_h: int = 0
        self._input_w: int = 0
        self._num_bins_x: int = 0
        self._num_bins_y: int = 0

    # -- registry convenience ------------------------------------------------

    @classmethod
    def from_registry(cls, registry: ModelRegistry | None = None) -> OnnxBackend:
        """Create an :class:`OnnxBackend` from the model catalog.

        Looks up ``"rtmpose-light"`` in the manifest via *registry* and
        resolves the installed path.  If *registry* is ``None`` a default
        ``ModelRegistry()`` rooted at ``models/`` is used.

        Args:
            registry: Optional pre-built model registry instance.

        Returns:
            A ready-to-use :class:`OnnxBackend`.
        """
        from aimation_actor_core.infrastructure.models.registry import ModelRegistry

        if registry is None:
            registry = ModelRegistry()
        spec = registry.get("rtmpose-light")
        model_path = registry.installed_path(spec)
        return cls(model_path=model_path)

    # -- session bootstrap ----------------------------------------------------

    def _ensure_session(self) -> Any:  # noqa: ANN401 — onnxruntime session is untyped
        """Lazily create the onnxruntime InferenceSession.

        Returns:
            The live ``onnxruntime.InferenceSession``.

        Raises:
            ImportError: If onnxruntime is not installed.
            FileNotFoundError: If the model file does not exist.
        """
        if self._session is not None:
            return self._session

        try:
            import onnxruntime  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for OnnxBackend but is not installed. "
                "Install it with: pip install onnxruntime"
            ) from exc

        if not self.model_path.exists():
            raise FileNotFoundError(_INSTALL_HINT)

        session = onnxruntime.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )

        # Introspect input shape to derive target resize dims.
        input_meta = session.get_inputs()[0]
        self._input_name = input_meta.name
        shape = input_meta.shape  # e.g. ["batch", 3, 256, 192]
        # Dynamic dims may be strings — pick the last two ints.
        self._input_h = int(shape[-2])  # height
        self._input_w = int(shape[-1])  # width

        # Introspect output shapes for SimCC bin counts.
        # simcc_x has shape [batch, K, num_bins_x], simcc_y [batch, K, num_bins_y]
        for o in session.get_outputs():
            if o.name == "simcc_x":
                self._num_bins_x = int(o.shape[-1])
            elif o.name == "simcc_y":
                self._num_bins_y = int(o.shape[-1])

        self._session = session
        logger.info(
            "ONNX session ready: input=%r (%dx%d), bins_x=%d, bins_y=%d",
            self._input_name,
            self._input_w,
            self._input_h,
            self._num_bins_x,
            self._num_bins_y,
        )
        return session

    # -- preprocessing --------------------------------------------------------

    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """Resize, normalize and transpose a BGR frame to model input format.

        Steps:
            1. Resize to (input_w, input_h) via bilinear interpolation.
            2. BGR → RGB.
            3. float32, range stays [0, 255].
            4. Normalize: ``(pixel - mean) / std`` (ImageNet in 0-255 scale).
            5. Transpose HWC → CHW.
            6. Add batch dimension → NCHW.

        Args:
            frame: BGR uint8 image of arbitrary size.

        Returns:
            Float32 NCHW array ready for onnxruntime.
        """
        resized: np.ndarray = np.asarray(
            cv2.resize(frame, (self._input_w, self._input_h)), dtype=np.uint8
        )
        rgb: np.ndarray = np.asarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB), dtype=np.uint8)
        tensor = rgb.astype(np.float32)
        tensor = (tensor - _IMAGENET_MEAN) / _IMAGENET_STD
        tensor = tensor.transpose(2, 0, 1)  # HWC → CHW
        result: np.ndarray = tensor[np.newaxis, ...]  # add batch dim → (1, 3, H, W)
        return result

    # -- SimCC decoding -------------------------------------------------------

    def _decode_simcc(
        self,
        simcc_x: np.ndarray,
        simcc_y: np.ndarray,
    ) -> list[tuple[float, float, float]]:
        """Decode SimCC logits into (x_norm, y_norm, confidence) per keypoint.

        For each keypoint the bin with the highest logit is selected on each
        axis.  The bin index is mapped to a [0, 1] coordinate:

        ``coord = argmax / (num_bins - 1)``

        Confidence is the max softmax probability over the bin axis for the
        more confident axis (x or y), clamped to [0, 1].

        Args:
            simcc_x: Shape ``(K, num_bins_x)`` — logits for the x-axis.
            simcc_y: Shape ``(K, num_bins_y)`` — logits for the y-axis.

        Returns:
            List of ``(x, y, confidence)`` tuples, one per keypoint.
        """
        num_kp = simcc_x.shape[0]
        results: list[tuple[float, float, float]] = []

        for k in range(num_kp):
            # x coordinate
            x_logits = simcc_x[k]
            x_bin = int(np.argmax(x_logits))
            x_norm = x_bin / max(self._num_bins_x - 1, 1)

            # y coordinate
            y_logits = simcc_y[k]
            y_bin = int(np.argmax(y_logits))
            y_norm = y_bin / max(self._num_bins_y - 1, 1)

            # Confidence: softmax over each axis, take the higher peak.
            x_conf = _softmax_max(x_logits)
            y_conf = _softmax_max(y_logits)
            conf = max(x_conf, y_conf)

            results.append((float(x_norm), float(y_norm), float(conf)))

        return results

    # -- public API -----------------------------------------------------------

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Estimate 2D keypoints using ONNX Runtime.

        Args:
            frames: List of video frames as numpy arrays (BGR format).

        Returns:
            List of Keypoints2D, one per input frame.

        Raises:
            FileNotFoundError: If the model file is missing.
            ImportError: If onnxruntime is not installed.
        """
        session = self._ensure_session()

        results: list[Keypoints2D] = []
        for frame_idx, frame in enumerate(frames):
            try:
                blob = self._preprocess_frame(frame)
                outputs = session.run(
                    None,
                    {self._input_name: blob},
                )
                simcc_x = outputs[0][0]  # (K, num_bins_x)
                simcc_y = outputs[1][0]  # (K, num_bins_y)
                decoded = self._decode_simcc(simcc_x, simcc_y)

                keypoints = [
                    Keypoint(
                        label=COCO17_LABELS[k],
                        x=max(0.0, min(1.0, xy[0])),
                        y=max(0.0, min(1.0, xy[1])),
                        confidence=max(0.0, min(1.0, xy[2])),
                    )
                    for k, xy in enumerate(decoded)
                ]
            except Exception:
                logger.warning(
                    "Frame %d inference failed; emitting zero-confidence keypoints",
                    frame_idx,
                    exc_info=True,
                )
                keypoints = [
                    Keypoint(label=COCO17_LABELS[k], x=0.0, y=0.0, confidence=0.0)
                    for k in range(_NUM_KEYPOINTS)
                ]

            results.append(Keypoints2D(frame_index=frame_idx, keypoints=keypoints))

        return results


# -- helpers ------------------------------------------------------------------


def _softmax_max(logits: np.ndarray) -> float:
    """Numerically stable softmax, return the maximum probability."""
    shifted = logits - logits.max()
    exp = np.exp(shifted)
    probs: np.ndarray = exp / exp.sum()
    return float(probs.max())
