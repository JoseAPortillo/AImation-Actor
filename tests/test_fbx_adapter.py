"""Tests for the FBX adapter: writer, payload conversion, and Blender plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aimation_actor.adapters.io.fbx import binary, transform
from aimation_actor.adapters.io.fbx_adapter import (
    BlenderError,
    BlenderFbxAdapter,
    state_from_payload,
)
from aimation_actor.core.models import Quaternion, TimelineState, Vector3

_TOLERANCE = 1e-9
_WORLD_SCALE = 0.01  # Blender's metre world unit for a centimetre FBX.


def _same_quaternion(actual: Quaternion, expected: Quaternion) -> None:
    got = (actual.w, actual.x, actual.y, actual.z)
    want = (expected.w, expected.x, expected.y, expected.z)
    same = all(abs(a - b) <= _TOLERANCE for a, b in zip(got, want, strict=True))
    flipped = all(abs(a + b) <= _TOLERANCE for a, b in zip(got, want, strict=True))
    assert same or flipped, f"{got} != {want}"


def _fbx_tuple(vector: Vector3) -> list[float]:
    x, y, z = transform.to_fbx_vector(vector)
    return [x, y, z]


def _fbx_quaternion(quaternion: Quaternion) -> list[float]:
    value = transform.rotation_to_fbx(quaternion)
    return [value.w, value.x, value.y, value.z]


def _payload_for(state: TimelineState) -> dict:
    """The JSON Blender would emit for ``state`` (raw armature-space values)."""
    rest = {joint.name: joint.rest_translation for joint in state.skeleton.joints}

    bones = []
    for joint in state.skeleton.joints:
        bones.append(
            {
                "name": joint.name,
                "parent": joint.parent,
                "rest_t": _fbx_tuple(joint.rest_translation),
                "rest_q": [1.0, 0.0, 0.0, 0.0],
            }
        )

    keyframes = []
    for keyframe in state.keyframes:
        poses = {}
        for joint in state.skeleton.joints:
            pose = keyframe.pose.get(joint.name)
            rotation = pose.rotation if pose else Quaternion.identity()
            delta = pose.translation if pose else Vector3()
            base = rest[joint.name]
            total = Vector3(base.x + delta.x, base.y + delta.y, base.z + delta.z)
            poses[joint.name] = {"t": _fbx_tuple(total), "q": _fbx_quaternion(rotation)}
        keyframes.append({"frame": keyframe.frame, "bones": poses})

    rotation = transform.A_INV_Q
    return {
        "fps": state.fps,
        "frame_start": state.frame_start,
        "frame_end": state.frame_end,
        "world_quaternion": [rotation.w, rotation.x, rotation.y, rotation.z],
        "world_scale": _WORLD_SCALE,
        "bones": bones,
        "keyframes": keyframes,
    }


def test_save_writes_a_parseable_fbx(sample_state: TimelineState, workspace: Path) -> None:
    path = workspace / "out.fbx"
    BlenderFbxAdapter().save(sample_state, path)

    names = {node.name for node in binary.parse(path.read_bytes())}
    assert {"FBXHeaderExtension", "Objects", "Connections"} <= names


def test_payload_conversion_recovers_the_domain_timeline(sample_state: TimelineState) -> None:
    result = state_from_payload(_payload_for(sample_state))

    assert result.fps == pytest.approx(24.0)
    assert (result.frame_start, result.frame_end) == (15, 42)
    assert result.frames() == (15, 42)
    assert result.skeleton.names() == ("Main", "Pelvis", "Spine_1", "Spine_2", "Head")

    pelvis = next(joint for joint in result.skeleton.joints if joint.name == "Pelvis")
    bind = pelvis.rest_translation
    assert (bind.x, bind.y, bind.z) == pytest.approx((0.0, 0.0, 100.0))

    first, second = result.keyframes
    move = first.pose["Main"].translation
    assert (move.x, move.y, move.z) == pytest.approx((10.0, 0.0, 0.0))

    source = sample_state.keyframes[1].pose
    _same_quaternion(second.pose["Head"].rotation, source["Head"].rotation)
    _same_quaternion(second.pose["Spine_1"].rotation, source["Spine_1"].rotation)
    assert second.pose["Main"].translation.y == pytest.approx(5.0)


def test_state_from_payload_orders_joints_root_first(sample_state: TimelineState) -> None:
    payload = _payload_for(sample_state)
    payload["bones"] = list(reversed(payload["bones"]))

    names = state_from_payload(payload).skeleton.names()
    assert names == ("Main", "Pelvis", "Spine_1", "Spine_2", "Head")


def test_sparse_keys_override_blenders_default_scene_range(sample_state: TimelineState) -> None:
    payload = _payload_for(sample_state)
    payload["frame_start"], payload["frame_end"] = 1, 250  # Blender's defaults.

    result = state_from_payload(payload)

    assert (result.frame_start, result.frame_end) == (15, 42)


def test_load_runs_the_bridge_and_reads_its_json(
    monkeypatch: pytest.MonkeyPatch, sample_state: TimelineState, workspace: Path
) -> None:
    payload = _payload_for(sample_state)
    adapter = BlenderFbxAdapter(blender_executable="blender")

    def fake_bridge(_executable: str, _source: Path, output: Path) -> None:
        output.write_text(json.dumps(payload))

    monkeypatch.setattr(adapter, "_run_bridge", fake_bridge)

    result = adapter.load(workspace / "whatever.fbx")

    assert result.frames() == (15, 42)
    source = sample_state.keyframes[0].pose["Spine_1"].rotation
    _same_quaternion(result.keyframes[0].pose["Spine_1"].rotation, source)


def test_missing_blender_is_reported(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    monkeypatch.setattr("aimation_actor.adapters.io.fbx_adapter.shutil.which", lambda _name: None)
    monkeypatch.setattr("aimation_actor.adapters.io.fbx_adapter._DEFAULT_EXECUTABLES", ())
    monkeypatch.delenv("AIMATION_BLENDER", raising=False)

    with pytest.raises(BlenderError, match="Blender was not found"):
        BlenderFbxAdapter().load(workspace / "x.fbx")


def test_unusable_executable_is_reported(workspace: Path) -> None:
    adapter = BlenderFbxAdapter(blender_executable=str(workspace / "nope-blender"))
    with pytest.raises(BlenderError, match="could not run Blender"):
        adapter.load(workspace / "x.fbx")
