"""Build the shadow armature from the neutral skeleton (bpy glue).

Implements the v0.1 slice of spec §5: create/edit bones from the neutral
skeleton's ``rest_position`` chain (LOCAL joint offsets, up-Y, centimetres),
rename or return an existing armature, and store the neutral bone mapping as
a JSON custom property on the object (metadata only — never secrets, spec
§8.1).

Bone geometry convention: each bone spans from its own joint to its first
child's joint (tail = child joint); leaf bones and zero-length segments get a
small deterministic extension because Blender rejects zero-length bones.
"""

from __future__ import annotations

import json

import bpy
import mathutils

from blender_addon.core.motion_prep import bone_map_for_skeleton

DEFAULT_ARMATURE_NAME = "AImation_Actor_Rig"
MIN_BONE_LEN = 0.1  # Blender rejects zero-length bones (doc units, cm)
LEAF_TAIL_LEN = 5.0  # visual extension for leaf bones (doc units, cm)
BONE_MAP_PROP = "aimation_bone_map"
UNITS_PROP = "aimation_skeleton_units"


def ensure_armature(skeleton: object, name: str = DEFAULT_ARMATURE_NAME) -> bpy.types.Object:
    """Return an armature object whose edit bones mirror the neutral skeleton.

    Args:
        skeleton: NeutralMotion skeleton dict (``{"bones": {...}}``).
        name: object name; an existing armature object with this name is
            reused and its bones rebuilt deterministically.

    Returns:
        The armature object, linked into the ``AI_ShadowRig`` collection
        (spec §5.1 isolation) and carrying the bone-map JSON custom props.

    Raises:
        ValueError: On malformed skeletons (via
            :func:`blender_addon.core.motion_prep.bone_map_for_skeleton`).
    """
    bone_map = bone_map_for_skeleton(skeleton)
    bones = skeleton["bones"]
    assert isinstance(bones, dict)

    positions = _joint_positions(bones)
    collection = _shadow_collection()
    obj = _find_or_create_armature(name, collection)
    _rebuild_edit_bones(obj, bones, positions)

    # Metadata only — never tokens or scene content (spec §5.3 / §8.1).
    obj[BONE_MAP_PROP] = json.dumps(bone_map)
    obj[UNITS_PROP] = "cm"
    return obj


def _joint_positions(bones: dict[str, object]) -> dict[str, tuple[float, float, float]]:
    """Accumulate LOCAL rest offsets into armature-space joint positions.

    Relies on the document's parents-before-children ordering (the neutral
    skeleton contract guarantees it) so a single forward pass suffices.
    """
    positions: dict[str, tuple[float, float, float]] = {}
    for key, raw in bones.items():
        assert isinstance(raw, dict)
        parent = raw.get("parent")
        rest = _rest_position(raw)
        if isinstance(parent, str) and parent:
            px, py, pz = positions[parent]
        else:
            px, py, pz = (0.0, 0.0, 0.0)
        positions[key] = (px + rest[0], py + rest[1], pz + rest[2])
    return positions


def _rest_position(raw: dict[str, object]) -> tuple[float, float, float]:
    """Return the bone's LOCAL rest offset as a 3-tuple of floats."""
    value = raw.get("rest_position", (0.0, 0.0, 0.0))
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"skeleton bone rest_position must be [x, y, z], got {value!r}")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"skeleton bone rest_position contains a non-number: {item!r}")
        result.append(float(item))
    return (result[0], result[1], result[2])


def _shadow_collection() -> bpy.types.Collection:
    """Return the ``AI_ShadowRig`` collection, creating it on demand (spec §5.1)."""
    collection = bpy.data.collections.get("AI_ShadowRig")
    if collection is None:
        collection = bpy.data.collections.new("AI_ShadowRig")
        if bpy.context.scene is not None:
            bpy.context.scene.collection.children.link(collection)
    return collection


def _find_or_create_armature(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    """Return an existing armature object ``name`` or create and link a new one."""
    existing = bpy.data.objects.get(name)
    if existing is not None and existing.type == "ARMATURE":
        if existing.name not in collection.objects:
            collection.objects.link(existing)
        return existing
    data = bpy.data.armatures.get(name)
    if data is None:
        data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    return obj


def _rebuild_edit_bones(
    obj: bpy.types.Object,
    bones: dict[str, object],
    positions: dict[str, tuple[float, float, float]],
) -> None:
    """Rebuild the edit-bone set from the joint positions (deterministic)."""
    _enter_edit_mode(obj)
    try:
        edit_bones = obj.data.edit_bones
        # Blender 5.2 removed .clear() on bpy_prop_collection
        for bone in list(edit_bones):
            edit_bones.remove(bone)

        created: dict[str, bpy.types.EditBone] = {}
        for key in positions:
            edit_bone = edit_bones.new(name=key)
            head = mathutils.Vector(positions[key])
            edit_bone.head = head
            edit_bone.tail = _tail_for(key, positions, bones)
            created[key] = edit_bone

        for key, raw in bones.items():
            assert isinstance(raw, dict)
            parent = raw.get("parent")
            if isinstance(parent, str) and parent:
                created[key].parent = created[parent]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def _tail_for(
    key: str,
    positions: dict[str, tuple[float, float, float]],
    bones: dict[str, object],
) -> mathutils.Vector:
    """Compute a deterministic tail for one bone (child joint or extension)."""
    head = mathutils.Vector(positions[key])
    # First child joint becomes the tail (joint-to-joint display).
    for child_key, child_raw in bones.items():
        assert isinstance(child_raw, dict)
        if child_raw.get("parent") == key:
            tail = mathutils.Vector(positions[child_key])
            if (tail - head).length >= MIN_BONE_LEN:
                return tail
    # Leaf / zero-length segment: extend along the bone's own rest offset.
    raw = bones[key]
    assert isinstance(raw, dict)
    direction = mathutils.Vector(_rest_position(raw))
    if direction.length < MIN_BONE_LEN:
        direction = mathutils.Vector((0.0, MIN_BONE_LEN, 0.0))
    return head + direction.normalized() * LEAF_TAIL_LEN


def _enter_edit_mode(obj: bpy.types.Object) -> None:
    """Make ``obj`` active and switch it (and only it) into edit mode."""
    if bpy.context.scene is not None:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")