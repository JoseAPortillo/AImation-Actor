"""Scene state for the transposition panel.

Everything the panel shows lives on the *working* scene, never on the preview
scene: the tool's clock and selection are properties of the animator's session,
and the preview scene is a display surface only (S1).
"""

from __future__ import annotations

from pathlib import Path

import bpy

from . import captures

__all__ = [
    "PREVIEW_SCENE",
    "SOURCE_MARKER",
    "SOURCE_NAME",
    "CaptureItem",
    "MappingItem",
    "explicit_path",
    "index_of",
    "link_of",
    "owner_of",
    "refresh_captures",
    "remove_capture",
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
    #: The exact file a manually imported row means. Folder rows resolve
    #: against the capture folder instead, so this stays empty for them.
    path: bpy.props.StringProperty()  # type: ignore[valid-type]


class MappingItem(bpy.types.PropertyGroup):
    """One capture-bone -> rig-control link (S7).

    ``name`` is the capture bone the link came from. The target is either a
    pose bone of the target rig (``kind == "BONE"``) or an empty object
    (``kind == "EMPTY"``); ``object`` holds the target object's name in both
    cases and ``target_bone`` is empty for empties. Everything is keyed by
    plain names so the links survive capture reloads and rig renames report
    as missing instead of corrupting the row.
    """

    name: bpy.props.StringProperty()  # type: ignore[valid-type]
    kind: bpy.props.EnumProperty(  # type: ignore[valid-type]
        items=(
            ("BONE", "Bone", "A pose bone of the target rig"),
            ("EMPTY", "Empty", "An empty object driving the rig"),
        ),
        default="BONE",
    )
    object: bpy.props.StringProperty(  # type: ignore[valid-type]
        description="Name of the armature or empty object the control lives on"
    )
    target_bone: bpy.props.StringProperty(  # type: ignore[valid-type]
        description="Pose bone of the target rig; empty for an empty target"
    )


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

    Returns how many captures were found. Rows the animator imported by hand
    survive the rebuild — their file lives outside the folder, which is the
    whole point of importing a single capture (S2) — as long as the file still
    exists and no folder row already owns that name (a folder refresh is the
    folder's truth). The selection is preserved when the file still exists,
    otherwise clamped to the new end of the list (S2, S9).
    """
    global _RESTORING
    from . import prefs

    preferences = prefs.preferences(context)
    directory = "" if preferences is None else preferences.capture_folder
    names = captures.capture_names_in(directory)

    manual: list[tuple[str, str]] = []
    for item in scene.capture_items:
        if (
            item.path
            and Path(bpy.path.abspath(item.path)).is_file()
            and item.name not in names
        ):
            manual.append((item.name, item.path))

    previous_name = selected_name(scene)
    _RESTORING = True
    try:
        while len(scene.capture_items):
            scene.capture_items.remove(0)
        for name in names:
            scene.capture_items.add().name = name
        for name, path in manual:
            item = scene.capture_items.add()
            item.name = name
            item.path = path
        if previous_name is not None:
            index = index_of(scene, previous_name)
            if index is not None:
                scene.capture_index = index
                return len(names)
        count = len(scene.capture_items)
        previous = scene.capture_index
        scene.capture_index = min(previous, count - 1) if count else -1
    finally:
        _RESTORING = False
    return len(names)


def index_of(scene, name: str) -> int | None:
    """The row index of ``name``, or ``None`` when the list holds no such row."""
    for index, item in enumerate(scene.capture_items):
        if item.name == name:
            return index
    return None


def remove_capture(scene, name: str) -> bool:
    """Drop ``name``'s row from the list; the viewer keeps what it shows (S2).

    A folder refresh is the folder's truth and will re-list a removed folder
    file; only hand-imported rows are gone for good. The selection follows the
    removed row's neighbour and the whole change runs under the rebuild guard,
    so removing a row never schedules a load of whatever the clamp lands on.
    """
    global _RESTORING
    index = index_of(scene, name)
    if index is None:
        return False
    selected = selected_name(scene)
    _RESTORING = True
    try:
        scene.capture_items.remove(index)
        count = len(scene.capture_items)
        kept = index_of(scene, selected) if selected and selected != name else None
        if kept is not None:
            scene.capture_index = kept
        elif count:
            scene.capture_index = min(index, count - 1)
        else:
            scene.capture_index = -1
    finally:
        _RESTORING = False
    return True


def selected_name(scene) -> str | None:
    """The capture the listbox has selected, or ``None``."""
    if 0 <= scene.capture_index < len(scene.capture_items):
        return scene.capture_items[scene.capture_index].name
    return None


def explicit_path(scene, name: str) -> str:
    """The file ``name``'s row was imported from, or ``""`` for a folder row.

    ``Import Capture`` remembers the picked file (S2): it may live outside the
    capture folder, and the row must keep meaning that exact file.
    """
    index = index_of(scene, name)
    if index is None:
        return ""
    return str(scene.capture_items[index].path or "")


def link_of(scene, bone: str) -> MappingItem | None:
    """The stored link for capture bone ``bone``, or ``None`` when unmapped."""
    for item in scene.mapping_items:
        if item.name == bone:
            return item
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
    bpy.utils.register_class(MappingItem)
    scene = bpy.types.Scene
    scene.capture_items = bpy.props.CollectionProperty(type=CaptureItem)  # type: ignore[attr-defined]
    scene.mapping_items = bpy.props.CollectionProperty(type=MappingItem)  # type: ignore[attr-defined]
    scene.mapping_active = bpy.props.BoolProperty(default=False)  # type: ignore[attr-defined]
    scene.mapping_pending = bpy.props.StringProperty(  # type: ignore[attr-defined]
        default="",
        description="The capture bone picked, waiting for its rig control",
    )
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
        "mapping_pending",
        "mapping_active",
        "mapping_items",
        "target_rig",
        "preview_owner",
        "preview_rest",
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
    bpy.utils.unregister_class(MappingItem)


def report(scene, message: str) -> None:
    """Record a user-facing message on the scene (the panel renders it)."""
    _set_status(scene, message)
