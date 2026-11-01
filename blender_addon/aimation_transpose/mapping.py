"""Click-to-map surface: link capture bones to rig controls (S4, S7).

The animator sees the capture in bind pose inside the viewer window and clicks
the bone they want to drive; a searchable popup lists every control the target
rig offers — its pose bones plus the empties in the file — and picking one
stores the link and turns the bone green.

The gesture lives in the viewer window on purpose. A modal operator only
receives mouse events from the window it started in (measured on Blender
5.2.3), and the capture skeleton lives in the viewer while the rig lives in the
animator's own viewport. The target control is therefore chosen from a popup
opened by the same window, never by a second click somewhere else.

Everything here is ``bpy`` shell. The ray mathematics is pure and lives in
:mod:`picking`, which the repository's pytest run covers.
"""

from __future__ import annotations

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import picking, preview, props

__all__ = [
    "GREEN",
    "GREY",
    "PENDING",
    "AIMATION_OT_finish_mapping",
    "AIMATION_OT_map_bones",
    "AIMATION_OT_pick_target",
    "activate",
    "build_choices",
    "finish",
    "link",
    "refresh_colours",
    "unlink",
]

#: Colours the mapping surface paints on the capture bones. The animator learns
#: them once: grey means "still on the capture", green means "linked", amber
#: means "waiting for its control".
GREY = (0.35, 0.35, 0.35)
PENDING = (0.90, 0.55, 0.10)
GREEN = (0.15, 0.72, 0.25)

#: A click is accepted when the bone passes this close to the ray, as a share
#: of the skeleton's own size — absolute distances would mean one thing for a
#: hand and something else for a full body.
_PICK_SHARE = 0.10
_MIN_PICK_EXTENT = 1.0

#: The popup's identifier -> (kind, object name, bone name). Rebuilt every time
#: the popup opens; ``execute`` never parses the identifier back into parts.
_CHOICES: dict[str, tuple[str, str, str]] = {}

_NO_CHOICE = "__none__"


# --------------------------------------------------------------------------- #
# The session
# --------------------------------------------------------------------------- #


def activate(owner) -> tuple[bool, str]:
    """Start (or resume) mapping: bind pose, grey bones, clicks armed (S4).

    Refuses with a named reason when there is nothing to map: without a capture
    there are no bones to click, and without a target rig a link would name a
    control that cannot be resolved later.
    """
    armature = preview.source_armature()
    if armature is None:
        return False, "Load a capture before mapping bones"
    rig = getattr(owner, "target_rig", None)
    if rig is None:
        return False, "Pick a target rig before mapping bones"
    if rig.type != "ARMATURE":
        return False, f"{rig.name} is not an armature"

    owner.mapping_active = True
    owner.mapping_pending = ""
    # Bind pose is not a preference here: the animator must click the skeleton
    # the capture was authored in, not a pose the animation invented at the
    # current frame.
    owner.preview_rest = True
    armature.data.show_bone_colors = True
    refresh_colours(owner)
    return True, f"Mapping: click a capture bone ({len(owner.mapping_items)} linked)"


def finish(owner) -> None:
    """End the mapping session: playback back, amber cleared (S4)."""
    owner.mapping_active = False
    owner.mapping_pending = ""
    # Finishing returns the viewer to the animation; bind pose stays available
    # in the panel as an explicit choice.
    owner.preview_rest = False
    refresh_colours(owner)


def refresh_colours(owner) -> None:
    """Repaint every capture bone from the stored links (S4, S7).

    Grey: no link. Amber: the bone the animator just clicked, waiting for its
    control. Green: linked to a control that still exists. A link whose target
    vanished reads grey again instead of lying green — the panel counts those
    separately (S9).
    """
    armature = preview.source_armature()
    if armature is None:
        if owner.mapping_active:
            owner.mapping_active = False
        return
    armature.data.show_bone_colors = True
    pending = owner.mapping_pending
    for bone in armature.data.bones:
        if bone.name == pending:
            _paint(armature, bone.name, PENDING)
            continue
        item = props.link_of(owner, bone.name)
        if item is not None and _resolves(item):
            _paint(armature, bone.name, GREEN)
        else:
            _paint(armature, bone.name, GREY)


def unresolved(owner) -> int:
    """How many links point at a control that is no longer in the file (S9)."""
    return sum(1 for item in owner.mapping_items if not _resolves(item))


def _resolves(item) -> bool:
    """Whether the link's target control still exists under the stored name."""
    if item.kind == "EMPTY":
        target = bpy.data.objects.get(item.object)
        return target is not None and target.type == "EMPTY"
    target = bpy.data.objects.get(item.object)
    if target is None or target.type != "ARMATURE":
        return False
    return item.target_bone in target.pose.bones


def _paint(armature, bone_name: str, colour: tuple[float, float, float]) -> None:
    """Set one bone's custom colour on the data and the pose side alike.

    ``BoneColor.custom`` is a read-only pointer to a ``ThemeBoneColorSet``
    (measured on 5.2.3): the colour is written through ``.normal``, and only
    after ``palette`` selects ``CUSTOM``.
    """
    bone = armature.data.bones.get(bone_name)
    if bone is not None:
        bone.color.palette = "CUSTOM"
        bone.color.custom.normal = colour
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is not None:
        pose_bone.color.palette = "CUSTOM"
        pose_bone.color.custom.normal = colour


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #


def link(owner, bone: str, kind: str, object_name: str, target_bone: str = "") -> None:
    """Store (or replace) ``bone``'s link to one rig control (S7)."""
    item = props.link_of(owner, bone)
    if item is None:
        item = owner.mapping_items.add()
        item.name = bone
    item.kind = kind
    item.object = object_name
    item.target_bone = target_bone
    refresh_colours(owner)


def unlink(owner, bone: str) -> bool:
    """Drop ``bone``'s link, so it turns grey again (S4)."""
    for index, item in enumerate(owner.mapping_items):
        if item.name == bone:
            owner.mapping_items.remove(index)
            refresh_colours(owner)
            return True
    return False


# --------------------------------------------------------------------------- #
# The target-control popup
# --------------------------------------------------------------------------- #


def _targets(owner):
    """Every control a link may point at: identifier, label and its triple.

    When the pending bone is already linked, the list opens with a
    ``Remove link`` entry, so unmapping needs no second gesture and no extra
    button: the same popup both sets and clears the link.

    The target rig's pose bones come first, then every empty in the file. One
    builder feeds both the popup and the lookup table, so confirming a choice
    never parses the identifier back into parts.
    """
    pending = getattr(owner, "mapping_pending", "")
    if pending and props.link_of(owner, pending) is not None:
        yield "UNLINK:-:", "Remove link", ("UNLINK", "", "")
    rig = getattr(owner, "target_rig", None)
    if rig is not None and rig.type == "ARMATURE":
        for bone in rig.pose.bones:
            yield (
                f"BONE:{rig.name}:{bone.name}",
                f"{rig.name}: {bone.name}",
                ("BONE", rig.name, bone.name),
            )
    for obj in bpy.data.objects:
        if obj.type != "EMPTY":
            continue
        yield f"EMPTY:{obj.name}:", f"{obj.name} (empty)", ("EMPTY", obj.name, "")


def build_choices(owner) -> list[tuple[str, str]]:
    """Every control a link may point at, as ``(identifier, label)`` pairs."""
    return [(identifier, label) for identifier, label, _target in _targets(owner)]


def _refresh_choices(owner) -> list[tuple[str, str]]:
    _CHOICES.clear()
    choices: list[tuple[str, str]] = []
    for identifier, label, target in _targets(owner):
        _CHOICES[identifier] = target
        choices.append((identifier, label))
    return choices


class AIMATION_OT_pick_target(bpy.types.Operator):
    """Searchable popup listing the rig controls (S4)."""

    bl_idname = "aimation.pick_target"
    bl_label = "Pick Control"
    bl_description = "Choose the rig control that drives the clicked capture bone"
    bl_property = "choice"
    bl_options = {"REGISTER", "INTERNAL"}

    choice: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Control",
        description="Bones of the target rig and the empties in the file",
        items=lambda self, context: _items(self, context),
    )

    def invoke(self, context, event):
        scene = props.tool_scene(context)
        if scene is None:
            self.report({"WARNING"}, "This viewer window is not bound to a working scene")
            return {"CANCELLED"}
        if not scene.mapping_pending:
            props.report(scene, "Click a capture bone first")
            self.report({"WARNING"}, "Click a capture bone first")
            return {"CANCELLED"}
        _refresh_choices(scene)
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = props.tool_scene(context)
        if scene is None:
            self.report({"WARNING"}, "This viewer window is not bound to a working scene")
            return {"CANCELLED"}
        bone = scene.mapping_pending
        if not bone:
            props.report(scene, "Click a capture bone first")
            self.report({"WARNING"}, "Click a capture bone first")
            return {"CANCELLED"}
        target = _CHOICES.get(self.choice)
        if target is None:
            # The list is rebuilt whenever the popup opens, so a stale
            # identifier means the file changed under the popup: refuse by name
            # rather than link a control that is no longer there (S9).
            props.report(scene, "That control is no longer available; try again")
            self.report({"WARNING"}, "That control is no longer available")
            return {"CANCELLED"}
        kind, object_name, target_bone = target
        if kind == "UNLINK":
            unlink(scene, bone)
            scene.mapping_pending = ""
            props.report(scene, f"{bone}: link removed")
            return {"FINISHED"}
        link(scene, bone, kind, object_name, target_bone)
        scene.mapping_pending = ""
        props.report(scene, f"{bone} -> {self.choice}")
        return {"FINISHED"}

    def cancel(self, context):
        # A dismissed popup must not leave its bone amber forever: the animator
        # is still mapping, they simply changed their mind about this one.
        scene = props.tool_scene(context)
        if scene is not None and scene.mapping_active and scene.mapping_pending:
            scene.mapping_pending = ""
            refresh_colours(scene)


def _refusal(context) -> str | None:
    """Why the modal cannot own this click, or ``None`` when it can.

    A modal only receives mouse events from the window it started in, and the
    capture skeleton is not in the animator's viewport: starting the session
    anywhere else would arm a picker that can never see its own clicks.
    """
    scene = props.tool_scene(context)
    if scene is None:
        return "This viewer window is not bound to a working scene"
    preview_scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    window = getattr(context, "window", None)
    if window is None or window.scene != preview_scene:
        return "Start mapping from the 3D viewer: clicks in other windows never reach it"
    return None


class AIMATION_OT_map_bones(bpy.types.Operator):
    """Modal picking of the capture bones to map (S4)."""

    bl_idname = "aimation.map_bones"
    bl_label = "Map Bones"
    bl_description = (
        "Click capture bones in the viewer and pick their rig controls; "
        "Esc or right-click finishes"
    )
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        refusal = _refusal(context)
        scene = props.tool_scene(context)
        if refusal is not None:
            if scene is not None:
                props.report(scene, refusal)
            self.report({"WARNING"}, refusal)
            return {"CANCELLED"}
        if scene is None:  # unreachable: _refusal refuses that case first
            return {"CANCELLED"}
        ok, message = activate(scene)
        props.report(scene, message)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        scene = props.tool_scene(context)
        if scene is None or not scene.mapping_active:
            context.window.cursor_modal_restore()
            return {"CANCELLED"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            finish(scene)
            context.window.cursor_modal_restore()
            props.report(scene, f"Mapping finished ({len(scene.mapping_items)} linked)")
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            bone = _bone_under(context.window, event.mouse_x, event.mouse_y)
            if bone is None:
                scene.mapping_pending = ""
                refresh_colours(scene)
                props.report(scene, "No capture bone under the cursor")
                return {"RUNNING_MODAL"}
            scene.mapping_pending = bone
            refresh_colours(scene)
            props.report(scene, f"{bone}: pick its control")
            bpy.ops.aimation.pick_target("INVOKE_DEFAULT")
            return {"RUNNING_MODAL"}
        # Everything else (orbit, pan, zoom, the timeline) keeps working: the
        # animator navigates while mapping.
        return {"PASS_THROUGH"}


class AIMATION_OT_finish_mapping(bpy.types.Operator):
    """End the mapping session from the panel (S4)."""

    bl_idname = "aimation.finish_mapping"
    bl_label = "Finish Mapping"
    bl_description = "Stop mapping and return the viewer to the animation"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = props.tool_scene(context)
        if scene is None:
            self.report({"WARNING"}, "This viewer window is not bound to a working scene")
            return {"CANCELLED"}
        finish(scene)
        props.report(scene, f"Mapping finished ({len(scene.mapping_items)} linked)")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Picking
# --------------------------------------------------------------------------- #


def _bone_under(window, mouse_x: float, mouse_y: float) -> str | None:
    """The capture bone closest to the click ray, in armature space."""
    armature = preview.source_armature()
    if armature is None:
        return None
    ray = _ray(window, mouse_x, mouse_y)
    if ray is None:
        return None
    origin, direction = ray
    inverse = armature.matrix_world.inverted()
    local_origin = inverse @ origin
    local_direction = inverse.to_3x3() @ direction
    segments = [
        (bone.name, tuple(bone.head_local), tuple(bone.tail_local))
        for bone in armature.data.bones
    ]
    return _pick(segments, tuple(local_origin), tuple(local_direction))


def _pick(segments, origin, direction) -> str | None:
    points = [Vector(head) for _name, head, _tail in segments]
    points.extend(Vector(tail) for _name, _head, tail in segments)
    if not points:
        return None
    center = sum(points, Vector()) / len(points)
    extent = max((point - center).length for point in points) * 2.0
    threshold = max(extent, _MIN_PICK_EXTENT) * _PICK_SHARE
    hit = picking.pick_bone(origin, direction, segments, max_distance=threshold)
    return None if hit is None else hit[0]


def _ray(window, mouse_x: float, mouse_y: float):
    """The click ray in world space, from the viewport under the mouse."""
    if window is None or window.screen is None:
        return None
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        if not _inside(area, mouse_x, mouse_y):
            continue
        region_3d = area.spaces.active.region_3d
        if region_3d is None:
            return None
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            coordinate = (mouse_x, mouse_y)
            origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
            direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
            return origin, direction
    return None


def _inside(area, x: float, y: float) -> bool:
    return area.x <= x <= area.x + area.width and area.y <= y <= area.y + area.height


def _items(self, context):
    """The searchable list the popup draws; rebuilt on every keystroke."""
    scene = props.tool_scene(context)
    choices = [] if scene is None else _refresh_choices(scene)
    if not choices:
        return [(_NO_CHOICE, "No controls available", "")]
    return [(identifier, label, "") for identifier, label in choices]


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

_OPERATORS = (
    AIMATION_OT_map_bones,
    AIMATION_OT_pick_target,
    AIMATION_OT_finish_mapping,
)


def register() -> None:
    for operator in _OPERATORS:
        bpy.utils.register_class(operator)


def unregister() -> None:
    for operator in reversed(_OPERATORS):
        bpy.utils.unregister_class(operator)
