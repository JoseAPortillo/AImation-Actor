"""Pose estimator backends for pose-2d node."""

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.pose_detection import SingleFramePose


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
    KEYPOINT_LABELS = [
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

    # Fixed normalized coordinates for a standing person (centered)
    FIXED_KEYPOINTS = [
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

    def _fixed_keypoints(self) -> list[Keypoint]:
        """Build the fixed scripted keypoint set at 0.95 confidence."""
        return [
            Keypoint(
                label=label,
                x=x,
                y=y,
                confidence=0.95,  # High confidence for synthetic data
            )
            for (label, (x, y)) in zip(self.KEYPOINT_LABELS, self.FIXED_KEYPOINTS, strict=True)
        ]

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Generate deterministic keypoints for each frame.

        Args:
            frames: List of video frames (ignored, output is fixed).

        Returns:
            List of Keypoints2D with fixed keypoints, one per frame.
        """
        result = []
        for frame_idx in range(len(frames)):
            result.append(Keypoints2D(frame_index=frame_idx, keypoints=self._fixed_keypoints()))
        return result

    def estimate_single(self, frame: np.ndarray) -> SingleFramePose:
        """Return the fixed scripted pose for a single frame (deterministic).

        Args:
            frame: A single video frame as a numpy array (BGR format; ignored).

        Returns:
            SingleFramePose with the fixed keypoint set and 0.95 confidence.
        """
        return SingleFramePose(keypoints=self._fixed_keypoints(), confidence=0.95)


class OnnxBackend:
    """ONNX Runtime backend for real pose estimation.

    Uses a top-down pipeline:
    1. RTMDet-nano: Detect person bounding boxes
    2. RTMPose: Estimate keypoints within each bounding box

    Uses lazy import of onnxruntime so the module can be imported even if
    onnxruntime is not installed. The import happens only when estimate() is called.
    """

    # COCO-17 keypoint labels (matches RTMPose output order)
    KEYPOINT_LABELS = [
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

    def __init__(self, model_dir: str | Path) -> None:
        """Initialize ONNX backend with model directory.

        Expects the following models in the directory:
        - rtmdet-nano.onnx: Person detection
        - rtmpose.onnx: Pose estimation

        Args:
            model_dir: Directory containing ONNX model files.
        """
        self.model_dir = Path(model_dir)
        self._det_session = None  # Lazy-loaded detector
        self._pose_session = None  # Lazy-loaded pose estimator

    def _get_det_session(self):
        """Lazy-load RTMDet Runtime session."""
        if self._det_session is None:
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise ImportError(
                    "onnxruntime is required for OnnxBackend but is not installed. "
                    "Install it with: pip install onnxruntime"
                ) from e
            model_path = self.model_dir / "rtmdet-nano.onnx"
            if not model_path.is_file():
                raise FileNotFoundError(
                    f"ONNX detector model not found: {model_path}"
                )
            self._det_session = ort.InferenceSession(str(model_path))
        return self._det_session

    def _get_pose_session(self):
        """Lazy-load RTMPose Runtime session."""
        if self._pose_session is None:
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise ImportError(
                    "onnxruntime is required for OnnxBackend but is not installed. "
                    "Install it with: pip install onnxruntime"
                ) from e
            model_path = self.model_dir / "rtmpose.onnx"
            if not model_path.is_file():
                raise FileNotFoundError(
                    f"ONNX pose model not found: {model_path}"
                )
            self._pose_session = ort.InferenceSession(str(model_path))
        return self._pose_session

    def _preprocess_det(self, frame: np.ndarray, input_size: tuple[int, int] = (320, 320)) -> np.ndarray:
        """Preprocess frame for RTMDet input.

        Args:
            frame: BGR numpy array (H, W, 3).
            input_size: Target (width, height).

        Returns:
            Preprocessed tensor (1, 3, H, W) normalized to [0, 1].
        """
        import cv2

        # Convert BGR to RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Resize to model input size
        w, h = input_size
        resized = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)

        # Normalize to [0, 1] and convert to float32
        normalized = resized.astype(np.float32) / 255.0

        # Transpose to (C, H, W) and add batch dimension
        tensor = normalized.transpose(2, 0, 1)[np.newaxis, ...]

        return tensor

    def _preprocess_pose(self, frame: np.ndarray, bbox: tuple[int, int, int, int], input_size: tuple[int, int] = (192, 256)) -> np.ndarray:
        """Preprocess cropped region for RTMPose input.

        Args:
            frame: Full BGR numpy array (H, W, 3).
            bbox: Bounding box (x1, y1, x2, y2) in pixel coordinates.
            input_size: Target (width, height) for pose model.

        Returns:
            Preprocessed tensor (1, 3, H, W) normalized to [0, 1].
        """
        import cv2

        x1, y1, x2, y2 = bbox
        h_frame, w_frame = frame.shape[:2]

        # Clamp bbox to frame boundaries
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w_frame, x2)
        y2 = min(h_frame, y2)

        # Crop region
        crop = frame[y1:y2, x1:x2]

        # Convert BGR to RGB
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

        # Resize to model input size
        w, h = input_size
        resized = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)

        # Normalize to [0, 1] and convert to float32
        normalized = resized.astype(np.float32) / 255.0

        # Transpose to (C, H, W) and add batch dimension
        tensor = normalized.transpose(2, 0, 1)[np.newaxis, ...]

        return tensor

    def _detect_persons(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Detect person bounding boxes using RTMDet.

        Args:
            frame: BGR numpy array (H, W, 3).

        Returns:
            List of bounding boxes (x1, y1, x2, y2) in pixel coordinates.
        """
        import cv2

        session = self._get_det_session()
        input_name = session.get_inputs()[0].name
        h_frame, w_frame = frame.shape[:2]

        # Preprocess
        input_size = (320, 320)
        tensor = self._preprocess_det(frame, input_size)

        # Run inference
        dets, labels = session.run(None, {input_name: tensor})

        # dets shape: (1, num_dets, 5) where 5 = [x1, y1, x2, y2, score]
        # labels shape: (1, num_dets) where 0 = person class
        bboxes = []
        det = dets[0]  # First batch
        label = labels[0]

        for i in range(det.shape[0]):
            score = det[i, 4]
            cls = label[i]

            # Keep only person detections (class 0) with score > 0.3
            if cls == 0 and score > 0.3:
                x1, y1, x2, y2 = det[i, :4]

                # Scale back to original frame size
                x1 = int(x1 * w_frame / input_size[0])
                y1 = int(y1 * h_frame / input_size[1])
                x2 = int(x2 * w_frame / input_size[0])
                y2 = int(y2 * h_frame / input_size[1])

                # Add padding (10% on each side)
                pad_x = int((x2 - x1) * 0.1)
                pad_y = int((y2 - y1) * 0.1)
                x1 = max(0, x1 - pad_x)
                y1 = max(0, y1 - pad_y)
                x2 = min(w_frame, x2 + pad_x)
                y2 = min(h_frame, y2 + pad_y)

                bboxes.append((x1, y1, x2, y2))

        # If no person detected, use full frame as fallback
        if not bboxes:
            bboxes.append((0, 0, w_frame, h_frame))

        return bboxes

    def _decode_simcc(self, simcc_x: np.ndarray, simcc_y: np.ndarray, crop_size: tuple[int, int], bbox: tuple[int, int, int, int]) -> list[tuple[float, float, float]]:
        """Decode SimCC outputs to keypoint coordinates in original frame space.

        Args:
            simcc_x: (1, num_keypoints, width_bins)
            simcc_y: (1, num_keypoints, height_bins)
            crop_size: (width, height) of the cropped region fed to pose model
            bbox: Bounding box (x1, y1, x2, y2) in original frame coordinates

        Returns:
            List of (x, y, confidence) tuples normalized to [0, 1].
        """
        import cv2

        num_kpts = simcc_x.shape[1]
        x_bins = simcc_x.shape[2]
        y_bins = simcc_y.shape[2]

        x1, y1, x2, y2 = bbox
        crop_w = x2 - x1
        crop_h = y2 - y1

        keypoints = []
        for k in range(num_kpts):
            # Find argmax for x and y
            x_idx = np.argmax(simcc_x[0, k])
            y_idx = np.argmax(simcc_y[0, k])

            # Get confidence from the activation values
            x_conf = float(simcc_x[0, k, x_idx])
            y_conf = float(simcc_y[0, k, y_idx])
            confidence = float(np.sqrt(max(0, x_conf) * max(0, y_conf)))

            # Convert bin indices to coordinates within crop
            x_crop = float(x_idx) / x_bins * crop_w
            y_crop = float(y_idx) / y_bins * crop_h

            # Convert to original frame coordinates
            x_orig = x1 + x_crop
            y_orig = y1 + y_crop

            # Normalize to [0, 1] based on frame dimensions (we don't have them here,
            # so we'll use the bbox as reference and normalize later)
            keypoints.append((x_orig, y_orig, confidence))

        return keypoints

    def estimate(self, frames: list[np.ndarray]) -> list[Keypoints2D]:
        """Estimate 2D keypoints using ONNX Runtime top-down pipeline.

        Args:
            frames: List of video frames as numpy arrays (BGR format).

        Returns:
            List of Keypoints2D, one per input frame.
        """
        results = []
        for frame_idx, frame in enumerate(frames):
            # Detect persons
            bboxes = self._detect_persons(frame)

            # Use the first/largest person
            bbox = bboxes[0] if bboxes else (0, 0, frame.shape[1], frame.shape[0])

            # Preprocess for pose
            tensor = self._preprocess_pose(frame, bbox)

            # Run pose inference
            pose_session = self._get_pose_session()
            input_name = pose_session.get_inputs()[0].name
            simcc_x, simcc_y = pose_session.run(None, {input_name: tensor})

            # Decode keypoints
            crop_size = (192, 256)
            kpts_data = self._decode_simcc(simcc_x, simcc_y, crop_size, bbox)

            # Build Keypoints2D (normalize to [0, 1])
            h_frame, w_frame = frame.shape[:2]
            keypoints = [
                Keypoint(
                    label=self.KEYPOINT_LABELS[i],
                    x=kpts_data[i][0] / w_frame,
                    y=kpts_data[i][1] / h_frame,
                    confidence=kpts_data[i][2],
                )
                for i in range(len(self.KEYPOINT_LABELS))
            ]

            results.append(Keypoints2D(frame_index=frame_idx, keypoints=keypoints))

        return results

    def estimate_single(self, frame: np.ndarray) -> SingleFramePose:
        """Single-frame estimation using ONNX Runtime top-down pipeline.

        Args:
            frame: A single video frame as a numpy array (BGR format).

        Returns:
            SingleFramePose with detected keypoints and average confidence.
        """
        # Detect persons
        bboxes = self._detect_persons(frame)

        # Use the first/largest person
        bbox = bboxes[0] if bboxes else (0, 0, frame.shape[1], frame.shape[0])

        # Preprocess for pose
        tensor = self._preprocess_pose(frame, bbox)

        # Run pose inference
        pose_session = self._get_pose_session()
        input_name = pose_session.get_inputs()[0].name
        simcc_x, simcc_y = pose_session.run(None, {input_name: tensor})

        # Decode keypoints
        crop_size = (192, 256)
        kpts_data = self._decode_simcc(simcc_x, simcc_y, crop_size, bbox)

        # Build Keypoint list (normalize to [0, 1])
        h_frame, w_frame = frame.shape[:2]
        keypoints = [
            Keypoint(
                label=self.KEYPOINT_LABELS[i],
                x=kpts_data[i][0] / w_frame,
                y=kpts_data[i][1] / h_frame,
                confidence=kpts_data[i][2],
            )
            for i in range(len(self.KEYPOINT_LABELS))
        ]

        # Calculate average confidence
        avg_confidence = float(np.mean([k.confidence for k in keypoints]))

        return SingleFramePose(keypoints=keypoints, confidence=avg_confidence)
