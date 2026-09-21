"""Bake a NeutralMotion into an armature Action (bpy glue).

v0.1 inserts pose values directly onto the armature's action fcurves —
deterministic and exact. This is equivalent to visual keying while the rig
has no constraints or drivers (the values written ARE the evaluated pose).
Constraint-aware ``nla.bake`` (spec §6/§11 parity note: Blender requires
visual keying for accuracy) is the v0.2+ path for retargeted/control rigs;
the interface already accepts ``use_visual_keying`` and raises loudly rather
than baking wrong values when a constrained rig asks for it.
"""

from __future__ import annotations

import bpy
import mathutils

DEFAULT_ACTION_NAME = "AImation_Motion"
ROTATION_PROP = "rotation_quaternion"
LOCATION_PROP = "location"
SCALE_PROP = "scale"


def bake_motion(
    armature_obj: bpy.types.Object,
    motion_doc: dict[str, object],
    keyframe_payload: dict[str, object],
    *,
    frame_start: int,
    frame_end: int,
    use_visual_keying: bool = True,
) -> bpy.types.Action:
    """Bake a prepared motion payload onto ``armature_obj`` and return the Action.

    Args:
        armature_obj: Target armature (must have pose bones matching the
            payload bone names).
        motion_doc: The original NeutralMotion document (kept for traceability
            and future metadata).
        keyframe_payload: Output of
            :func:`blender_addon.core.motion_prep.keyframe_payload` —
            per-frame bone transforms with w-first quaternions.
        frame_start: First scene frame to key (inclusive).
        frame_end: Last scene frame to key (inclusive).
        use_visual_keying: When True (default), verify the rig has no pose-bone
            constraints; the direct value insertion is then exact. A
            constrained rig raises ``NotImplementedError`` (the ``nla.bake``
            path is a v0.2 deliverable) instead of baking approximate keys.

    Returns:
        The action that was written (``bpy.data.actions["AImation_Motion"]``).

    Raises:
        TypeError: If ``armature_obj`` is not an armature.
        ValueError: If the frame range is inverted, or a payload frame lies
            outside the range.
    """
    if armature_obj.type != "ARMATURE":
        raise TypeError(f"{armature_obj.name} is not an armature")
    if frame_end < frame_start:
        raise ValueError("frame_end must be >= frame_start")
    del motion_doc  # traceability only in v0.1; consumed via the payload

    frames = keyframe_payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("keyframe_payload has no frames to bake")

    if use_visual_keying:
        _require_visual_keying_safe(armature_obj)

    action = _fresh_action(DEFAULT_ACTION_NAME)
    if armature_obj.animation_data is None:
        armature_obj.animation_data_create()
    armature_obj.animation_data.action = action

    for frame_data in frames:
        frame_number = _frame_number(frame_data)
        if frame_number < frame_start or frame_number > frame_end:
            raise ValueError(
                f"payload frame {frame_number} is outside [{frame_start}, {frame_end}]"
            )
        _bake_frame(armature_obj, frame_data, frame_number)

    action.frame_range = (float(frame_start), float(frame_end))
    return action


def _bake_frame(armature_obj: bpy.types.Object, frame_data: dict[str, object], frame: int) -> None:
    """Apply one frame's transforms and key them on every present bone."""
    bones = frame_data.get("bones")
    if not isinstance(bones, dict):
        raise ValueError("payload frame is missing a 'bones' mapping")
    for bone_name, transform in bones.items():
        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            continue  # partial skeleton: missing bones simply stay at rest
        if not isinstance(transform, dict):
            raise ValueError(
                f"payload frame {frame}: transform for {bone_name!r} must be an object"
            )

        pose_bone.rotation_mode = "QUATERNION"
        translation = _numbers(transform.get("translation"), 3, "translation")
        pose_bone.location = mathutils.Vector(tuple(translation))
        pose_bone.rotation_quaternion = mathutils.Quaternion(
            tuple(_numbers(transform.get("rotation"), 4, "rotation"))
        )
        pose_bone.scale = mathutils.Vector(tuple(_numbers(transform.get("scale"), 3, "scale")))

        pose_bone.keyframe_insert(data_path=LOCATION_PROP, frame=frame)
        pose_bone.keyframe_insert(data_path=ROTATION_PROP, frame=frame)
        pose_bone.keyframe_insert(data_path=SCALE_PROP, frame=frame)


def _numbers(value: object, length: int, where: str) -> list[float]:
    """Coerce ``value`` to ``length`` floats, raising on anything else."""
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"payload {where} must be a sequence of {length} numbers")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"payload {where} contains a non-number: {item!r}")
        result.append(float(item))
    return result


def _frame_number(frame_data: dict[str, object]) -> int:
    """Return the validated integer frame number of a payload frame."""
    number = frame_data.get("frame")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("payload frame is missing a valid integer 'frame'")
    return number


def _fresh_action(name: str) -> bpy.types.Action:
    """Return a fresh action (remove any existing one with the same name)."""
    existing = bpy.data.actions.get(name)
    if existing is not None:
        bpy.data.actions.remove(existing)
    return bpy.data.actions.new(name)


def _require_visual_keying_safe(armature_obj: bpy.types.Object) -> None:
    """Fail loudly when visual keying cannot be satisfied by direct insertion."""
    if any(pose_bone.constraints for pose_bone in armature_obj.pose.bones):
        raise NotImplementedError(
            "use_visual_keying with constrained rigs requires nla.bake (v0.2); "
            "remove the constraints or pass use_visual_keying=False"
        )