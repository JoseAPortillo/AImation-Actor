"""Scene state for the transposition panel.

Everything the panel shows lives on the *working* scene, never on the preview
scene: the tool's clock and selection are properties of the animator's session,
and the preview scene is a display surface only (S1).
"""

from __future__ import annotations

import bpy

from . import captures

__all__ = [
    "PREVIEW_SCENE",
    "SOURCE_MARKER",
    "SOURCE_NAME",
    "CaptureItem",
    "owner_of",
    "refresh_captures",
    "selected_name",
    "status",
    "tool_scene",
]

#: The scene holding the imported capture. It is never the working scene.
PREVIEW_SCENE = "AImation Capture"
#: Name the source armature is normalised to (the FBX importer invents its own).
SOURCE_NAME = "AImation Capture Rig"
#: Custom property marking the source armature, so a rename never breaks it.
SOURCE_MARKER = "aimation_capture_source"

#: Guards the RNA update callbacks while the capture list is being rebuilt.
_RESTORING = False


class CaptureItem(bpy.types.PropertyGroup):
    """One row of the capture listbox (S2)."""

    name: bpy.props.StringProperty()  # type: ignore[valid-type]


def owner_of(scene) -> bpy.types.Scene | None:
    """The scene whose tool state ``scene`` should act on (S1).

    Every tool property lives on the *animator's* scene. The preview scene carries
    its own empty copy of them (RNA properties registered on ``bpy.types.Scene``
    exist on every scene), so acting on the preview scene's copy would silently
    drive nothing. The preview scene records its owner, and that is followed here.
    """
    if scene is None:
        return None
    if scene.name == PREVIEW_SCENE:
        return scene.preview_owner
    return scene


def tool_scene(context) -> bpy.types.Scene | None:
    """The owner scene resolved from a draw/operator context.

    Without this the tool appears to vanish the moment the viewer opens: the
    viewer window's scene *is* the preview scene, so its controls would be
    reading an empty copy of themselves.
    """
    return owner_of(getattr(context, "scene", None))


def refresh_captures(scene, context) -> int:
    """Repopulate ``scene.capture_items`` from the configured folder.

    Returns how many captures were found. The selection is preserved when the
    file still exists, otherwise clamped to the new end of the list (S2, S9).
    """
    global _RESTORING
    from . import prefs

    preferences = prefs.preferences(context)
    directory = "" if preferences is None else preferences.capture_folder
    names = captures.capture_names_in(directory)

    previous = scene.capture_index
    _RESTORING = True
    try:
        while len(scene.capture_items):
            scene.capture_items.remove(0)
        for name in names:
            scene.capture_items.add().name = name
        scene.capture_index = min(previous, len(names) - 1) if names else -1
    finally:
        _RESTORING = False
    return len(names)


def selected_name(scene) -> str | None:
    """The capture the listbox has selected, or ``None``."""
    if 0 <= scene.capture_index < len(scene.capture_items):
        return scene.capture_items[scene.capture_index].name
    return None


def status(scene) -> str:
    """The last honest message for the panel (S9)."""
    return str(scene.get("aimation_status", ""))


def _set_status(scene, message: str) -> None:
    scene["aimation_status"] = message


def _on_capture_index(scene, context) -> None:
    if _RESTORING:
        return
    owner = owner_of(scene)
    if owner is None:
        return
    name = selected_name(owner)
    if name is None:
        return
    from . import preview

    preview.schedule_load(owner.name, name)


def _on_preview_frame(scene, context) -> None:
    from . import preview

    preview.show_frame(scene.preview_frame)


def _on_preview_rest(scene, context) -> None:
    owner = owner_of(scene)
    if owner is None:
        return
    from . import preview

    preview.apply_rest(owner)


def _on_preview_scene_frame(scene, _depsgraph=None) -> None:
    """Scrubbing the preview window's own timeline feeds the tool's clock back.

    Without this the preview window would inherit the animator's layout — and
    therefore its timeline — and the two clocks would disagree.
    """
    if scene.name != PREVIEW_SCENE:
        return
    owner = scene.preview_owner
    if owner is None or owner.preview_frame == scene.frame_current:
        return
    owner.preview_frame = scene.frame_current


def _rig_poll(_self, obj) -> bool:
    return obj.type == "ARMATURE"


def register() -> None:
    bpy.utils.register_class(CaptureItem)
    scene = bpy.types.Scene
    scene.capture_items = bpy.props.CollectionProperty(type=CaptureItem)  # type: ignore[attr-defined]
    scene.capture_index = bpy.props.IntProperty(  # type: ignore[attr-defined]
        default=-1, update=_on_capture_index
    )
    scene.capture_loaded = bpy.props.StringProperty(  # type: ignore[attr-defined]
        default="", description="The capture file currently in the preview scene"
    )
    scene.capture_first = bpy.props.IntProperty(default=0)  # type: ignore[attr-defined]
    scene.capture_last = bpy.props.IntProperty(default=0)  # type: ignore[attr-defined]
    scene.capture_fps = bpy.props.FloatProperty(default=24.0, min=0.0)  # type: ignore[attr-defined]
    scene.preview_frame = bpy.props.IntProperty(  # type: ignore[attr-defined]
        default=0, update=_on_preview_frame
    )
    scene.preview_playing = bpy.props.BoolProperty(default=False)  # type: ignore[attr-defined]
    scene.preview_rest = bpy.props.BoolProperty(  # type: ignore[attr-defined]
        default=False,
        name="Bind pose",
        description="Freeze the capture in its bind pose for mapping; animation is not "
        "evaluated while this is on",
        update=_on_preview_rest,
    )
    scene.preview_owner = bpy.props.PointerProperty(type=bpy.types.Scene)  # type: ignore[attr-defined]
    scene.target_rig = bpy.props.PointerProperty(  # type: ignore[attr-defined]
        type=bpy.types.Object, poll=_rig_poll
    )
    bpy.app.handlers.frame_change_pre.append(_on_preview_scene_frame)


def unregister() -> None:
    if _on_preview_scene_frame in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_on_preview_scene_frame)
    scene = bpy.types.Scene
    for name in (
        "target_rig",
        "preview_owner",
        "preview_rest",
        "preview_playing",
        "preview_frame",
        "capture_fps",
        "capture_last",
        "capture_first",
        "capture_loaded",
        "capture_index",
        "capture_items",
    ):
        if hasattr(scene, name):
            delattr(scene, name)
    bpy.utils.unregister_class(CaptureItem)


def report(scene, message: str) -> None:
    """Record a user-facing message on the scene (the panel renders it)."""
    _set_status(scene, message)
