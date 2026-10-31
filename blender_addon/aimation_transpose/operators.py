"""Operators behind the transposition panel (S1, S2, S9).

Every operator reports through :func:`props.report` so the panel can show what
happened instead of the tool failing silently.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper

from . import captures, prefs, preview, props

__all__ = [
    "AIMATION_OT_import_capture",
    "AIMATION_OT_open_viewer",
    "AIMATION_OT_refresh_captures",
]


def _capture_folder(context) -> str:
    """The configured capture folder as an absolute path, or ``""``."""
    preferences = prefs.preferences(context)
    if preferences is None:
        return ""
    return bpy.path.abspath(preferences.capture_folder)


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
        scene = props.tool_scene(context)
        if scene is None:  # a viewer window with no owner has no state to drive
            message = "This viewer window is not bound to a working scene"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
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
    bl_description = (
        "Add one capture FBX to the list and load it; the capture folder above "
        "is left alone (it is for importing a whole folder)"
    )
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
        scene = props.tool_scene(context)
        if scene is None:  # a viewer window with no owner has no state to drive
            message = "This viewer window is not bound to a working scene"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        path = Path(bpy.path.abspath(self.filepath))
        if path.suffix.lower() != captures.CAPTURE_SUFFIX:
            props.report(scene, f"Not a capture file: {path.name}")
            self.report({"WARNING"}, f"Not a capture file: {path.name}")
            return {"CANCELLED"}
        if not path.is_file():
            props.report(scene, f"Capture not found: {path.name}")
            self.report({"WARNING"}, f"Capture not found: {path.name}")
            return {"CANCELLED"}

        # One picked file, and only that file, joins the list (S2). Its folder
        # is deliberately NOT adopted: the capture folder field is the
        # whole-folder workflow, and repointing it here would fill the list
        # with captures the animator never asked for.
        folder = _capture_folder(context)
        inside_folder = bool(folder) and path.parent == Path(folder)
        row = next(
            (item for item in scene.capture_items if item.name == path.name), None
        )
        if row is None:
            row = scene.capture_items.add()
            row.name = path.name
        # A folder row already resolves to this file when it lives in the
        # folder; otherwise the row must remember exactly which file was picked.
        row.path = "" if inside_folder else str(path)

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
        scene = props.tool_scene(context)
        if scene is None:  # a viewer window with no owner has no state to drive
            message = "This viewer window is not bound to a working scene"
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        name = props.selected_name(scene)
        if preview.source_armature() is None and name is not None:
            preview.schedule_load(scene.name, name)
        ok, message = preview.open_window()
        props.report(scene, message)
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


_OPERATORS = (
    AIMATION_OT_refresh_captures,
    AIMATION_OT_import_capture,
    AIMATION_OT_open_viewer,
)


def register() -> None:
    for operator in _OPERATORS:
        bpy.utils.register_class(operator)


def unregister() -> None:
    for operator in reversed(_OPERATORS):
        bpy.utils.unregister_class(operator)
