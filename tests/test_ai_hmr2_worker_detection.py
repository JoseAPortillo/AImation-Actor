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

from types import SimpleNamespace

import pytest

from aimation_actor.adapters.ai.hmr2_worker import (
    FULL_FRAME_DETECTOR,
    _box_with_margin,
    _resolve_request_box,
    detect_person_box,
    detect_person_keypoints,
    pick_best_person,
    refine_end_effectors_from_pose_landmarks,
    refine_projected_joints,
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


def test_keypoint_refinement_replaces_confident_coco_joints_only() -> None:
    projected = {
        "L_Hip": (10.0, 10.0),
        "R_Hip": (20.0, 20.0),
        "L_Knee": (30.0, 30.0),
        "R_Knee": (40.0, 40.0),
        "L_Ankle": (50.0, 50.0),
        "R_Ankle": (60.0, 60.0),
        "L_Shoulder": (70.0, 70.0),
        "R_Shoulder": (80.0, 80.0),
        "L_Elbow": (90.0, 90.0),
        "R_Elbow": (100.0, 100.0),
        "L_Wrist": (110.0, 110.0),
        "R_Wrist": (120.0, 120.0),
        "Head": (130.0, 130.0),
    }
    keypoints = [[float(index), float(index + 1)] for index in range(17)]
    scores = [0.95] * 17
    scores[8] = 0.1  # right elbow: keep HMR2 when COCO is uncertain

    refined = refine_projected_joints(projected, keypoints, scores)

    assert refined["L_Shoulder"] == (5.0, 6.0)
    assert refined["R_Shoulder"] == (6.0, 7.0)
    assert refined["L_Elbow"] == (7.0, 8.0)
    assert refined["R_Elbow"] == (100.0, 100.0)
    assert refined["L_Wrist"] == (9.0, 10.0)
    assert refined["R_Wrist"] == (10.0, 11.0)
    assert refined["L_Hip"] == (11.0, 12.0)
    assert refined["R_Hip"] == (12.0, 13.0)
    assert refined["L_Knee"] == (13.0, 14.0)
    assert refined["R_Knee"] == (14.0, 15.0)
    assert refined["L_Ankle"] == (15.0, 16.0)
    assert refined["R_Ankle"] == (16.0, 17.0)
    assert refined["Head"] == (130.0, 130.0)


def test_keypoint_refinement_updates_pelvis_from_confident_hips() -> None:
    projected = {"Pelvis": (0.0, 0.0), "L_Hip": (0.0, 0.0), "R_Hip": (0.0, 0.0)}
    keypoints = [[0.0, 0.0]] * 17
    keypoints[11] = [10.0, 20.0]
    keypoints[12] = [30.0, 40.0]
    scores = [0.0] * 17
    scores[11] = scores[12] = 0.95

    refined = refine_projected_joints(projected, keypoints, scores)

    assert refined["L_Hip"] == (10.0, 20.0)
    assert refined["R_Hip"] == (30.0, 40.0)
    assert refined["Pelvis"] == (20.0, 30.0)


def test_keypoint_refinement_rebuilds_the_torso_from_confident_shoulders() -> None:
    projected = {
        "Pelvis": (20.0, 30.0),
        "L_Shoulder": (0.0, 0.0),
        "R_Shoulder": (0.0, 0.0),
        "Neck": (0.0, 0.0),
        "Spine_1": (0.0, 0.0),
        "Spine_2": (0.0, 0.0),
        "Spine_3": (0.0, 0.0),
        "L_Collar": (0.0, 0.0),
        "R_Collar": (0.0, 0.0),
    }
    keypoints = [[0.0, 0.0]] * 17
    keypoints[5] = [10.0, 10.0]
    keypoints[6] = [30.0, 10.0]
    scores = [0.0] * 17
    scores[5] = scores[6] = 0.95

    refined = refine_projected_joints(projected, keypoints, scores)

    assert refined["Neck"] == (20.0, 10.0)
    assert refined["Spine_1"] == (20.0, 25.0)
    assert refined["Spine_2"] == (20.0, 20.0)
    assert refined["Spine_3"] == (20.0, 15.0)
    assert refined["L_Collar"] == (15.0, 10.0)
    assert refined["R_Collar"] == (25.0, 10.0)


def test_keypoint_refinement_extrapolates_hands_and_feet_from_observed_limbs() -> None:
    projected = {
        "L_Elbow": (10.0, 10.0),
        "L_Wrist": (20.0, 20.0),
        "L_Hand": (0.0, 0.0),
        "L_Knee": (30.0, 30.0),
        "L_Ankle": (40.0, 40.0),
        "L_Foot": (0.0, 0.0),
    }
    keypoints = [[0.0, 0.0]] * 17
    keypoints[7] = [10.0, 10.0]
    keypoints[9] = [20.0, 20.0]
    keypoints[13] = [30.0, 30.0]
    keypoints[15] = [40.0, 40.0]
    scores = [0.0] * 17
    scores[7] = scores[9] = scores[13] = scores[15] = 0.95

    refined = refine_projected_joints(projected, keypoints, scores)

    assert refined["L_Hand"] == (23.5, 23.5)
    assert refined["L_Foot"] == (42.5, 42.5)


def test_pose_landmarks_use_real_hand_and_toe_observations() -> None:
    landmarks = [SimpleNamespace(x=0.0, y=0.0, visibility=0.0) for _ in range(33)]
    landmarks[19] = SimpleNamespace(x=0.20, y=0.30, visibility=0.9)  # L index
    landmarks[17] = SimpleNamespace(x=0.24, y=0.34, visibility=0.9)  # L pinky
    landmarks[20] = SimpleNamespace(x=0.70, y=0.30, visibility=0.9)  # R index
    landmarks[18] = SimpleNamespace(x=0.74, y=0.34, visibility=0.9)  # R pinky
    landmarks[31] = SimpleNamespace(x=0.25, y=0.90, visibility=0.9)  # L toe
    landmarks[32] = SimpleNamespace(x=0.75, y=0.90, visibility=0.9)  # R toe

    refined = refine_end_effectors_from_pose_landmarks(
        {"L_Hand": (0.0, 0.0), "R_Hand": (0.0, 0.0), "L_Foot": (0.0, 0.0)},
        landmarks,
        1000,
        500,
    )

    assert refined["L_Hand"] == (220.0, 160.0)
    assert refined["R_Hand"] == (720.0, 160.0)
    assert refined["L_Foot"] == (250.0, 450.0)


def test_keypoint_detection_selects_the_person_overlapping_the_capture_box() -> None:
    keypoints = [[[float(index), float(index + 1)] for index in range(17)]] * 2
    detector = _FakeDetector(
        {
            "boxes": [[0.0, 0.0, 20.0, 20.0], [100.0, 100.0, 300.0, 500.0]],
            "scores": [0.99, 0.8],
            "labels": [1, 1],
            "keypoints": keypoints,
            "keypoints_scores": [[0.2] * 17, [0.9] * 17],
        }
    )

    found = detect_person_keypoints(detector, object(), [90.0, 90.0, 310.0, 510.0])

    assert found == (keypoints[1], [0.9] * 17)
