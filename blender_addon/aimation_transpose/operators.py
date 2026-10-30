"""Operators behind the transposition panel (S1, S2, S9).

Every operator reports through :func:`props.report` so the panel can show what
happened instead of the tool failing silently.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper

from . import captures, playback, prefs, preview, props

__all__ = [
    "AIMATION_OT_import_capture",
    "AIMATION_OT_open_viewer",
    "AIMATION_OT_refresh_captures",
    "AIMATION_OT_toggle_preview",
]


def _capture_folder(context) -> str:
    """The configured capture folder as an absolute path, or ``""``."""
    preferences = prefs.preferences(context)
    if preferences is None:
        return ""
    return bpy.path.abspath(preferences.capture_folder)


def _adopt_folder(context, folder: str) -> None:
    """Persist ``folder`` and rebuild the list from it (S2).

    The preference update callback already refreshes, but only when the value
    actually changed. Refreshing unconditionally keeps the list correct when the
    animator re-picks the same folder after adding files to it.
    """
    preferences = prefs.preferences(context)
    if preferences is not None:
        preferences.capture_folder = folder
    props.refresh_captures(context.scene, context)


def _select(scene, name: str) -> bool:
    for index, item in enumerate(scene.capture_items):
        if item.name == name:
            scene.capture_index = index
            return True
    return False


class AIMATION_OT_refresh_captures(bpy.types.Operator):
    bl_idname = "aimation.refresh_captures"
    bl_label = "Refresh Captures"
    bl_description = "Re-read the capture folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        count = props.refresh_captures(scene, context)
        folder = _capture_folder(context)
        if not folder:
            props.report(scene, "Set a capture folder first")
        elif count:
            props.report(scene, f"{count} capture(s) in {folder}")
        else:
            props.report(scene, f"No .fbx captures found in {folder}")
        return {"FINISHED"}


class AIMATION_OT_import_capture(bpy.types.Operator, ImportHelper):
    bl_idname = "aimation.import_capture"
    bl_label = "Import Capture"
    bl_description = "Pick a capture FBX; its folder becomes the capture folder"
    bl_options = {"REGISTER"}

    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="*.fbx", options={"HIDDEN"}, maxlen=255
    )

    def invoke(self, context, event):
        folder = _capture_folder(context)
        if folder and Path(folder).is_dir():
            # A trailing separator opens the browser *inside* that folder.
            self.filepath = str(Path(folder) / "")
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        scene = context.scene
        path = Path(bpy.path.abspath(self.filepath))
        if path.suffix.lower() != captures.CAPTURE_SUFFIX:
            props.report(scene, f"Not a capture file: {path.name}")
            self.report({"WARNING"}, f"Not a capture file: {path.name}")
            return {"CANCELLED"}
        if not path.is_file():
            props.report(scene, f"Capture not found: {path.name}")
            self.report({"WARNING"}, f"Capture not found: {path.name}")
            return {"CANCELLED"}

        _adopt_folder(context, str(path.parent))
        if not _select(scene, path.name):
            props.report(scene, f"{path.name} did not appear in the capture list")
            self.report({"WARNING"}, f"{path.name} did not appear in the capture list")
            return {"CANCELLED"}

        # The index change already schedules a load; scheduling again is the
        # no-op-safe path for re-picking the row that was already selected.
        preview.schedule_load(scene.name, path.name)
        props.report(scene, f"Importing {path.name}")
        return {"FINISHED"}


class AIMATION_OT_open_viewer(bpy.types.Operator):
    bl_idname = "aimation.open_viewer"
    bl_label = "Open 3D Viewer"
    bl_description = "Open the isolated preview window; the capture never enters your viewport"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        name = props.selected_name(scene)
        if preview.source_armature() is None and name is not None:
            preview.schedule_load(scene.name, name)
        ok, message = preview.open_window()
        props.report(scene, message)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class AIMATION_OT_toggle_preview(bpy.types.Operator):
    bl_idname = "aimation.toggle_preview"
    bl_label = "Play/Pause"
    bl_description = "Play or pause the capture on the viewer's own clock"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        if preview.source_armature() is None:
            message = "Load a capture before playing it"
            props.report(scene, message)
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        if scene.preview_playing:
            playback.stop()
            scene.preview_playing = False
            props.report(scene, "Paused")
            return {"FINISHED"}

        if scene.capture_last <= scene.capture_first:
            message = "The capture holds a single frame; there is nothing to play"
            props.report(scene, message)
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        # Watching the animation means watching the pose, not the bind pose.
        scene.preview_rest = False
        scene.preview_playing = True
        playback.start(scene)
        props.report(scene, "Playing")
        return {"FINISHED"}


_OPERATORS = (
    AIMATION_OT_refresh_captures,
    AIMATION_OT_import_capture,
    AIMATION_OT_open_viewer,
    AIMATION_OT_toggle_preview,
)


def register() -> None:
    for operator in _OPERATORS:
        bpy.utils.register_class(operator)


def unregister() -> None:
    for operator in reversed(_OPERATORS):
        bpy.utils.unregister_class(operator)
