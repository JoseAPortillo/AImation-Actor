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

# TopDownAffine padding factor (mmpose default).
_TOPDOWN_PADDING: float = 1.25

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
        # mmpose SimCC split ratio: bins_per_axis / input_size (2.0 for RTMPose).
        self._simcc_split_ratio_x: float = 2.0
        self._simcc_split_ratio_y: float = 2.0

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

        # SimCC split ratio (mmpose convention): bins = input_size × ratio,
        # so ratio = bins / input_size (2.0 for RTMPose-S: 384/192, 512/256).
        if self._num_bins_x > 0 and self._input_w > 0:
            self._simcc_split_ratio_x = self._num_bins_x / self._input_w
        if self._num_bins_y > 0 and self._input_h > 0:
            self._simcc_split_ratio_y = self._num_bins_y / self._input_h

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

    def _preprocess_crop(self, crop: np.ndarray) -> np.ndarray:
        """Normalize an affine-warped crop for pose inference.

        Unlike :meth:`_preprocess_frame` which resizes the full frame,
        this method expects the crop to already be the correct model
        input size (e.g. 256×192 from :class:`TopDownAffine`).  It only
        performs BGR→RGB, ImageNet normalization, and NCHW transpose.

        Args:
            crop: BGR uint8 crop at the model's expected input resolution.

        Returns:
            Float32 NCHW array ready for onnxruntime.
        """
        rgb: np.ndarray = np.asarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), dtype=np.uint8)
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
        """Decode SimCC logits into (x_px, y_px, confidence) per keypoint.

        The RTMPose ONNX emits raw logits per bin; the bin with the highest
        logit on each axis selects the joint location, mapped to *pixel
        coordinates in the model input space* via the mmpose SimCC split
        ratio: ``x_px = argmax / split_ratio`` (split ratio 2.0 for
        RTMPose-S, i.e. 384 bins over a 192-wide input).

        Confidence follows mmpose's ``decode_simcc``: the geometric mean of
        the two axis peaks, ``sqrt(max_x * max_y)`` (no softmax — the SDK
        model outputs raw logits), clamped to [0, 1].

        Args:
            simcc_x: Shape ``(K, num_bins_x)`` — logits for the x-axis.
            simcc_y: Shape ``(K, num_bins_y)`` — logits for the y-axis.

        Returns:
            List of ``(x_px, y_px, confidence)`` tuples, one per keypoint,
            where x_px ∈ [0, input_w - 1] and y_px ∈ [0, input_h - 1].
        """
        num_kp = simcc_x.shape[0]
        results: list[tuple[float, float, float]] = []

        for k in range(num_kp):
            x_logits = simcc_x[k]
            y_logits = simcc_y[k]

            x_bin = int(np.argmax(x_logits))
            y_bin = int(np.argmax(y_logits))
            x_px = x_bin / self._simcc_split_ratio_x
            y_px = y_bin / self._simcc_split_ratio_y

            # Confidence: geometric mean of axis peaks on raw logits (mmpose
            # decode_simcc), clamped to [0, 1].
            peak_x = float(np.max(x_logits))
            peak_y = float(np.max(y_logits))
            conf = max(0.0, min(1.0, float(np.sqrt(peak_x * peak_y))))

            results.append((float(x_px), float(y_px), conf))

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

                # Full-frame path: the frame was resized into the model input
                # space, so pixel coords normalise by (input_size - 1).
                num_x = float(max(self._input_w - 1, 1))
                num_y = float(max(self._input_h - 1, 1))
                keypoints = [
                    Keypoint(
                        label=COCO17_LABELS[k],
                        x=max(0.0, min(1.0, xy[0] / num_x)),
                        y=max(0.0, min(1.0, xy[1] / num_y)),
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


class TopDownOnnxBackend:
    """Top-down pose pipeline: RTMDet-nano detector + TopDownAffine + RTMPose-S.

    Composes a :class:`~.detectors.RTMDetPersonDetector` (person bounding
    boxes), the mmpose-style **TopDownAffine** transform (padding=1.25,
    aspect-preserving letterbox, model input 256×192), and an
    :class:`OnnxBackend` pose engine.

    Pipeline per frame::

        1. Detect persons → list[PersonBox]
        2. Select best person (area × score) or emit zero-confidence.
        3. TopDownAffine: generate 2×3 affine from bbox → model input size.
        4. Warp crop, run RTMPose-S on the affine-warped crop.
        5. Decode SimCC → keypoints in model-input pixel space.
        6. Map keypoints back to original frame via inverse affine.

    The ``PoseEstimator`` protocol signature is preserved:
    ``estimate(frames) -> list[Keypoints2D]``.

    TopDownAffine math (mmpose convention):
        - Given person bbox: center (cx, cy), size = max(w, h).
        - Scale = size × padding / 200  (200 is mmpose convention).
        - Crop region: [cx − scale×96, cy − scale×128,
                        cx + scale×96, cy + scale×128]  for 192×256.
        - Forward affine  (source → model):
            x_model = (x_src − src_x) × (input_w / crop_w)
            y_model = (y_src − src_y) × (input_h / crop_h)
        - Inverse affine  (model → source), model coords are pixels
            (argmax / SimCC split ratio, where split ratio = bins / size):
            x_src = x_px × inv[0,0] + y_px × inv[0,1] + inv[0,2]
            y_src = x_px × inv[1,0] + y_px × inv[1,1] + inv[1,2]

    Constants:
        - ``_TOPDOWN_PADDING = 1.25`` (mmpose default).
        - Pose model input: 192×256 (W×H), matching RTMPose-S.
        - Scale formula: ``scale = max(w, h) × 1.25 / 200``.
    """

    def __init__(
        self,
        model_dir: str | Path | None = None,
        detector_path: str | Path | None = None,
        pose_path: str | Path | None = None,
    ) -> None:
        """Initialise the top-down pipeline.

        Args:
            model_dir: Directory containing model files (fallback resolver).
            detector_path: Explicit path to ``rtmdet-nano.onnx``.
            pose_path: Explicit path to ``rtmpose.onnx``.
        """
        self._model_dir = Path(model_dir) if model_dir else Path("models")
        self._detector_path = Path(detector_path) if detector_path else None
        self._pose_path = Path(pose_path) if pose_path else None
        self._detector: Any = None  # lazy-init
        self._pose_backend: OnnxBackend | None = None

    # -- registry convenience ------------------------------------------------

    @classmethod
    def from_registry(cls, registry: ModelRegistry | None = None) -> TopDownOnnxBackend:
        """Create a :class:`TopDownOnnxBackend` from the model catalog.

        Resolves both ``"rtmdet-nano"`` and ``"rtmpose-light"`` entries.

        Args:
            registry: Optional pre-built model registry instance.

        Returns:
            A ready-to-use :class:`TopDownOnnxBackend`.
        """
        from aimation_actor_core.infrastructure.models.registry import ModelRegistry

        if registry is None:
            registry = ModelRegistry()
        det_spec = registry.get("rtmdet-nano")
        pose_spec = registry.get("rtmpose-light")
        det_path = registry.installed_path(det_spec)
        pose_path = registry.installed_path(pose_spec)
        return cls(model_dir=det_path.parent, detector_path=det_path, pose_path=pose_path)

    # -- session bootstrap ---------------------------------------------------

    def _ensure_sessions(self) -> None:
        """Lazily initialise detector and pose ONNX sessions."""
        from aimation_actor_core.infrastructure.ai_models.detectors import (
            RTMDetPersonDetector,
        )

        if self._detector is not None:
            return

        det_path = self._detector_path or (self._model_dir / "rtmdet-nano.onnx")
        pose_path = self._pose_path or (self._model_dir / "rtmpose.onnx")

        self._detector = RTMDetPersonDetector(model_path=det_path)
        self._pose_backend = OnnxBackend(model_path=pose_path)
        # Warm up both sessions (creates InferenceSessions).
        self._detector._ensure_session()
        self._pose_backend._ensure_session()

    # -- TopDownAffine -------------------------------------------------------

    @staticmethod
    def _compute_affine(
        box_cx: float,
        box_cy: float,
        box_size: float,
        input_w: int = 192,
        input_h: int = 256,
        padding: float = _TOPDOWN_PADDING,
    ) -> tuple[np.ndarray, float, float, float]:
        """Compute the 2×3 affine matrix mapping source → model input.

        Follows mmpose TopDownAffine convention:
            scale = box_size × padding / 200
            source crop: [cx − scale×input_w/2, cy − scale×input_h/2,
                          cx + scale×input_w/2, cy + scale×input_h/2]

        Args:
            box_cx: Person bbox centre x (original frame pixels).
            box_cy: Person bbox centre y (original frame pixels).
            box_size: Person bbox max dimension (w, h) in pixels.
            input_w: Model input width (default 192).
            input_h: Model input height (default 256).
            padding: Scale padding factor (default 1.25).

        Returns:
            Tuple of (affine_matrix_2x3, crop_scale, offset_x, offset_y)
            where the latter three are needed for inverse mapping.
        """
        scale = box_size * padding / 200.0
        crop_w = scale * input_w
        crop_h = scale * input_h

        # Source top-left of the crop.
        src_x = box_cx - crop_w / 2.0
        src_y = box_cy - crop_h / 2.0

        # Forward affine matrix: source → model.
        # x_model = (x_src − src_x) × (input_w / crop_w)
        # y_model = (y_src − src_y) × (input_h / crop_h)
        sx = input_w / crop_w if crop_w > 0 else 1.0
        sy = input_h / crop_h if crop_h > 0 else 1.0
        affine: np.ndarray = np.array(
            [[sx, 0.0, -src_x * sx], [0.0, sy, -src_y * sy]],
            dtype=np.float64,
        )
        return affine, scale, src_x, src_y

    @staticmethod
    def _inverse_affine(
        affine: np.ndarray,
    ) -> np.ndarray:
        """Invert a 2×3 affine matrix (model → source)."""
        # Augment to 3×3, invert, extract top 2 rows.
        a3 = np.eye(3, dtype=np.float64)
        a3[:2, :] = affine
        inv = np.linalg.inv(a3)
        return inv[:2, :]

    @staticmethod
    def _warp_crop(
        frame: np.ndarray,
        affine: np.ndarray,
        input_w: int = 192,
        input_h: int = 256,
    ) -> np.ndarray:
        """Apply affine warp to extract the pose crop.

        Args:
            frame: Original BGR uint8 frame.
            affine: 2×3 affine matrix (source → model).
            input_w: Output width (default 192).
            input_h: Output height (default 256).

        Returns:
            Warped BGR uint8 crop of shape ``(input_h, input_w, 3)``.
        """
        return cv2.warpAffine(
            frame,
            affine,
            (input_w, input_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(114, 114, 114),
        )

    # -- SimCC decoding (delegates to OnnxBackend) ----------------------------

    def _decode_simcc(
        self,
        simcc_x: np.ndarray,
        simcc_y: np.ndarray,
    ) -> list[tuple[float, float, float]]:
        """Decode SimCC logits → (x_px, y_px, confidence) per keypoint.

        Identical logic to :meth:`OnnxBackend._decode_simcc` — pixel
        coordinates in the model input space, confidence = sqrt(max_x·max_y).
        """
        assert self._pose_backend is not None
        return self._pose_backend._decode_simcc(simcc_x, simcc_y)

    # -- public API -----------------------------------------------------------

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Run the full top-down pipeline: detect → affine → pose → decode.

        For each frame:
            1. Run RTMDet-nano person detector.
            2. Select the best person (highest area × score).
            3. Compute TopDownAffine and warp the crop.
            4. Run RTMPose-S on the affine-warped crop.
            5. Decode SimCC and map keypoints back through inverse affine.

        If no person is detected, emits 17 zero-confidence keypoints.

        Args:
            frames: List of video frames as BGR uint8 numpy arrays.

        Returns:
            List of :class:`Keypoints2D`, one per input frame.
        """
        from aimation_actor_core.infrastructure.ai_models.detectors import (
            select_best_person,
        )

        self._ensure_sessions()
        assert self._detector is not None
        assert self._pose_backend is not None

        det_results = self._detector.detect(frames)
        pose_session = self._pose_backend._ensure_session()
        input_h = self._pose_backend._input_h
        input_w = self._pose_backend._input_w

        results: list[Keypoints2D] = []

        for frame_idx, (frame, person_boxes) in enumerate(zip(frames, det_results, strict=True)):
            best = select_best_person(person_boxes)

            if best is None:
                # No person detected → zero-confidence fallback.
                results.append(
                    Keypoints2D(
                        frame_index=frame_idx,
                        keypoints=[
                            Keypoint(label=COCO17_LABELS[k], x=0.0, y=0.0, confidence=0.0)
                            for k in range(_NUM_KEYPOINTS)
                        ],
                    )
                )
                continue

            # Compute TopDownAffine from best person bbox.
            affine, _scale, _src_x, _src_y = self._compute_affine(
                best.cx, best.cy, best.size, input_w=input_w, input_h=input_h
            )
            crop = self._warp_crop(frame, affine, input_w=input_w, input_h=input_h)

            # Run pose on the affine-warped crop.
            try:
                blob = self._pose_backend._preprocess_crop(crop)
                outputs = pose_session.run(
                    None,
                    {self._pose_backend._input_name: blob},
                )
                simcc_x = outputs[0][0]  # (K, num_bins_x)
                simcc_y = outputs[1][0]  # (K, num_bins_y)
                decoded = self._decode_simcc(simcc_x, simcc_y)

                # Map keypoints from model pixel space → original frame coords via
                # the inverse affine (mmpose convention).
                inv = self._inverse_affine(affine)
                fw = float(frame.shape[1])
                fh = float(frame.shape[0])

                keypoints = []
                for k, xy in enumerate(decoded):
                    x_raw = xy[0] * inv[0, 0] + xy[1] * inv[0, 1] + inv[0, 2]
                    y_raw = xy[0] * inv[1, 0] + xy[1] * inv[1, 1] + inv[1, 2]
                    keypoints.append(
                        Keypoint(
                            label=COCO17_LABELS[k],
                            x=max(0.0, min(1.0, x_raw / fw)),
                            y=max(0.0, min(1.0, y_raw / fh)),
                            confidence=max(0.0, min(1.0, xy[2])),
                        )
                    )
            except Exception:
                logger.warning(
                    "Frame %d pose inference failed; emitting zero-confidence keypoints",
                    frame_idx,
                    exc_info=True,
                )
                keypoints = [
                    Keypoint(label=COCO17_LABELS[k], x=0.0, y=0.0, confidence=0.0)
                    for k in range(_NUM_KEYPOINTS)
                ]
            results.append(Keypoints2D(frame_index=frame_idx, keypoints=keypoints))

        return results
