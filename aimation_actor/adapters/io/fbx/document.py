"""Maps the domain (:class:`TimelineState`) onto an FBX node tree.

The tree produced here is serialized by
:func:`~aimation_actor.adapters.io.fbx.binary.serialize` into a binary FBX
document that Maya/Blender/HumanIK can open.

Coordinate & transform conventions
----------------------------------

The domain is **Z-up, right-handed, centimetres** (the ``Pelvis`` height lives
on ``Z``). FBX's standard scene is **Y-up, right-handed, centimetres**. Every
translation and rotation is therefore conjugated by ``A = R_x(-90 deg)``, which
maps ``(x, y, z)`` to ``(x, z, -y)``.

A joint is an FBX ``Model`` of type ``LimbNode``:

- ``Lcl Translation`` is the joint's local offset from its parent. At rest it is
  ``JointData.rest_translation``; at a keyframe it is
  ``rest_translation + JointPose.translation`` (the pose translation is a delta).
- ``Lcl Rotation`` is the joint's *local* rotation, taken from
  ``JointPose.rotation`` (a quaternion in the domain). FBX stores rotations as
  Euler angles in degrees with ``RotationOrder = XYZ``, so each key's quaternion
  is converted. Stepped tangents mean no interpolation ever happens between
  keys, so this conversion is lossless pose-for-pose.

Keys are written only at the frames present in the timeline: no channel is ever
filled in between. Every animated channel gets a key at every such frame.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from aimation_actor.adapters.io.fbx.binary import (
    DEFAULT_TIME_ID,
    FBX_VERSION,
    FBXNode,
    char,
    float32_array,
    float64,
    int32,
    int32_array,
    int64,
    int64_array,
    string,
)
from aimation_actor.adapters.io.fbx.transform import (
    rotation_to_fbx_euler_degrees,
    to_fbx_vector,
)
from aimation_actor.core.models import JointData, Keyframe, Quaternion, TimelineState, Vector3

#: FBX's time unit: 1/46186158000 of a second.
KTIME = 46_186_158_000.0

#: The three vector components, paired with their column index in a channel.
_AXES = (("X", 0), ("Y", 1), ("Z", 2))

#: Local-transform property names, shared by rest models and animation channels.
_LCL_TRANSLATION = "Lcl Translation"
_LCL_ROTATION = "Lcl Rotation"
_LCL_SCALING = "Lcl Scaling"

_UNIT_SCALE_FACTOR = 1.0  # 1 FBX unit == 1 centimetre
_TIME_MODE_BY_FPS = {120: 1, 100: 2, 60: 3, 50: 4, 48: 5, 30: 6, 25: 10, 24: 11}
_TAKE_NAME = "Take 001"

#: FBX writes these version numbers verbatim; they identify the writer to readers.
_FBX_HEADER_VERSION = 1003
_MODEL_VERSION = 232
_KEY_VER = 4008
# ``1 << 2`` selects stepped/constant tangents; ``24836`` is the value Autodesk
# and Blender both use for it.
_STEPPED_KEY_ATTR_FLAGS = 24836

#: ``Properties70`` entries are ``(name, type, label, flags, *values)``.
#: The template name FBX declares for a ``Model`` object, and the object types
#: that carry an (empty) ``PropertyTemplate``.
_MODEL_TEMPLATE_NAME = "FbxNode"
_TEMPLATED_TYPES = {
    "AnimationStack": "FbxAnimStack",
    "AnimationLayer": "FbxAnimLayer",
    "AnimationCurveNode": "FbxAnimCurveNode",
}

#: Deterministic ids start high so they never collide with 0 (root) or negatives.
_ID_BASE = 1_000_000_000


class _IdAllocator:
    """Deterministic, unique 64-bit FBX object ids."""

    def __init__(self, base: int = _ID_BASE) -> None:
        self._next = base

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        return value


def _time(frame: int, fps: float) -> int:
    return round(frame / fps * KTIME)


def _reject_duplicate_frames(frames: Sequence[int]) -> None:
    """A timeline carries at most one key per frame; duplicates are an error."""
    duplicates = sorted(frame for frame, count in Counter(frames).items() if count > 1)
    if duplicates:
        raise ValueError(
            f"a timeline has at most one keyframe per frame; duplicated frames: {duplicates}"
        )


# --------------------------------------------------------------------------- #
# Property helpers
# --------------------------------------------------------------------------- #


def _p(name: str, type_name: str, label: str, flags: str, *values) -> FBXNode:
    """A ``P`` property inside ``Properties70``.

    FBX stores these as ``(name, type, label, flags, *values)``; readers assert
    on the exact ``type``/``label`` pair (e.g. ``double`` must be labelled
    ``Number``).
    """
    node = FBXNode("P").add(name, type_name, label, flags)
    node.props.extend(values)
    return node


def _p_anim(name: str, type_name: str, *values) -> FBXNode:
    """An animatable (``A``) ``P`` property inside ``Properties70``."""
    return _p(name, type_name, "", "A", *values)


def _p_number(name: str, *values) -> FBXNode:
    return _p(name, "Number", "", "A", *(float64(v) for v in values))


def _append_p(parent: FBXNode, *properties: FBXNode) -> None:
    """Append ``Properties70``-style ``P`` nodes to ``parent``'s children."""
    parent.children.extend(properties)


# --------------------------------------------------------------------------- #
# Top-level sections
# --------------------------------------------------------------------------- #


def _header(created: datetime) -> FBXNode:
    header = FBXNode("FBXHeaderExtension")
    header.child("FBXHeaderVersion").add(int32(_FBX_HEADER_VERSION))
    header.child("FBXVersion").add(int32(FBX_VERSION))
    header.child("EncryptionType").add(int32(0))

    stamp = header.child("CreationTimeStamp")
    stamp.child("Version").add(int32(1000))
    stamp.child("Year").add(int32(created.year))
    stamp.child("Month").add(int32(created.month))
    stamp.child("Day").add(int32(created.day))
    stamp.child("Hour").add(int32(created.hour))
    stamp.child("Minute").add(int32(created.minute))
    stamp.child("Second").add(int32(created.second))
    stamp.child("Millisecond").add(int32(created.microsecond // 1000))

    header.child("Creator").add(string("AImation Actor"))
    header.child("CreationTime").add(string(DEFAULT_TIME_ID))

    scene_info = header.child("SceneInfo").add(string("GlobalInfo"), string("UserData"))
    scene_info.child("Type").add(string("UserData"))
    scene_info.child("Version").add(int32(100))
    metadata = scene_info.child("MetaData")
    metadata.child("Version").add(int32(100))
    for field in ("Title", "Subject", "Author", "Keywords", "Revision", "Comment"):
        metadata.child(field).add(string(""))
    properties = scene_info.child("Properties70")
    _append_p(
        properties,
        _p("DocumentUrl", "KString", "Url", "", string("")),
        _p("SrcDocumentUrl", "KString", "Url", "", string("")),
    )
    return header


def _global_settings(fps: float, frame_start: int, frame_end: int) -> FBXNode:
    settings = FBXNode("GlobalSettings")
    settings.child("Version").add(int32(1000))
    properties = settings.child("Properties70")

    def enum(name: str, value: int) -> None:
        _append_p(properties, _p(name, "enum", "", "", int32(value)))

    def integer(name: str, value: int) -> None:
        _append_p(properties, _p(name, "int", "Integer", "", int32(value)))

    def number(name: str, value: float) -> None:
        _append_p(properties, _p(name, "double", "Number", "", float64(value)))

    def ktime(name: str, value: int) -> None:
        _append_p(properties, _p(name, "KTime", "Time", "", int64(value)))

    integer("UpAxis", 1)
    integer("UpAxisSign", 1)
    integer("FrontAxis", 2)
    integer("FrontAxisSign", 1)
    integer("CoordAxis", 0)
    integer("CoordAxisSign", 1)
    integer("OriginalUpAxis", -1)
    integer("OriginalUpAxisSign", 1)
    number("UnitScaleFactor", _UNIT_SCALE_FACTOR)
    number("OriginalUnitScaleFactor", _UNIT_SCALE_FACTOR)
    _append_p(
        properties,
        _p("AmbientColor", "ColorRGB", "Color", "", float64(0.0), float64(0.0), float64(0.0)),
        _p("DefaultCamera", "KString", "", "", string("Producer Perspective")),
    )
    enum("TimeMode", _TIME_MODE_BY_FPS.get(int(round(fps)), 0))
    enum("TimeProtocol", 2)
    enum("SnapOnFrameMode", 0)
    ktime("TimeSpanStart", _time(frame_start, fps))
    ktime("TimeSpanStop", _time(frame_end, fps))
    number("CustomFrameRate", fps)
    return settings


def _documents(document_id: int) -> FBXNode:
    documents = FBXNode("Documents")
    documents.child("Count").add(int32(1))
    document = documents.child("Document")
    document.add(int64(document_id), string("Scene"), string("Scene"))
    properties = document.child("Properties70")
    _append_p(
        properties,
        _p("SourceObject", "object", "", ""),
        _p("ActiveAnimStackName", "KString", "", "", string("")),
    )
    document.child("RootNode").add(int64(0))
    return documents


def _definition_template(type_name: str) -> tuple[str, list[FBXNode]]:
    """The property template FBX declares for ``type_name`` (may be empty)."""
    if type_name == "Model":
        return _MODEL_TEMPLATE_NAME, [
            _p_anim(_LCL_TRANSLATION, _LCL_TRANSLATION, float64(0), float64(0), float64(0)),
            _p_anim(_LCL_ROTATION, _LCL_ROTATION, float64(0), float64(0), float64(0)),
            _p_anim(_LCL_SCALING, _LCL_SCALING, float64(1), float64(1), float64(1)),
        ]
    return _TEMPLATED_TYPES.get(type_name, ""), []


def _definitions(object_counts: dict[str, int]) -> FBXNode:
    """Build ``Definitions`` from real object type -> count pairs (no sections)."""
    definitions = FBXNode("Definitions")
    definitions.child("Version").add(int32(100))
    definitions.child("Count").add(int32(sum(object_counts.values())))

    for type_name, count in object_counts.items():
        object_type = definitions.child("ObjectType").add(string(type_name))
        object_type.child("Count").add(int32(count))
        template_name, properties = _definition_template(type_name)
        if template_name:
            template = object_type.child("PropertyTemplate").add(string(template_name))
            if properties:
                template.child("Properties70").children.extend(properties)
    return definitions


def _objects(objects: list[FBXNode]) -> FBXNode:
    node = FBXNode("Objects")
    node.children.extend(objects)
    return node


def _connections(connections: list[FBXNode]) -> FBXNode:
    node = FBXNode("Connections")
    node.children.extend(connections)
    return node


def _takes(fps: float, frame_start: int, frame_end: int) -> FBXNode:
    takes = FBXNode("Takes")
    takes.child("Current").add(string(""))
    take = takes.child("Take").add(string(_TAKE_NAME))
    take.child("FileName").add(string(f"{_TAKE_NAME}.tak"))
    local = (int64(_time(frame_start, fps)), int64(_time(frame_end, fps)))
    take.child("LocalTime").add(*local)
    take.child("ReferenceTime").add(*local)
    return takes


# --------------------------------------------------------------------------- #
# Objects: models, attributes and animation
# --------------------------------------------------------------------------- #


def _model(model_id: int, name: str, rest_translation: Vector3) -> FBXNode:
    model = FBXNode("Model")
    model.add(int64(model_id), string(f"{name}\x00\x01Model"), string("LimbNode"))
    model.child("Version").add(int32(_MODEL_VERSION))
    properties = model.child("Properties70")
    x, y, z = to_fbx_vector(rest_translation)
    _append_p(
        properties,
        _p_anim(_LCL_TRANSLATION, _LCL_TRANSLATION, float64(x), float64(y), float64(z)),
        _p_anim(_LCL_ROTATION, _LCL_ROTATION, float64(0), float64(0), float64(0)),
        _p_anim(_LCL_SCALING, _LCL_SCALING, float64(1), float64(1), float64(1)),
    )
    model.child("MultiLayer").add(int32(0))
    model.child("MultiTake").add(int32(0))
    model.child("Shading").add(char(b"\x00"))
    model.child("Culling").add(string("CullingOff"))
    return model


def _node_attribute(attribute_id: int, name: str) -> FBXNode:
    attribute = FBXNode("NodeAttribute").add(
        int64(attribute_id), string(f"{name}\x00\x01NodeAttribute"), string("LimbNode")
    )
    attribute.child("TypeFlags").add(string("Skeleton"))
    attribute.child("Properties70")
    return attribute


def _connect_oo(child_id: int, parent_id: int) -> FBXNode:
    return FBXNode("C").add(string("OO"), int64(child_id), int64(parent_id))


def _connect_op(child_id: int, parent_id: int, property_name: str) -> FBXNode:
    return FBXNode("C").add(string("OP"), int64(child_id), int64(parent_id), string(property_name))


def _animation_curve(
    curve_id: int, times: list[int], values: list[float], default: float
) -> FBXNode:
    curve = FBXNode("AnimationCurve").add(int64(curve_id), string("\x00\x01AnimCurve"), string(""))
    curve.child("Default").add(float64(default))
    curve.child("KeyVer").add(int32(_KEY_VER))
    curve.child("KeyTime").add(int64_array(times))
    curve.child("KeyValueFloat").add(float32_array(values))
    curve.child("KeyAttrFlags").add(int32_array([_STEPPED_KEY_ATTR_FLAGS]))
    curve.child("KeyAttrDataFloat").add(float32_array([0.0, 0.0, 0.0, 0.0]))
    curve.child("KeyAttrRefCount").add(int32_array([len(times)]))
    return curve


def _animation_stack(stack_id: int, times: list[int]) -> FBXNode:
    stack = FBXNode("AnimationStack")
    stack.add(int64(stack_id), string(f"{_TAKE_NAME}\x00\x01AnimStack"), string(""))
    start, stop = int64(times[0]), int64(times[-1])
    _append_p(
        stack.child("Properties70"),
        _p("LocalStart", "KTime", "Time", "", start),
        _p("LocalStop", "KTime", "Time", "", stop),
        _p("ReferenceStart", "KTime", "Time", "", start),
        _p("ReferenceStop", "KTime", "Time", "", stop),
    )
    return stack


def _animation_layer(layer_id: int) -> FBXNode:
    return FBXNode("AnimationLayer").add(
        int64(layer_id), string(f"{_TAKE_NAME}\x00\x01AnimLayer"), string("")
    )


def _animation_curve_node(node_id: int, kind: str, defaults: tuple[float, float, float]) -> FBXNode:
    node = FBXNode("AnimationCurveNode").add(
        int64(node_id), string(f"{kind}\x00\x01AnimCurveNode"), string("")
    )
    properties = node.child("Properties70")
    _append_p(properties, *(_p_number(f"d|{axis}", defaults[index]) for axis, index in _AXES))
    return node


def _channel_values(
    joint_name: str,
    keyframes: Sequence[Keyframe],
    rest_translation: Vector3,
    kind: str,
) -> list[tuple[float, float, float]]:
    """The per-keyframe FBX values (Y-up) for one channel of one joint."""
    values: list[tuple[float, float, float]] = []
    for keyframe in keyframes:
        pose = keyframe.pose.get(joint_name)
        if kind == "T":
            delta = pose.translation if pose is not None else Vector3()
            total = Vector3(
                rest_translation.x + delta.x,
                rest_translation.y + delta.y,
                rest_translation.z + delta.z,
            )
            values.append(to_fbx_vector(total))
        else:
            rotation = pose.rotation if pose is not None else Quaternion.identity()
            values.append(rotation_to_fbx_euler_degrees(rotation))
    return values


def _wants_translation(joint: JointData, keyframes: Sequence[Keyframe]) -> bool:
    moves = any(
        keyframe.pose.get(joint.name) is not None
        and keyframe.pose[joint.name].translation != Vector3()
        for keyframe in keyframes
    )
    return moves or (joint.parent is None and joint.name == "Main")


def _wants_rotation(joint: JointData, keyframes: Sequence[Keyframe]) -> bool:
    return any(
        keyframe.pose.get(joint.name) is not None
        and keyframe.pose[joint.name].rotation != Quaternion.identity()
        for keyframe in keyframes
    )


def _joint_channels(
    joint: JointData,
    keyframes: Sequence[Keyframe],
    times: list[int],
    rest_translation: Vector3,
    model_id: int,
    layer_id: int,
    ids: _IdAllocator,
) -> tuple[list[FBXNode], list[FBXNode], int, int]:
    """Build the animated channels (translation and/or rotation) of one joint.

    Returns ``(objects, connections, curve_node_count, curve_count)`` so the
    caller can aggregate the ``Definitions`` counts.
    """
    objects: list[FBXNode] = []
    connections: list[FBXNode] = []
    curve_nodes = 0
    curves = 0

    wanted = (("T", _wants_translation(joint, keyframes)), ("R", _wants_rotation(joint, keyframes)))
    for kind, is_wanted in wanted:
        if not is_wanted:
            continue
        channel_id = ids()
        columns = _channel_values(joint.name, keyframes, rest_translation, kind)
        property_name = _LCL_TRANSLATION if kind == "T" else _LCL_ROTATION
        objects.append(_animation_curve_node(channel_id, kind, columns[0]))
        connections.append(_connect_oo(channel_id, layer_id))
        connections.append(_connect_op(channel_id, model_id, property_name))
        curve_nodes += 1
        for axis, index in _AXES:
            curve_id = ids()
            objects.append(
                _animation_curve(
                    curve_id,
                    times,
                    [column[index] for column in columns],
                    columns[0][index],
                )
            )
            connections.append(_connect_op(curve_id, channel_id, f"d|{axis}"))
            curves += 1

    return objects, connections, curve_nodes, curves


def _build_animation(
    state: TimelineState,
    keyframes: Sequence[Keyframe],
    ids: _IdAllocator,
    model_ids: dict[str, int],
) -> tuple[list[FBXNode], list[FBXNode], dict[str, int]]:
    """Build the animation objects, the ``Animation*`` connections, and counts."""
    times = [_time(keyframe.frame, state.fps) for keyframe in keyframes]
    stack_id = ids()
    layer_id = ids()

    objects: list[FBXNode] = [_animation_stack(stack_id, times), _animation_layer(layer_id)]
    connections: list[FBXNode] = [_connect_oo(layer_id, stack_id)]

    rest_by_name = {joint.name: joint.rest_translation for joint in state.skeleton.joints}
    curve_nodes = 0
    curves = 0
    for joint in state.skeleton.joints:
        joint_objects, joint_connections, joint_curve_nodes, joint_curves = _joint_channels(
            joint,
            keyframes,
            times,
            rest_by_name[joint.name],
            model_ids[joint.name],
            layer_id,
            ids,
        )
        objects.extend(joint_objects)
        connections.extend(joint_connections)
        curve_nodes += joint_curve_nodes
        curves += joint_curves

    # Autodesk convention: the stack is connected to the scene root.
    connections.append(_connect_oo(stack_id, 0))

    counts = {
        "AnimationStack": 1,
        "AnimationLayer": 1,
        "AnimationCurveNode": curve_nodes,
        "AnimationCurve": curves,
    }
    return objects, connections, counts


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def build_document(state: TimelineState, *, created: datetime | None = None) -> list[FBXNode]:
    """Build the complete FBX top-level node list for ``state``."""
    created = created or datetime.now(UTC)
    fps = state.fps if state.fps > 0 else 24.0
    keyframes = sorted(state.keyframes, key=lambda keyframe: keyframe.frame)
    frames = [keyframe.frame for keyframe in keyframes]
    _reject_duplicate_frames(frames)

    if state.frame_end > state.frame_start:
        frame_start, frame_end = state.frame_start, state.frame_end
    elif frames:
        frame_start, frame_end = frames[0], frames[-1]
    else:
        frame_start = frame_end = state.frame_start

    ids = _IdAllocator()
    document_id = ids()

    models: list[FBXNode] = []
    attributes: list[FBXNode] = []
    connections: list[FBXNode] = []
    model_ids: dict[str, int] = {}
    attribute_ids: dict[str, int] = {}

    for joint in state.skeleton.joints:
        model_id = ids()
        model_ids[joint.name] = model_id
        models.append(_model(model_id, joint.name, joint.rest_translation))
        attribute_id = ids()
        attribute_ids[joint.name] = attribute_id
        attributes.append(_node_attribute(attribute_id, joint.name))

    for joint in state.skeleton.joints:
        connections.append(_connect_oo(model_ids[joint.name], model_ids.get(joint.parent or "", 0)))
        connections.append(_connect_oo(attribute_ids[joint.name], model_ids[joint.name]))

    objects: list[FBXNode] = [*models, *attributes]
    # ``Definitions`` describes FBX *objects* only; ``GlobalSettings`` is a
    # top-level section, not an object, so it must not be counted here.
    object_counts = {
        "NodeAttribute": len(state.skeleton.joints),
        "Model": len(state.skeleton.joints),
    }
    if keyframes:
        animation_objects, animation_connections, animation_counts = _build_animation(
            state, keyframes, ids, model_ids
        )
        objects.extend(animation_objects)
        connections.extend(animation_connections)
        object_counts.update(animation_counts)

    return [
        _header(created),
        _global_settings(fps, frame_start, frame_end),
        _documents(document_id),
        FBXNode("References"),
        _definitions(object_counts),
        _objects(objects),
        _connections(connections),
        _takes(fps, frame_start, frame_end),
    ]
