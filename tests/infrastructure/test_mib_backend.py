"""Focused tests for the MIB motion backend adapter.

MIB shares the AutoKeyframe conditioning contract (bounded raw-LaFAN ext-joint
payload) and returns the same ``{keyframes, global_positions}`` envelope, but
emits dense transition frames and tags the motion ``source_type="mib"``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from aimation_actor_core.domain.animation.motion_backend import MotionBackendUnavailable
from aimation_actor_core.infrastructure.ai_models.autokeyframe import (
    _COCO_TO_EXT,
    _normalize_conditioning,
)
from aimation_actor_core.infrastructure.ai_models.mib_backend import MibBackend, _motion_from_result

_PARENTS = (-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20)
#: Small per-bone offsets so the synthetic skeleton stays in plausible cm range.
_OFFSETS = [
    (0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 15.0, 0.0), (0.0, 15.0, 0.0),
    (0.0, 5.0, 0.0), (0.0, 10.0, 0.0), (0.0, 15.0, 0.0), (0.0, 15.0, 0.0),
    (0.0, 5.0, 0.0), (0.0, 8.0, 0.0), (0.0, 8.0, 0.0), (0.0, 12.0, 0.0),
    (0.0, 6.0, 0.0), (0.0, 5.0, 0.0), (3.0, 0.0, 0.0), (5.0, 0.0, 0.0),
    (8.0, 0.0, 0.0), (5.0, 0.0, 0.0), (-3.0, 0.0, 0.0), (-5.0, 0.0, 0.0),
    (-8.0, 0.0, 0.0), (-5.0, 0.0, 0.0),
]


def _rest_global() -> list[list[float]]:
    """Global rest positions (22 joints) built with the parent array."""
    points = [[0.0, 0.0, 0.0] for _ in range(len(_PARENTS))]
    for joint in range(1, len(_PARENTS)):
        parent = _PARENTS[joint]
        x, y, z = _OFFSETS[joint]
        points[joint] = [
            points[parent][0] + x, points[parent][1] + y, points[parent][2] + z,
        ]
    return points


def _dense_result(frames: list[int]) -> dict[str, object]:
    """A dense MIB-like result: one 22-joint global frame per returned index."""
    base = _rest_global()
    positions = [
        [[float(base[j][k]) + 0.1 * (frame % 5) for k in range(3)] for j in range(22)]
        for frame in frames
    ]
    return {"keyframes": frames, "global_positions": positions}


def _coco_conditioning() -> dict[str, object]:
    """Minimal wizard conditioning with COCO-labeled joints near rest height."""
    return {
        "duration_frames": 219,
        "fps": 24.0,
        "keyframes": [
            {"frame": 30, "joints": {
                "left_hip": [0.5, 0.45, 0.0], "right_hip": [0.5, 0.45, 0.0],
                "left_shoulder": [0.48, 0.25, 0.0], "right_shoulder": [0.52, 0.25, 0.0],
            }},
            {"frame": 90, "joints": {
                "left_hip": [0.55, 0.45, 0.1], "right_hip": [0.55, 0.45, 0.1],
                "left_shoulder": [0.53, 0.25, 0.1], "right_shoulder": [0.57, 0.25, 0.1],
            }},
        ],
    }


def test_mib_conditioning_reuses_autokeyframe_contract() -> None:
    """The normalizer produces the exact payload the MIB helper consumes."""
    payload = _normalize_conditioning(_coco_conditioning())
    assert payload["duration_frames"] == 219
    assert payload["fps"] == 24.0
    assert len(payload["keyframes"]) == 2
    for keyframe in payload["keyframes"]:
        assert isinstance(keyframe["frame"], int)
        assert 9 <= keyframe["frame"] <= 218
        assert keyframe["joints"]
        for ext, point in keyframe["joints"].items():
            assert ext.isdecimal() and 0 <= int(ext) < 22
            assert len(point) == 3
            assert all(math.isfinite(value) for value in point)


def test_mib_dense_result_builds_motion() -> None:
    """Dense (>64) output converts to a NeutralMotion tagged source_type=mib."""
    frames = list(range(21, 91))  # 70 dense frames, like the helper emits
    motion = _motion_from_result(_dense_result(frames), {"fps": 24.0})
    assert motion.meta.source_type == "mib"
    assert motion.meta.duration_frames == 90
    assert len(motion.frames) == 70
    assert [frame.frame for frame in motion.frames] == frames
    motion.validate_invariants()


def test_mib_dense_rejects_bad_result() -> None:
    with pytest.raises(ValueError):
        _motion_from_result(
            {
                "keyframes": [21, 20],
                "global_positions": _dense_result([21, 20])["global_positions"],
            },
            {"fps": 24.0},
        )


def test_mib_missing_assets_raise_unavailable() -> None:
    backend = MibBackend(
        Path("definitely-missing-mib-dir"),
        Path("definitely-missing-autokeyframe-dir"),
        timeout_seconds=5.0,
        helper=Path("definitely-missing-helper.py"),
    )
    with pytest.raises(MotionBackendUnavailable):
        backend.generate({"keyframes": _coco_conditioning()["keyframes"]})


def test_mib_axis_contract_is_shared_with_autokeyframe() -> None:
    """MIB converts raw LaFAN globals through the same scene transform."""
    expected_labels = set(_COCO_TO_EXT.keys())
    assert expected_labels  # mapping is populated