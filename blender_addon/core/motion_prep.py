"""NeutralMotion -> Blender-bake-ready preparation (bpy-free).

Consumes the NeutralMotion JSON shape produced by the Core
(``aimation_actor_core/domain/animation/neutral_motion.py``): ``meta`` /
``skeleton`` / ``frames`` / ``contacts`` / ``keyposes`` / ``tracking``, where
each frame pose holds per-bone LOCAL transforms with w-first unit quaternions
and translations/scales in the document's units (cm).

All functions here are pure and bpy-free so they are testable with plain
pytest in the repo venv.
"""

from __future__ import annotations

from typing import cast


def bone_map_for_skeleton(skeleton: object) -> dict[str, str]:
    """Return the neutral->armature bone name map (identity for v0.1).

    The neutral skeleton and the shadow armature share names in this slice,
    so the map is the identity. The validation still matters: it catches
    malformed skeleton documents before any Blender datablock is touched.

    Args:
        skeleton: The ``motion_doc["skeleton"]`` object.

    Returns:
        Mapping from neutral bone name to armature bone name.

    Raises:
        ValueError: On malformed skeletons (missing/invalid ``bones`` or
            bone names, unknown parents, name/key mismatches).
    """
    if not isinstance(skeleton, dict):
        raise ValueError("motion_doc['skeleton'] must be an object")
    bones = skeleton.get("bones")
    if not isinstance(bones, dict) or not bones:
        raise ValueError("skeleton.bones must be a non-empty object")

    mapping: dict[str, str] = {}
    for key, value in bones.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("skeleton bone keys must be non-empty strings")
        if not isinstance(value, dict):
            raise ValueError(f"skeleton bone {key!r} must be an object")
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"skeleton bone {key!r} is missing a valid 'name'")
        if name != key:
            raise ValueError(f"skeleton bone name {name!r} does not match its key {key!r}")
        parent = value.get("parent")
        if parent is not None:
            if not isinstance(parent, str) or not parent:
                raise ValueError(f"skeleton bone {key!r} has an invalid parent {parent!r}")
            if parent not in bones:
                raise ValueError(f"skeleton bone {key!r} has unknown parent {parent!r}")
            if parent == key:
                raise ValueError(f"skeleton bone {key!r} cannot be its own parent")
        mapping[key] = name
    return mapping


def keyframe_payload(motion_doc: object) -> dict[str, object]:
    """Prepare a NeutralMotion document for baking in Blender.

    Returns:
        A bake-ready payload::

            {
              "meta": {"version", "fps", "units", "up_axis"},
              "frames": [
                {
                  "frame": int,                    # 1-based doc frame number
                  "time": float,                   # seconds (frame / fps when absent)
                  "bones": {
                    "<bone>": {
                      "rotation": [w, x, y, z],    # w-first local quaternion
                      "translation": [x, y, z],    # doc units (cm)
                      "scale": [x, y, z],
                    },
                  },
                },
              ],
            }

    Raises:
        ValueError: On malformed documents (missing meta/skeleton/frames,
            invalid frame/pose/transform structure, unknown bones).
    """
    if not isinstance(motion_doc, dict):
        raise ValueError("motion_doc must be an object")

    skeleton = motion_doc.get("skeleton")
    bone_map = bone_map_for_skeleton(skeleton)  # validates the skeleton too

    meta_payload = _meta_payload(motion_doc.get("meta"))
    fps = cast(float, meta_payload["fps"])

    frames = motion_doc.get("frames")
    if not isinstance(frames, list):
        raise ValueError("motion_doc['frames'] must be a list")

    prepared: list[dict[str, object]] = []
    seen: set[int] = set()
    for entry in frames:
        if not isinstance(entry, dict):
            raise ValueError("each frame must be an object")
        number = entry.get("frame")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ValueError(f"frame number must be an int >= 1, got {number!r}")
        if number in seen:
            raise ValueError(f"duplicate frame number {number}")
        seen.add(number)

        time_value = entry.get("time")
        if time_value is None:
            time_value = number / fps
        if (
            not isinstance(time_value, (int, float))
            or isinstance(time_value, bool)
            or time_value < 0
        ):
            raise ValueError(f"frame {number}: time must be a non-negative number")

        pose = entry.get("pose")
        if not isinstance(pose, dict):
            raise ValueError(f"frame {number}: 'pose' must be an object")
        transforms = pose.get("transforms")
        if not isinstance(transforms, dict):
            raise ValueError(f"frame {number}: pose.transforms must be an object")

        bones_payload: dict[str, object] = {}
        for bone_name, raw in transforms.items():
            if not isinstance(bone_name, str):
                raise ValueError(f"frame {number}: transform key must be a string")
            if bone_name not in bone_map:
                raise ValueError(f"frame {number}: transform for unknown bone {bone_name!r}")
            if not isinstance(raw, dict):
                raise ValueError(f"frame {number}: transform for {bone_name!r} must be an object")
            bones_payload[bone_name] = _parse_transform(raw, number, bone_name)

        prepared.append({"frame": number, "time": float(time_value), "bones": bones_payload})

    return {"meta": meta_payload, "frames": prepared}


def _meta_payload(meta: object) -> dict[str, object]:
    """Extract and validate the meta fields the baker needs."""
    if meta is None:
        return {"version": "0.3", "fps": 24.0, "units": "cm", "up_axis": "Y"}
    if not isinstance(meta, dict):
        raise ValueError("motion_doc['meta'] must be an object")
    fps = meta.get("fps", 24.0)
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        raise ValueError("meta.fps must be a positive number")
    return {
        "version": meta.get("version", "0.3"),
        "fps": float(fps),
        "units": meta.get("units", "cm"),
        "up_axis": meta.get("up_axis", "Y"),
    }


def _parse_transform(raw: dict[str, object], frame: int, bone: str) -> dict[str, object]:
    """Validate one bone transform and normalize it to lists of floats."""
    rotation = _number_tuple(raw.get("rotation"), 4, f"frame {frame} bone {bone!r}: rotation")
    translation = _number_tuple(
        raw.get("translation", (0.0, 0.0, 0.0)), 3, f"frame {frame} bone {bone!r}: translation"
    )
    scale = _number_tuple(
        raw.get("scale", (1.0, 1.0, 1.0)),
        3,
        f"frame {frame} bone {bone!r}: scale",
    )
    return {
        "rotation": list(rotation),
        "translation": list(translation),
        "scale": list(scale),
    }


def _number_tuple(value: object, length: int, where: str) -> tuple[float, ...]:
    """Coerce ``value`` to a tuple of ``length`` finite numbers."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{where} must be a sequence of {length} numbers")
    if len(value) != length:
        raise ValueError(f"{where} must have exactly {length} numbers, got {len(value)}")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{where} contains a non-number: {item!r}")
        result.append(float(item))
    return tuple(result)