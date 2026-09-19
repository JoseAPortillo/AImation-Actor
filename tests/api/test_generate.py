"""Focused tests for the wizard generate response preview metadata."""

from aimation_actor_core.api.routers.generate import (
    DetectedKeypoint,
    GoldenPose,
    _build_preview_metadata,
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
