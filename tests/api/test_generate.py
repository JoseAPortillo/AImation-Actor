"""Focused tests for the wizard generate response preview metadata."""

import asyncio
from typing import Any

import pytest

from aimation_actor_core.api.routers.generate import (
    DetectedKeypoint,
    GenerateMotionRequest,
    GoldenPose,
    _build_preview_metadata,
    generate_motion,
)
from aimation_actor_core.domain.animation.motion_backend import MotionBackendUnavailable
from aimation_actor_core.infrastructure.ai_models.autokeyframe import (
    _motion_from_result,
    _normalize_conditioning,
    _scene_to_model_coordinates,
    _validate_authored_fidelity,
)


def _kp(label: str, x: float = 0.5, y: float = 0.5) -> DetectedKeypoint:
    return DetectedKeypoint(label=label, x=x, y=y, confidence=1.0)


def test_preview_omits_synthetic_joints_and_head_segments() -> None:
    preview = _build_preview_metadata([
        GoldenPose(
            frame=1,
            label="pose",
            detection=[_kp("nose"), _kp("left_shoulder"), _kp("right_shoulder")],
        )
    ])

    assert preview["joint_names"] == ["Head", "LShoulder", "RShoulder"]
    assert preview["bone_pairs"] == [{"parent": "LShoulder", "child": "RShoulder"}]
    assert all("Neck" not in pair.values() for pair in preview["bone_pairs"])


def test_preview_topology_includes_only_captured_connections() -> None:
    preview = _build_preview_metadata([
        GoldenPose(
            frame=7,
            label="off-origin",
            detection=[
                _kp("left_hip", 0.2, 0.7),
                _kp("right_hip", 0.8, 0.7),
                _kp("left_knee", 0.2, 0.9),
            ],
        )
    ])

    assert preview["joint_names"] == ["Hips", "LLeg", "LUpLeg", "RUpLeg"]
    assert preview["bone_pairs"] == [
        {"parent": "LUpLeg", "child": "RUpLeg"},
        {"parent": "LUpLeg", "child": "LLeg"},
    ]


def test_external_conditioning_maps_labels_to_numeric_joints_and_pads_frames() -> None:
    result = _normalize_conditioning({
        "fps": 24.0,
        "keyframes": [{"frame": 1, "joints": {
            "left_hip": [0.25, 0.25, 0.0], "right_hip": [0.75, 0.25, 0.0],
            "not_a_joint": [0.5, 0.5, 0.0],
        }}],
    })
    assert result["duration_frames"] == 219
    assert result["keyframes"] == [{
        "frame": 9,
        "joints": {
            "1": [-129.0, 0.0, -43.0],
            "5": [-129.0, 0.0, -129.0],
            "0": [-129.0, 0.0, -86.0],
        },
    }]


def test_scene_model_axis_transform_round_trips_without_rotation() -> None:
    scene = (12.0, 34.0, -56.0)
    model = _scene_to_model_coordinates(scene)

    assert model == [-34.0, -56.0, -12.0]
    assert (-model[2], -model[0], model[1]) == scene


def test_external_result_preserves_signed_left_right_and_up_axes() -> None:
    positions = [[[0.0, 0.0, 0.0] for _ in range(22)]]
    positions[0][0] = [0.0, 0.0, 0.0]
    positions[0][1] = [-100.0, 0.0, 20.0]  # scene: left hip, x=-20, y=100
    positions[0][5] = [-100.0, 0.0, -20.0]  # scene: right hip, x=20, y=100
    positions[0][9] = [-140.0, 0.0, 0.0]  # scene: torso is higher

    motion = _motion_from_result(
        {"keyframes": [9], "global_positions": positions}, {"fps": 24.0}
    )
    frame = motion.frames[0].pose.transforms

    assert frame["LUpLeg"].translation[0] < frame["RUpLeg"].translation[0]
    assert frame["Spine"].translation[1] > 0.0


def test_repeated_asymmetric_keyframes_do_not_accumulate_yaw() -> None:
    def frame(root_x: float) -> list[list[float]]:
        points = [[0.0, 0.0, 0.0] for _ in range(22)]
        points[0] = [0.0, 0.0, root_x]
        points[1] = [-100.0, 0.0, 20.0]
        points[5] = [-100.0, 0.0, -20.0]
        points[9] = [-140.0, 0.0, 0.0]
        return points

    def motion_for(count: int) -> object:
        keys = [9 + i * 20 for i in range(count)]
        return _motion_from_result(
            {"keyframes": keys, "global_positions": [frame(3.0)] * count},
            {"fps": 24.0},
        )

    two = motion_for(2)
    five = motion_for(5)
    for motion in (two, five):
        transforms = motion.frames[-1].pose.transforms
        assert transforms["LUpLeg"].translation[0] < transforms["RUpLeg"].translation[0]
        assert transforms["Spine"].translation[1] > 0.0
        assert transforms["Root"].translation == (-3.0, -0.0, 0.0)


def test_external_result_converts_proven_mapping_without_duplicate_bones() -> None:
    positions = [[[float(joint), float(joint), 0.0] for joint in range(22)] for _ in range(2)]
    motion = _motion_from_result(
        {"keyframes": [9, 218], "global_positions": positions},
        {"fps": 24.0},
    )
    motion.validate_invariants()
    transforms = motion.frames[0].pose.transforms
    assert set(transforms) == set(motion.skeleton.bones)
    assert transforms["Hips"].translation == (0.0, 0.0, 0.0)
    assert transforms["Root"].translation == (0.0, 0.0, 0.0)


def test_external_conditioning_rejects_oversized_keyframe_input() -> None:
    with pytest.raises(MotionBackendUnavailable, match="keyframe count"):
        _normalize_conditioning({"keyframes": [{"frame": 9, "joints": {}}] * 65})


def test_external_conditioning_rejects_oversized_joint_input() -> None:
    with pytest.raises(MotionBackendUnavailable, match="joint count"):
        _normalize_conditioning({
            "keyframes": [{"frame": 9, "joints": {f"joint_{i}": [0.0, 0.0, 0.0]
                                                    for i in range(23)}}],
        })


def _fidelity_conditioning(count: int) -> dict[str, Any]:
    labels = {
        "left_hip": [0.30, 0.70, 0.0],
        "right_hip": [0.70, 0.70, 0.0],
        "left_shoulder": [0.22, 0.30, 0.0],
        "right_shoulder": [0.78, 0.30, 0.0],
        "left_elbow": [0.12, 0.45, 0.0],
        "right_elbow": [0.88, 0.45, 0.0],
        "left_wrist": [0.08, 0.60, 0.0],
        "right_wrist": [0.92, 0.60, 0.0],
    }
    return {"keyframes": [
        {"frame": 10 + index * 20, "joints": labels.copy()}
        for index in range(count)
    ]}


def _fidelity_result(conditioning: dict[str, Any], arm_offset: float = 0.0) -> dict[str, Any]:
    keys = [max(9, min(218, int(item["frame"]))) for item in conditioning["keyframes"]]
    positions = []
    for item in conditioning["keyframes"]:
        points = [[0.0, 0.0, 0.0] for _ in range(22)]
        for label, point in item["joints"].items():
            ext = {"left_hip": 1, "right_hip": 5, "left_shoulder": 14,
                   "right_shoulder": 18, "left_elbow": 15, "right_elbow": 19,
                   "left_wrist": 16, "right_wrist": 20}[label]
            scene = (point[0] * 172.0, (1.0 - point[1]) * 172.0, point[2] * 172.0)
            if label == "left_wrist":
                scene = (scene[0] + arm_offset, scene[1], scene[2])
            points[ext] = _scene_to_model_coordinates(scene)
        positions.append(points)
    return {"keyframes": keys, "global_positions": positions}


@pytest.mark.parametrize("count", [2, 5])
def test_authored_fidelity_gate_accepts_near_matching_result(count: int) -> None:
    conditioning = _fidelity_conditioning(count)
    _validate_authored_fidelity(_fidelity_result(conditioning, arm_offset=5.0), conditioning)


@pytest.mark.parametrize("count", [2, 5])
def test_authored_fidelity_gate_rejects_cumulative_arm_rotation(count: int) -> None:
    conditioning = _fidelity_conditioning(count)
    with pytest.raises(MotionBackendUnavailable, match="fidelity"):
        _validate_authored_fidelity(_fidelity_result(conditioning, arm_offset=60.0), conditioning)


def test_bad_model_result_falls_back_with_sanitized_reason() -> None:
    conditioning = _fidelity_conditioning(2)

    class BadBackend:
        def generate(self, _: dict[str, object]) -> object:
            _validate_authored_fidelity(
                _fidelity_result(conditioning, arm_offset=60.0), conditioning
            )
            raise AssertionError("unreachable")

    request = GenerateMotionRequest(goldenPoses=[
        GoldenPose(
            frame=item["frame"],
            label="authored",
            detection=[DetectedKeypoint(label=label, x=point[0], y=point[1], confidence=1.0)
                       for label, point in item["joints"].items()],
        ) for item in conditioning["keyframes"]
    ])
    response = asyncio.run(generate_motion(request, BadBackend()))
    assert response["backend"] == "procedural"
    assert response["fallback_reason"] == "authored keyframe fidelity check failed"


def test_default_backend_stays_procedural_without_schema_mutation() -> None:
    response = asyncio.run(
        generate_motion(
            GenerateMotionRequest(goldenPoses=[GoldenPose(frame=1, label="start")]),
            None,
        )
    )
    assert response["backend"] == "procedural"
    assert {"meta", "skeleton", "frames", "contacts", "keyposes", "tracking"} <= response.keys()


def test_unavailable_optional_backend_falls_back_to_procedural() -> None:
    class UnavailableBackend:
        def generate(self, conditioning: dict[str, object]) -> object:
            raise MotionBackendUnavailable("not installed")

    response = asyncio.run(
        generate_motion(
            GenerateMotionRequest(goldenPoses=[GoldenPose(frame=1, label="start")]),
            UnavailableBackend(),  # type: ignore[arg-type]
        )
    )
    assert response["backend"] == "procedural"
