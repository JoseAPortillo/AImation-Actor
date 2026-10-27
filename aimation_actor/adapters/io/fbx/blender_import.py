"""Blender-side bridge: import an ``.fbx`` and dump its animation as JSON.

This script is **never imported** by the application; it runs inside Blender's
own Python::

    blender --background --factory-startup --python blender_import.py -- IN OUT

``IN`` is the ``.fbx`` to read and ``OUT`` the JSON file to write. The JSON holds
raw *armature-space* (i.e. FBX-space) values; the coordinate/unit conversion into
the domain belongs to the adapter, so it stays testable without Blender.

Layout of ``OUT``::

    {
      "fps": 24.0,
      "frame_start": 0, "frame_end": 42,
      "world_quaternion": [w, x, y, z],   # armature object rotation
      "world_scale": 0.01,                # armature object uniform scale
      "bones": [{"name", "parent", "rest_t": [x, y, z], "rest_q": [w, x, y, z]}],
      "keyframes": [{"frame": 15, "bones": {"Name": {"t": [...], "q": [...]}}}]
    }

``rest_t``/``t`` are parent-local translations; ``rest_q``/``q`` are parent-local
rotations (``q`` is absolute, i.e. it already includes the bind orientation).
"""

from __future__ import annotations

import json
import sys

import bpy

_ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _quat(value) -> list[float]:
    return [value.w, value.x, value.y, value.z]


def _vec(value) -> list[float]:
    return [value.x, value.y, value.z]


def _local_matrix(pose_bone):
    """The bone's transform relative to its parent, in armature space."""
    parent = pose_bone.parent
    if parent is None:
        return pose_bone.matrix.copy()
    return parent.matrix.inverted() @ pose_bone.matrix


def _rest_local_matrix(bone):
    """The bone's bind transform relative to its parent, in armature space."""
    parent = bone.parent
    if parent is None:
        return bone.matrix_local.copy()
    return parent.matrix_local.inverted() @ bone.matrix_local


def _iter_fcurves(action):
    """Yield the action's fcurves across Blender's legacy and slotted layouts."""
    layers = getattr(action, "layers", None)
    if layers is None:  # Blender < 4.4 legacy actions.
        yield from action.fcurves
        return
    for layer in layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                yield from channelbag.fcurves


def _keyed_frames(armature) -> list[int]:
    animation_data = armature.animation_data
    if animation_data is None or animation_data.action is None:
        return []
    frames: set[int] = set()
    for fcurve in _iter_fcurves(animation_data.action):
        for point in fcurve.keyframe_points:
            frames.add(round(point.co[0]))
    return sorted(frames)


def _snapshot(armature) -> dict[str, dict[str, list[float]]]:
    snapshot: dict[str, dict[str, list[float]]] = {}
    for pose_bone in armature.pose.bones:
        local = _local_matrix(pose_bone)
        snapshot[pose_bone.name] = {
            "t": _vec(local.to_translation()),
            "q": _quat(local.to_quaternion()),
        }
    return snapshot


def main(input_path: str, output_path: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # ``anim_offset=0`` keeps FBX times and Blender frames aligned 1:1.
    bpy.ops.import_scene.fbx(filepath=input_path, use_anim=True, anim_offset=0.0)

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise SystemExit(f"no armature found in {input_path!r}")
    armature = armatures[0]

    world = armature.matrix_world
    scene = bpy.context.scene

    payload = {
        "fps": scene.render.fps / scene.render.fps_base,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "world_quaternion": _quat(world.to_quaternion()),
        "world_scale": world.to_scale().x,
        "bones": [],
        "keyframes": [],
    }
    for bone in armature.data.bones:
        rest = _rest_local_matrix(bone)
        payload["bones"].append(
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "rest_t": _vec(rest.to_translation()),
                "rest_q": _quat(rest.to_quaternion()),
            }
        )

    for frame in _keyed_frames(armature):
        scene.frame_set(frame)
        payload["keyframes"].append({"frame": frame, "bones": _snapshot(armature)})

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


if __name__ == "__main__":
    if len(_ARGS) != 2:
        raise SystemExit("usage: ... -- INPUT.fbx OUTPUT.json")
    main(_ARGS[0], _ARGS[1])
