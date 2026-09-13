"""Tests for person detector module (RTMDetPersonDetector, decode, NMS)."""

from __future__ import annotations

import numpy as np
import pytest

from aimation_actor_core.infrastructure.ai_models.detectors import (
    PersonBox,
    decode_person_detections,
    letterbox_resize,
    preprocess_detector_frame,
    select_best_person,
)

# ---------------------------------------------------------------------------
# PersonBox
# ---------------------------------------------------------------------------


class TestPersonBox:
    """Test PersonBox dataclass properties."""

    def test_area_and_dimensions(self) -> None:
        """Should compute width, height, area, centre correctly."""
        box = PersonBox(x1=10.0, y1=20.0, x2=110.0, y2=220.0, score=0.9)
        assert box.width == 100.0
        assert box.height == 200.0
        assert box.area == 20000.0
        assert box.cx == 60.0
        assert box.cy == 120.0
        assert box.size == 200.0

    def test_frozen(self) -> None:
        """PersonBox should be immutable."""
        box = PersonBox(x1=0.0, y1=0.0, x2=10.0, y2=10.0, score=0.5)
        with pytest.raises(AttributeError):
            box.score = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# letterbox_resize
# ---------------------------------------------------------------------------


class TestLetterboxResize:
    """Test letterbox resize helper."""

    def test_output_is_square(self) -> None:
        """Should produce target_size × target_size output."""
        frame = np.zeros((200, 300, 3), dtype=np.uint8)
        padded, scale, offset = letterbox_resize(frame, target_size=320)
        assert padded.shape == (320, 320, 3)
        assert scale > 0

    def test_preserves_content_in_top_left(self) -> None:
        """Resized content should appear in the top-left corner."""
        frame = np.full((100, 100, 3), 255, dtype=np.uint8)
        padded, scale, _ = letterbox_resize(frame, target_size=320)
        # Scale should be 320/100 = 3.2, but limited by min.
        # For a square input, scale = 320/100 = 3.2.
        new_dim = int(100 * scale)
        assert new_dim == 320
        # The entire output should be the frame content (no padding needed).
        assert padded[0, 0, 0] == 255

    def test_handles_empty_frame(self) -> None:
        """Should handle zero-size frame without crashing."""
        frame = np.zeros((0, 0, 3), dtype=np.uint8)
        padded, _, _ = letterbox_resize(frame, target_size=320)
        assert padded.shape == (320, 320, 3)


# ---------------------------------------------------------------------------
# preprocess_detector_frame
# ---------------------------------------------------------------------------


class TestPreprocessDetectorFrame:
    """Test detector preprocessing."""

    def test_output_shape(self) -> None:
        """Should produce (1, 3, 320, 320) float32 NCHW."""
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        blob = preprocess_detector_frame(frame)
        assert blob.shape == (1, 3, 320, 320)
        assert blob.dtype == np.float32

    def test_normalization(self) -> None:
        """Should apply ImageNet normalization in BGR order."""
        # Uniform grey frame at mean value → should be ~0 after normalization.
        frame = np.full((320, 320, 3), 114, dtype=np.uint8)
        blob = preprocess_detector_frame(frame)
        # The padding region should be normalized with the mean/std.
        # Not exactly zero, but close to (114 - mean) / std for each channel.
        mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
        std = np.array([57.375, 57.12, 58.395], dtype=np.float32)
        expected = (114.0 - mean) / std
        for c in range(3):
            assert abs(blob[0, c, 0, 0] - expected[c]) < 0.01


# ---------------------------------------------------------------------------
# NMS and decode
# ---------------------------------------------------------------------------


class TestNMS:
    """Test the pure-numpy NMS implementation."""

    def test_no_overlap(self) -> None:
        """Non-overlapping boxes should all be kept."""
        from aimation_actor_core.infrastructure.ai_models.detectors import _nms

        boxes = np.array(
            [[0, 0, 10, 10], [20, 20, 30, 30], [40, 40, 50, 50]], dtype=np.float32
        )
        scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
        keep = _nms(boxes, scores, iou_threshold=0.5)
        assert sorted(keep) == [0, 1, 2]

    def test_full_overlap_suppresses(self) -> None:
        """Identical boxes should suppress all but the highest score."""
        from aimation_actor_core.infrastructure.ai_models.detectors import _nms

        boxes = np.array(
            [[0, 0, 10, 10], [0, 0, 10, 10], [0, 0, 10, 10]], dtype=np.float32
        )
        scores = np.array([0.5, 0.9, 0.7], dtype=np.float32)
        keep = _nms(boxes, scores, iou_threshold=0.5)
        assert len(keep) == 1
        assert keep[0] == 1  # highest score kept

    def test_empty_input(self) -> None:
        """Should handle empty boxes."""
        from aimation_actor_core.infrastructure.ai_models.detectors import _nms

        keep = _nms(np.zeros((0, 4)), np.zeros(0), 0.5)
        assert keep == []


class TestDecodePersonDetections:
    """Test decode_person_detections pure function."""

    def test_filters_person_class_and_score(self) -> None:
        """Should keep only person class (0) above score threshold."""
        dets = np.array(
            [
                [10, 10, 50, 50, 0.9],  # person, high score → keep
                [20, 20, 60, 60, 0.1],  # person, low score → drop
                [30, 30, 70, 70, 0.8],  # class 1 (cat) → drop
            ],
            dtype=np.float32,
        )
        labels = np.array([0, 0, 1], dtype=np.int64)
        boxes = decode_person_detections(dets, labels, score_threshold=0.3)
        assert len(boxes) == 1
        assert boxes[0].score == pytest.approx(0.9)

    def test_empty_when_no_persons(self) -> None:
        """Should return empty when no person detections pass threshold."""
        dets = np.array(
            [[10, 10, 50, 50, 0.1], [20, 20, 60, 60, 0.05]], dtype=np.float32
        )
        labels = np.array([0, 0], dtype=np.int64)
        boxes = decode_person_detections(dets, labels, score_threshold=0.3)
        assert boxes == []


# ---------------------------------------------------------------------------
# select_best_person
# ---------------------------------------------------------------------------


class TestSelectBestPerson:
    """Test select_best_person helper."""

    def test_returns_none_for_empty(self) -> None:
        """Should return None for empty list."""
        assert select_best_person([]) is None

    def test_picks_highest_area_times_score(self) -> None:
        """Should pick the box with highest area × score."""
        small_high = PersonBox(x1=0, y1=0, x2=10, y2=10, score=1.0)  # area=100
        large_low = PersonBox(x1=0, y1=0, x2=100, y2=100, score=0.3)  # area=10000
        best = select_best_person([small_high, large_low])
        assert best is large_low  # 10000×0.3 = 3000 > 100×1.0 = 100
