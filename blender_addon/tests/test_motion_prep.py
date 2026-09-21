"""Tests for NeutralMotion preparation (bone map + keyframe payload)."""

from __future__ import annotations

import json
import pathlib

import pytest

from blender_addon.core.motion_prep import bone_map_for_skeleton, keyframe_payload

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def motion_doc() -> dict[str, object]:
    with open(FIXTURES / "small_motion.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_bone_map_identity(motion_doc: dict[str, object]) -> None:
    skeleton = motion_doc["skeleton"]
    mapping = bone_map_for_skeleton(skeleton)
    assert mapping == {"Root": "Root", "Hips": "Hips", "Spine": "Spine"}


def test_bone_map_rejects_non_dict(motion_doc: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="object"):
        bone_map_for_skeleton("Root")


def test_bone_map_rejects_empty_bones(motion_doc: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        bone_map_for_skeleton({"bones": {}})


def test_bone_map_rejects_name_key_mismatch(motion_doc: dict[str, object]) -> None:
    skeleton = motion_doc["skeleton"]
    skeleton["bones"]["Hips"]["name"] = "Pelvis"
    with pytest.raises(ValueError, match="does not match"):
        bone_map_for_skeleton(skeleton)


def test_bone_map_rejects_unknown_parent(motion_doc: dict[str, object]) -> None:
    skeleton = motion_doc["skeleton"]
    skeleton["bones"]["Spine"]["parent"] = "Ghost"
    with pytest.raises(ValueError, match="unknown parent"):
        bone_map_for_skeleton(skeleton)


def test_bone_map_rejects_self_parent(motion_doc: dict[str, object]) -> None:
    skeleton = motion_doc["skeleton"]
    skeleton["bones"]["Spine"]["parent"] = "Spine"
    with pytest.raises(ValueError, match="own parent"):
        bone_map_for_skeleton(skeleton)


def test_keyframe_payload_shape(motion_doc: dict[str, object]) -> None:
    payload = keyframe_payload(motion_doc)
    assert payload["meta"] == {
        "version": "0.3",
        "fps": 24.0,
        "units": "cm",
        "up_axis": "Y",
    }
    frames = payload["frames"]
    assert [frame["frame"] for frame in frames] == [1, 2]
    assert frames[0]["time"] == pytest.approx(1 / 24)
    assert frames[1]["time"] == pytest.approx(2 / 24)
    first = frames[0]["bones"]
    assert first["Root"]["translation"] == [0.0, 0.0, 0.0]  # omitted -> zeros
    assert first["Root"]["scale"] == [1.0, 1.0, 1.0]  # omitted -> identity
    assert first["Hips"]["rotation"] == pytest.approx([0.92388, 0.0, 0.0, -0.382683])
    second = frames[1]["bones"]
    assert second["Spine"]["scale"] == [1.0, 1.0, 1.0]
    assert len(first.keys()) == 3  # all three bones present


def test_keyframe_payload_rejects_unknown_bone(motion_doc: dict[str, object]) -> None:
    motion_doc["frames"][0]["pose"]["transforms"]["GhostBone"] = {
        "rotation": [1.0, 0.0, 0.0, 0.0]
    }
    with pytest.raises(ValueError, match="unknown bone"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_rejects_duplicate_frames(motion_doc: dict[str, object]) -> None:
    motion_doc["frames"][1]["frame"] = 1
    with pytest.raises(ValueError, match="duplicate frame"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_rejects_zero_frame(motion_doc: dict[str, object]) -> None:
    motion_doc["frames"][0]["frame"] = 0
    with pytest.raises(ValueError, match=">= 1"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_rejects_bad_rotation_length(
    motion_doc: dict[str, object],
) -> None:
    motion_doc["frames"][0]["pose"]["transforms"]["Root"]["rotation"] = [1.0, 0.0]
    with pytest.raises(ValueError, match="exactly 4"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_rejects_non_numeric_value(
    motion_doc: dict[str, object],
) -> None:
    motion_doc["frames"][0]["pose"]["transforms"]["Root"]["rotation"] = [
        1.0,
        0.0,
        0.0,
        "zero",
    ]
    with pytest.raises(ValueError, match="non-number"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_rejects_missing_pose(motion_doc: dict[str, object]) -> None:
    del motion_doc["frames"][0]["pose"]
    with pytest.raises(ValueError, match="'pose'"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_explicit_time_is_kept(motion_doc: dict[str, object]) -> None:
    motion_doc["frames"][0]["time"] = 5.0
    payload = keyframe_payload(motion_doc)
    assert payload["frames"][0]["time"] == 5.0


def test_keyframe_payload_rejects_bad_fps(motion_doc: dict[str, object]) -> None:
    motion_doc["meta"]["fps"] = -4
    with pytest.raises(ValueError, match="positive"):
        keyframe_payload(motion_doc)


def test_keyframe_payload_non_dict_document() -> None:
    with pytest.raises(ValueError, match="object"):
        keyframe_payload(["not", "a", "doc"])


def test_keyframe_payload_missing_frames(motion_doc: dict[str, object]) -> None:
    del motion_doc["frames"]
    with pytest.raises(ValueError, match="list"):
        keyframe_payload(motion_doc)