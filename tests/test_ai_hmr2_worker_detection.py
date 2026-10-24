"""Tests for the worker's automatic person-detection box (M8, S7).

The HMR2 worker estimates root depth from ``box_size`` and the weak-perspective
scale, so the full-frame box it used to hardcode made depth collapse to a
near-constant. These tests pin the replacement contract: the worker resolves a
detected person box per frame (highest-scoring, largest person), expands it by
a margin around its center without moving that center, clamps to the image,
and honestly falls back to the full-frame box when no detector is usable —
the historical behavior, never a fabricated trajectory (S4).

The pure stdlib helpers are exercised directly; the torch/torchvision calls
stay behind the ``detector`` callable seam so no test needs the engine stack.
"""

from __future__ import annotations

import pytest

from aimation_actor.adapters.ai.hmr2_worker import (
    FULL_FRAME_DETECTOR,
    _box_with_margin,
    _resolve_request_box,
    detect_person_box,
    pick_best_person,
)

FALLBACK = [0.0, 0.0, 1920.0, 1080.0]


# -- pick_best_person ---------------------------------------------------------- #


def test_pick_best_person_takes_the_largest_qualifying_person() -> None:
    boxes = [(10.0, 10.0, 30.0, 70.0), (200.0, 5.0, 400.0, 605.0), (500.0, 0.0, 550.0, 400.0)]
    scores = [0.9, 0.99, 0.7]
    labels = [1, 1, 0]  # the third box is not a person

    assert pick_best_person(boxes, scores, labels) == list(boxes[1])


def test_pick_best_person_breaks_ties_by_area() -> None:
    small = (0.0, 0.0, 100.0, 200.0)
    large = (0.0, 0.0, 600.0, 900.0)

    assert pick_best_person([small, large], [0.9, 0.9], [1, 1]) == list(large)


def test_pick_best_person_rejects_low_scores() -> None:
    assert pick_best_person([(0.0, 0.0, 500.0, 500.0)], [0.3], [1]) is None


def test_pick_best_person_handles_empty_candidates() -> None:
    assert pick_best_person([], [], []) is None


# -- _box_with_margin ----------------------------------------------------------- #


def test_margin_expands_around_the_center_and_clamps_to_the_image() -> None:
    box = _box_with_margin([100.0, 200.0, 300.0, 800.0], (1920, 1080), margin=1.2)

    center_x = (100.0 + 300.0) / 2
    center_y = (200.0 + 800.0) / 2
    assert (box[0] + box[2]) / 2 == pytest.approx(center_x)
    assert (box[1] + box[3]) / 2 == pytest.approx(center_y)
    assert box[2] - box[0] == pytest.approx(200.0 * 1.2)
    assert box[3] - box[1] == pytest.approx(600.0 * 1.2)
    assert box[0] >= 0.0 and box[1] >= 0.0
    assert box[2] <= 1920.0 and box[3] <= 1080.0


def test_margin_clamping_keeps_the_box_inside_the_image() -> None:
    box = _box_with_margin([5.0, 5.0, 605.0, 1075.0], (1920, 1080), margin=1.2)

    assert box[0] == 0.0 and box[1] == 0.0
    assert box[2] <= 1920.0 and box[3] <= 1080.0
    assert box[2] > box[0] and box[3] > box[1]


# -- detect_person_box (fake detector seam) ------------------------------------- #


class _FakeDetector:
    """Stands in for the torch model: called with the image, returns the
    torchvision batch-of-one list of dicts."""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def __call__(self, image):
        if self._error is not None:
            raise self._error
        return [self._result]


def test_detect_person_box_filters_labels_scores_and_rejects_degenerate_boxes() -> None:
    image = object()
    detector = _FakeDetector(
        {
            "boxes": [[0.0, 0.0, 0.0, 0.0], [10.0, 10.0, 10.0, 900.0], [5.0, 5.0, 605.0, 905.0]],
            "scores": [0.99, 0.99, 0.95],
            "labels": [1, 0, 1],
        }
    )

    found = detect_person_box(detector, image)

    # the zero-area box is degenerate, the second is not a person: the wide
    # person wins even with a lower score than the rejected higher ones.
    assert found == [5.0, 5.0, 605.0, 905.0]


def test_detect_person_box_reports_no_person_and_detector_errors_as_none() -> None:
    image = object()
    empty = _FakeDetector({"boxes": [], "scores": [], "labels": []})
    broken = _FakeDetector(error=RuntimeError("no cuda"))

    assert detect_person_box(empty, image) is None
    assert detect_person_box(broken, image) is None
    assert detect_person_box(None, image) is None


# -- _resolve_request_box -------------------------------------------------------- #


def test_resolve_request_box_uses_the_margined_detection() -> None:
    detector = _FakeDetector(
        {"boxes": [[100.0, 200.0, 300.0, 800.0]], "scores": [0.99], "labels": [1]}
    )

    box, name = _resolve_request_box(detector, object(), (1920, 1080), FALLBACK, margin=1.2)

    assert name == "fasterrcnn_mobilenet_v3_large_320_fpn"
    assert box[2] - box[0] == pytest.approx(240.0)
    assert box[3] - box[1] == pytest.approx(720.0)


def test_resolve_request_box_falls_back_to_the_full_frame_box() -> None:
    for detector in (None, _FakeDetector({"boxes": [], "scores": [], "labels": []})):
        box, name = _resolve_request_box(detector, object(), (1920, 1080), FALLBACK)

        assert box == FALLBACK
        assert name == FULL_FRAME_DETECTOR
