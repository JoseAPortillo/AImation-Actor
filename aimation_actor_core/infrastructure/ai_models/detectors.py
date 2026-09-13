"""Person detector backend for top-down pose pipelines.

Provides :class:`RTMDetPersonDetector` — a pure-ONNX person detector
using RTMDet-nano trained on COCO person class.  The detector is used as
the first stage of a top-down pose estimation pipeline: it produces
bounding boxes that are then affine-warped into the pose model's input
space.

RTMDet-nano ONNX input/output layout (from OpenMMLab SDK export):
    - Input ``input``: ``[batch, 3, H, W]`` float32 NCHW, expected 320×320.
    - Output ``dets``: ``[batch, 100, 5]`` float32 — (x1, y1, x2, y2, score).
    - Output ``labels``: ``[batch, 100]`` int64 — class labels (0 = person).

The model includes built-in NMS (iou_threshold=0.5, max_per_img=100).
Our decode step applies an additional configurable score filter and NMS
safety net.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# RTMDet-nano expects 320×320 input (from pipeline.json resize+pad).
_DETECTOR_INPUT_SIZE: int = 320

# Person class index in COCO-trained RTMDet.
_PERSON_CLASS: int = 0

# RTMDet preprocessing: ImageNet normalization in BGR channel order.
# (pipeline.json: to_rgb=false, mean=[103.53,116.28,123.675],
#  std=[57.375,57.12,58.395]).
_DET_MEAN: np.ndarray = np.array([103.53, 116.28, 123.675], dtype=np.float32)
_DET_STD: np.ndarray = np.array([57.375, 57.12, 58.395], dtype=np.float32)

# Letterbox pad fill value (pipeline.json: pad_val.img = [114, 114, 114]).
_PAD_FILL: int = 114


# ---------------------------------------------------------------------------
# Data class for detector results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonBox:
    """Bounding box for a detected person in original frame coordinates.

    All coordinates are in pixels relative to the original input frame
    (before any detector preprocessing).  The box is axis-aligned with
    (x1, y1) as the top-left corner and (x2, y2) as the bottom-right.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def width(self) -> float:
        """Box width in pixels."""
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        """Box height in pixels."""
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        """Box area in pixels²."""
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def cx(self) -> float:
        """Center x coordinate."""
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        """Center y coordinate."""
        return (self.y1 + self.y2) / 2.0

    @property
    def size(self) -> float:
        """Max dimension (width, height) — used by TopDownAffine scale."""
        return max(self.width, self.height)


# ---------------------------------------------------------------------------
# Pure functions (independently testable)
# ---------------------------------------------------------------------------


def letterbox_resize(
    frame: np.ndarray,
    target_size: int = _DETECTOR_INPUT_SIZE,
) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Letterbox-resize a frame to a square with padding.

    Maintains aspect ratio by fitting the frame inside ``target_size ×
    target_size``, padding the shorter dimension with ``_PAD_FILL``.

    Args:
        frame: BGR uint8 image of arbitrary size.
        target_size: Target square dimension (default 320).

    Returns:
        Tuple of (padded image, scale_factor, (pad_left, pad_top)) where
        scale_factor maps detector coordinates back to the original frame.
    """
    h, w = frame.shape[:2]
    if h == 0 or w == 0:
        return (
            np.full((target_size, target_size, 3), _PAD_FILL, dtype=np.uint8),
            1.0,
            (0, 0),
        )
    scale = min(target_size / w, target_size / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized: np.ndarray = cv2.resize(frame, (new_w, new_h))
    padded: np.ndarray = np.full((target_size, target_size, 3), _PAD_FILL, dtype=np.uint8)
    padded[:new_h, :new_w] = resized
    return padded, scale, (0, 0)


def preprocess_detector_frame(frame: np.ndarray) -> np.ndarray:
    """Preprocess a BGR frame for RTMDet-nano inference.

    Steps (matching OpenMMLab pipeline.json):
        1. Letterbox-resize to 320×320 (pad with 114).
        2. BGR (no rgb conversion — to_rgb=false).
        3. float32, normalize: ``(pixel - mean) / std``.
        4. Transpose HWC → CHW.
        5. Add batch dimension → NCHW.

    Args:
        frame: BGR uint8 image of arbitrary size.

    Returns:
        Float32 NCHW array of shape ``(1, 3, 320, 320)``.
    """
    padded, _scale, _offset = letterbox_resize(frame)
    img = padded.astype(np.float32)
    img = (img - _DET_MEAN) / _DET_STD
    img = img.transpose(2, 0, 1)  # HWC → CHW
    result: np.ndarray = img[np.newaxis, ...]  # add batch dim → (1, 3, H, W)
    return result


def decode_person_detections(
    dets: np.ndarray,
    labels: np.ndarray,
    score_threshold: float = 0.3,
    nms_iou_threshold: float = 0.65,
) -> list[PersonBox]:
    """Decode RTMDet-nano raw outputs into PersonBox objects.

    Filters for person class (0), applies score threshold, then NMS.

    Args:
        dets: Raw ``[N, 5]`` array (x1, y1, x2, y2, score).
        labels: Raw ``[N]`` int64 class labels.
        score_threshold: Minimum confidence to keep a detection.
        nms_iou_threshold: IoU threshold for non-maximum suppression.

    Returns:
        List of :class:`PersonBox` in descending score order.
    """
    # Filter: person class + score threshold.
    mask: np.ndarray = (labels == _PERSON_CLASS) & (dets[:, 4] > score_threshold)
    filtered_dets = dets[mask]

    if len(filtered_dets) == 0:
        return []

    # NMS safety net (model already does internal NMS, but we add ours
    # for robustness).
    indices = _nms(filtered_dets[:, :4], filtered_dets[:, 4], nms_iou_threshold)

    results: list[PersonBox] = []
    for idx in indices:
        x1, y1, x2, y2, score = filtered_dets[idx]
        results.append(
            PersonBox(
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
                score=float(score),
            )
        )
    return results


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Pure-numpy Non-Maximum Suppression.

    Args:
        boxes: ``[N, 4]`` array of (x1, y1, x2, y2).
        scores: ``[N]`` confidence scores.
        iou_threshold: IoU above which a box is suppressed.

    Returns:
        List of kept indices (descending by score).
    """
    if len(boxes) == 0:
        return []

    order: np.ndarray = np.argsort(-scores)
    keep: list[int] = []

    while len(order) > 0:
        i = int(order[0])
        keep.append(i)

        if len(order) == 1:
            break

        # IoU of box[i] with all remaining boxes.
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)

        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_j = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (
            boxes[order[1:], 3] - boxes[order[1:], 1]
        )
        union = area_i + area_j - inter
        iou = np.where(union > 0, inter / union, 0.0)

        # Keep boxes with IoU below threshold.
        mask: np.ndarray = iou <= iou_threshold
        order = order[1:][mask]

    return keep


def select_best_person(boxes: list[PersonBox]) -> PersonBox | None:
    """Select the highest-scoring, largest-area person from a detection list.

    The selection score is ``area × score`` — this favours prominent
    subjects that fill the frame (matching the single-subject camera
    assumption).

    Args:
        boxes: List of detected :class:`PersonBox`.

    Returns:
        The best :class:`PersonBox`, or ``None`` if the list is empty.
    """
    if not boxes:
        return None
    return max(boxes, key=lambda b: b.area * b.score)


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------


class RTMDetPersonDetector:
    """RTMDet-nano person detector using ONNX Runtime.

    Produces bounding boxes for detected persons in each frame.  The
    session is created lazily on the first call to :meth:`detect` and
    reused for subsequent calls.

    Args:
        model_path: Path to the RTMDet-nano ONNX model file.
        score_threshold: Minimum confidence to keep a detection (default 0.3).
        nms_iou_threshold: IoU threshold for NMS (default 0.65).
    """

    def __init__(
        self,
        model_path: str | Path,
        score_threshold: float = 0.3,
        nms_iou_threshold: float = 0.65,
    ) -> None:
        self.model_path = Path(model_path)
        self.score_threshold = score_threshold
        self.nms_iou_threshold = nms_iou_threshold
        self._session: Any = None
        self._input_name: str = ""

    # -- session bootstrap ---------------------------------------------------

    def _ensure_session(self) -> Any:  # noqa: ANN401 — onnxruntime session is untyped
        """Lazily create the onnxruntime InferenceSession for detection.

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
                "onnxruntime is required for RTMDetPersonDetector but is not "
                "installed.  Install it with: pip install onnxruntime"
            ) from exc

        if not self.model_path.exists():
            raise FileNotFoundError(
                "RTMDet-nano model not found.  Install with:\n"
                "  python -m aimation_actor_core.models_cli install rtmdet-nano "
                "--accept-license Apache-2.0 --trust-on-first-use"
            )

        session = onnxruntime.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )

        # Introspect input.
        input_meta = session.get_inputs()[0]
        self._input_name = input_meta.name

        # Log output shapes for diagnostic purposes.
        for o in session.get_outputs():
            logger.debug("RTMDet output: name=%s shape=%s", o.name, o.shape)

        self._session = session
        logger.info("RTMDet-nano session ready: input=%r", self._input_name)
        return session

    # -- public API ----------------------------------------------------------

    def detect(self, frames: list[np.ndarray]) -> list[list[PersonBox]]:
        """Detect persons in each frame.

        Args:
            frames: List of video frames as BGR uint8 numpy arrays.

        Returns:
            List of detection lists, one per input frame.  Each inner
            list contains 0 or more :class:`PersonBox` in descending
            score order.
        """
        session = self._ensure_session()
        results: list[list[PersonBox]] = []

        for frame in frames:
            blob = preprocess_detector_frame(frame)
            outputs = session.run(None, {self._input_name: blob})
            dets: np.ndarray = outputs[0][0]  # (100, 5)
            labels: np.ndarray = outputs[1][0]  # (100,)

            # Decode back to original frame coordinates.
            scale = min(_DETECTOR_INPUT_SIZE / max(frame.shape[1], 1),
                        _DETECTOR_INPUT_SIZE / max(frame.shape[0], 1))
            boxes = decode_person_detections(
                dets,
                labels,
                score_threshold=self.score_threshold,
                nms_iou_threshold=self.nms_iou_threshold,
            )
            # Map detector coordinates back to original frame space.
            original_boxes = [
                PersonBox(
                    x1=b.x1 / scale,
                    y1=b.y1 / scale,
                    x2=b.x2 / scale,
                    y2=b.y2 / scale,
                    score=b.score,
                )
                for b in boxes
            ]
            results.append(original_boxes)

        return results
