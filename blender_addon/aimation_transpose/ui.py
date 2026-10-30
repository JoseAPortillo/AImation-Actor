"""The transposition panel (S1, S2, S9).

The panel lives in the animator's 3D viewport sidebar, but it never shows the
capture there: the viewer is its own window and its own scene. The frame slider
is drawn from the *preview* scene's ``frame_current``, whose range the import
sets — that keeps one source of truth and gives a real slider without dynamic
RNA min/max gymnastics.
"""

from __future__ import annotations

import bpy

from . import prefs, props

__all__ = ["AIMATION_PT_transpose", "AIMATION_UL_captures"]


class AIMATION_UL_captures(bpy.types.UIList):
    """One row per capture FBX found in the capture folder (S2)."""

    bl_idname = "AIMATION_UL_captures"

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index, flt_flag
    ):
        loaded = item.name == getattr(data, "capture_loaded", "")
        layout.label(text=item.name, icon="CHECKMARK" if loaded else "DOT")


class AIMATION_PT_transpose(bpy.types.Panel):
    bl_idname = "AIMATION_PT_transpose"
    bl_label = "Transpose"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AImation"

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        # The preview window shows its own scene; the panel belongs to the
        # animator's scene, not there (S1).
        return scene is not None and scene.name != props.PREVIEW_SCENE

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        preferences = prefs.preferences(context)

        if preferences is None:
            layout.label(text="Add-on preferences are unavailable", icon="ERROR")
        else:
            column = layout.column(align=True)
            column.label(text="Capture folder", icon="FILE_FOLDER")
            row = column.row(align=True)
            row.prop(preferences, "capture_folder", text="")
            row.operator("aimation.refresh_captures", text="", icon="FILE_REFRESH")
        layout.operator("aimation.import_capture", icon="IMPORT")

        box = layout.box()
        box.label(text="Captures", icon="PRESET")
        box.template_list(
            "AIMATION_UL_captures",
            "",
            scene,
            "capture_items",
            scene,
            "capture_index",
            rows=6,
        )

        layout.operator("aimation.open_viewer", icon="VIEW3D")

        preview_scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
        if preview_scene is None or scene.capture_last <= scene.capture_first:
            layout.label(text="No capture loaded", icon="INFO")
        else:
            row = layout.row(align=True)
            playing = scene.preview_playing
            row.operator(
                "aimation.toggle_preview",
                text="Pause" if playing else "Play",
                icon="PAUSE" if playing else "PLAY",
            )
            row.prop(scene, "preview_rest", text="Rest", toggle=True)
            layout.prop(preview_scene, "frame_current", text="Frame", slider=True)

        message = props.status(scene)
        if message:
            layout.label(text=message, icon="INFO")


def register() -> None:
    bpy.utils.register_class(AIMATION_UL_captures)
    bpy.utils.register_class(AIMATION_PT_transpose)


def unregister() -> None:
    bpy.utils.unregister_class(AIMATION_PT_transpose)
    bpy.utils.unregister_class(AIMATION_UL_captures)
