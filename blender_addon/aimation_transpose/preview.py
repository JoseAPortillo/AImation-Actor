"""The isolated preview scene and the capture armature that lives in it (S1).

The application's exports carry their own frame rate (``GlobalSettings``:
``TimeMode`` plus ``CustomFrameRate``), and Blender's importer honours it — the
keys land on the written frames whatever the scene's rate, measured with a 30
fps probe imported into 24/30/60 fps scenes. The importer also rewrites the
importing scene's ``render.fps`` to that value, which is where the capture's
rate is read from before the animator's scene is put back.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Vector

from . import captures, playback, props

__all__ = [
    "apply_rest",
    "load_capture",
    "open_window",
    "preview_scene",
    "schedule_load",
    "show_frame",
    "source_armature",
]

_MIN_VIEW_DISTANCE = 2.0

#: Coalesces rapid listbox clicks into one deferred load.
_pending: tuple[str, str] | None = None


# --------------------------------------------------------------------------- #
# The scene
# --------------------------------------------------------------------------- #


def preview_scene() -> bpy.types.Scene:
    """The dedicated scene holding only the imported capture (S1)."""
    scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    if scene is None:
        scene = bpy.data.scenes.new(props.PREVIEW_SCENE)
        scene.render.fps = 24
        scene.unit_settings.system = "METRIC"
    return scene


def source_armature() -> bpy.types.Object | None:
    """The capture armature, found by marker so a rename never loses it."""
    scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    if scene is None:
        return None
    for obj in scene.objects:
        if obj.type == "ARMATURE" and obj.get(props.SOURCE_MARKER):
            return obj
    return None


def show_frame(frame: int) -> None:
    """Drive the preview scene from the tool's clock (S1)."""
    scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    if scene is None or scene.frame_current == frame:
        return
    scene.frame_set(frame)
    _tag_viewer_redraw()


def _tag_viewer_redraw() -> None:
    """Ask the windows showing the preview scene to repaint.

    The clock advances on a timer while the animator's own window is the active
    one, so nothing else would tell the viewer to repaint: the frame changes and
    the window keeps showing the pose it last drew.
    """
    scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    if scene is None:
        return
    for window in bpy.context.window_manager.windows:
        if window.scene != scene:
            continue
        for area in window.screen.areas:
            area.tag_redraw()


def apply_rest(owner) -> None:
    """Show the capture in its bind pose (mapping) or in pose (playback)."""
    armature = source_armature()
    if armature is None:
        return
    armature.data.pose_position = "REST" if owner.preview_rest else "POSE"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def schedule_load(owner_name: str, name: str) -> None:
    """Load ``name`` on the next tick — never inside an RNA update callback."""
    global _pending
    _pending = (owner_name, name)
    if not bpy.app.timers.is_registered(_deferred_load):
        bpy.app.timers.register(_deferred_load, first_interval=0.0)


def _deferred_load():
    global _pending
    request, _pending = _pending, None
    if request is not None:
        owner = bpy.data.scenes.get(request[0])
        from . import prefs

        preferences = prefs.preferences(bpy.context)
        directory = "" if preferences is None else preferences.capture_folder
        if owner is not None:
            ok, message = load_capture(owner, request[1], directory)
            props.report(owner, message)
            if not ok:
                owner.capture_loaded = ""
    return None


def load_capture(owner, name: str, directory: str) -> tuple[bool, str]:
    """Import ``name`` as the single source armature, swapping when possible.

    Returning ``(ok, message)`` keeps every failure visible in the panel (S9);
    the caller never has to guess why the viewer stayed empty.
    """
    if owner.capture_loaded == name and source_armature() is not None:
        return True, f"{name} is already loaded"

    path = captures.capture_path(directory, name)
    if path is None or not path.is_file():
        return False, f"Capture not found: {name}"

    try:
        created, fps = _import(path)
    except RuntimeError as error:
        return False, f"{name} could not be imported: {error}"

    armatures = [obj for obj in created if obj.type == "ARMATURE"]
    if not armatures:
        _remove(created)
        return False, f"{name} holds no armature"

    incoming = armatures[0]
    action = _action_of(incoming)
    if action is None:
        _remove(created)
        return False, f"{name} holds no animation"

    existing = source_armature()
    if existing is not None and _same_bones(existing, incoming):
        # S3: the capture changed, the skeleton did not — swap the action and
        # drop the duplicate so the viewport camera never jumps.
        _adopt(existing, action)
        _remove([obj for obj in created if obj is not incoming])
        _remove([incoming])
        source = existing
    else:
        if existing is not None:
            _remove([existing])
        _remove([obj for obj in created if obj is not incoming])
        source = incoming
        source.name = props.SOURCE_NAME

    _mark(source)
    _make_stepped(action)
    _bind_clock(owner, source, action, fps)
    playback.reset(owner)
    owner.capture_loaded = name
    return True, f"Loaded {name} ({len(source.data.bones)} bones)"


def _make_stepped(action) -> int:
    """Re-assert stepped keys on the imported action, and return how many.

    Blender's FBX importer never reads ``KeyAttrFlags``: its own source says
    *"Currently, linear interpolation is assumed, but FBX does store how
    keyframes should be interpolated"* (``import_fbx.py:716``), so a capture that
    leaves this application stepped (``KeyAttrFlags`` ``24836`` = CONSTANT) comes
    back looking smooth. The viewer would then show in-between poses that do not
    exist in the animator's file, which is the one thing this tool must not do.
    """
    points = []
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                bag = strip.channelbag(slot)
                if bag is None:
                    continue
                points.extend(kp for fcurve in bag.fcurves for kp in fcurve.keyframe_points)
    for point in points:
        point.interpolation = "CONSTANT"
    return len(points)


def _import(path: Path) -> tuple[list[bpy.types.Object], float]:
    """Import one capture through the legacy FBX importer, then move it.

    ``bpy.ops.import_scene.fbx`` IS the legacy importer in Blender 5.2: the new
    one is registered as a name only and its operator RNA is not available, so
    the legacy path is the one that actually runs and the one that carries
    ``automatic_bone_orientation``. That flag is on deliberately: left at its
    default the importer keeps the FBX-authored bone axes, which flips which end
    of a bone is its head and leaves every bone's local Y pointing the same way
    regardless of where the bone goes (measured on a 30 fps capture: with the
    default ``Pelvis`` spans y 90 -> 170, with it on, y 90 -> 10, and the bones
    that point down get ``y = (0,-1,0)`` instead of ``(0,1,0)``). The animator's
    skeleton was being drawn inside-out.

    The importer must *not* run under ``temp_override``: it builds the armature
    by entering edit mode through an operator, and that operator resolves the
    active object against the real context — an overridden scene yields an
    armature with zero bones and a ``KeyError`` on the first bone (measured, see
    ``blender_addon/tests/headless_smoke.py``). So the import runs plainly and
    the created objects are moved afterwards.

    The importer rewrites the importing scene's frame rate from the file's
    ``GlobalSettings``/``CustomFrameRate`` — that value *is* the capture's frame
    rate, so it is read before the snapshot is restored, and the animator's
    scene is left exactly as it was.

    A failure removes everything the attempt created, so a half-built state is
    never left behind (S9) — the animator's scene is the scene the import would
    otherwise pollute.
    """
    scene = preview_scene()
    working = bpy.context.scene
    snapshot = _snapshot(working)
    before = {obj.as_pointer() for obj in bpy.data.objects}
    actions_before = {action.as_pointer() for action in bpy.data.actions}
    try:
        result = bpy.ops.import_scene.fbx(
            filepath=str(path),
            use_anim=True,
            anim_offset=0.0,
            automatic_bone_orientation=True,
        )
        fps = working.render.fps / (working.render.fps_base or 1.0)
    except RuntimeError:
        _discard(before, actions_before)
        raise
    finally:
        _restore(working, snapshot)
    if "FINISHED" not in result:
        _discard(before, actions_before)
        raise RuntimeError("the FBX importer refused the file")
    created = _created_since(before)
    _move_to(created, scene)
    return created, fps


def _created_since(before: set[int]) -> list[bpy.types.Object]:
    """Objects the import added, matched by pointer so a rename cannot confuse it."""
    return [obj for obj in bpy.data.objects if obj.as_pointer() not in before]


def _discard(before: set[int], actions_before: set[int]) -> None:
    """Remove everything a failed import created (S9)."""
    for obj in _created_since(before):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        if action.as_pointer() not in actions_before and action.users == 0:
            bpy.data.actions.remove(action)


def _snapshot(scene) -> tuple:
    """The animator's scene state the importer is allowed to disturb."""
    return (
        scene.render.fps,
        scene.render.fps_base,
        scene.frame_start,
        scene.frame_end,
        scene.frame_current,
    )


def _restore(scene, snapshot: tuple) -> None:
    """Put the working scene back exactly as the importer found it."""
    fps, fps_base, start, end, current = snapshot
    scene.render.fps = fps
    scene.render.fps_base = fps_base
    scene.frame_start = start
    scene.frame_end = end
    # Assigned, never ``frame_set``: no handler — including this add-on's — runs.
    scene.frame_current = current


def _move_to(objects: list[bpy.types.Object], scene: bpy.types.Scene) -> None:
    for obj in objects:
        if obj.name in scene.objects:
            continue
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        scene.collection.objects.link(obj)


def _remove(objects) -> None:
    for obj in objects:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def _mark(armature: bpy.types.Object) -> None:
    armature[props.SOURCE_MARKER] = True
    armature.show_in_front = True


def _action_of(armature: bpy.types.Object):
    data = armature.animation_data
    return None if data is None else data.action


def _adopt(source: bpy.types.Object, action) -> None:
    """Give ``source`` the incoming action, binding its slot explicitly.

    Blender 4.4+ actions are slotted: assigning the action alone can leave the
    animation unbound, so the slot is selected by hand.
    """
    source.animation_data_create()
    source.animation_data.action = action
    slots = getattr(action, "slots", None)
    if slots and hasattr(source.animation_data, "action_slot"):
        source.animation_data.action_slot = slots[0]


def _same_bones(left: bpy.types.Object, right: bpy.types.Object) -> bool:
    return {bone.name for bone in left.data.bones} == {
        bone.name for bone in right.data.bones
    }


def _bind_clock(owner, source: bpy.types.Object, action, fps: float) -> None:
    """Publish the capture's frames and rate to the tool's clock (S1)."""
    scene = preview_scene()
    start, end = action.frame_range
    first, last = int(round(start)), int(round(end))
    owner.capture_first = first
    owner.capture_last = last
    owner.capture_fps = float(fps if fps > 0.0 else 24.0)
    # Whole-number rates only: the preview timeline is a display, and the clock
    # keeps the exact value in ``capture_fps`` (a 23.976 capture ticks at 23.976).
    scene.render.fps = max(int(round(owner.capture_fps)), 1)
    scene.render.fps_base = 1.0
    scene.frame_start = first
    scene.frame_end = max(last, first)
    # The viewer window's context scene IS this preview scene, so the panel and
    # the operators have to be able to walk back to the animator's scene from it.
    scene.preview_owner = owner
    scene.frame_set(first)
    owner.preview_frame = first
    apply_rest(owner)
    _frame_armature(source)
    _tag_viewer_redraw()


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #


def open_window() -> tuple[bool, str]:
    """Open (or focus) the secondary window showing the preview scene (S1)."""
    scene = preview_scene()
    manager = bpy.context.window_manager
    for window in manager.windows:
        if window.scene == scene:
            return True, "The 3D viewer is already open"
    try:
        bpy.ops.wm.window_new()
    except RuntimeError as error:  # background mode has no window manager
        return False, f"The 3D viewer needs the interactive editor: {error}"
    window = manager.windows[-1]
    window.scene = scene
    # The view layer follows the scene: the viewer's own timeline and viewport
    # must belong to the preview scene, not to the animator's.
    if scene.view_layers:
        window.view_layer = scene.view_layers[0]
    # The window is deliberately NOT sized: `Window.width`, `Window.height`,
    # `Window.x` and `Window.y` are read-only in Blender 5.2 and there is no
    # resize operator, so geometry is the animator's to decide by dragging.
    if _shares_layout(window):
        # `wm.window_new` gave the viewer the SAME Screen datablock as the
        # animator's window. Areas belong to the Screen, not to the window, so
        # shading or view changes here would rewrite their viewport — the one
        # thing isolation forbids (S1). Leave the layout alone and say so.
        return True, (
            "3D viewer opened, but it shares your window layout: "
            "the tool did not change your viewport shading or framing"
        )
    _configure_viewports(window)
    _frame_armature(source_armature())
    return True, "3D viewer opened"


def _shares_layout(window) -> bool:
    """Whether another window is displaying the same Screen as ``window``."""
    return any(
        other != window and other.screen == window.screen
        for other in bpy.context.window_manager.windows
    )


def _configure_viewports(window) -> None:
    if _shares_layout(window):
        return
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        if space is None:
            continue
        space.shading.type = "SOLID"
        space.overlay.show_relationship_lines = False


def _frame_armature(armature: bpy.types.Object | None) -> None:
    """Point every preview viewport at the armature without an operator."""
    if armature is None:
        return
    points = [armature.matrix_world @ point for point in _extent_points(armature)]
    if not points:
        return
    center = sum(points, Vector()) / len(points)
    size = max((point - center).length for point in points) * 2.0
    distance = max(size, _MIN_VIEW_DISTANCE) * 1.4
    for window in bpy.context.window_manager.windows:
        if window.scene != preview_scene() or _shares_layout(window):
            continue
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = area.spaces.active.region_3d
            if region is not None:
                region.view_location = center
                region.view_distance = distance
                region.view_perspective = "PERSP"


def _extent_points(armature: bpy.types.Object):
    if armature.data.pose_position == "REST":
        bones = ((bone.head_local, bone.tail_local) for bone in armature.data.bones)
    else:
        bones = ((bone.head, bone.tail) for bone in armature.pose.bones)
    for head, tail in bones:
        yield head
        yield tail
