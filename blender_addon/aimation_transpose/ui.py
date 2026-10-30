"""The transposition panel (S1, S2, S9).

The panel lives in a 3D viewport sidebar and is deliberately reachable from
**either** window: the animator's own, and the viewer window the tool opens. The
viewer window's context scene is the preview scene, which holds none of the tool's
state, so every control is drawn against the owner scene (`props.tool_scene`) —
otherwise the tool looks like it vanished the moment the viewer opened.
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
        # Reachable in the viewer window too: there the state lives on the
        # preview scene's owner, not on the context scene.
        return props.tool_scene(context) is not None

    def draw(self, context):
        layout = self.layout
        scene = props.tool_scene(context)
        if scene is None:  # poll guarantees this, but a stale redraw can beat it
            return
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
            row.prop(scene, "preview_rest", text="Bind pose", toggle=True)
            layout.prop(preview_scene, "frame_current", text="Frame", slider=True)
            if scene.preview_rest:
                # REST does not evaluate animation: without this the frozen
                # skeleton reads as a broken import rather than a chosen mode.
                layout.label(text="Bind pose freezes the animation", icon="INFO")
                layout.label(text="Untick it to watch it play.")

        message = props.status(scene)
        if message:
            layout.label(text=message, icon="INFO")


def register() -> None:
    bpy.utils.register_class(AIMATION_UL_captures)
    bpy.utils.register_class(AIMATION_PT_transpose)


def unregister() -> None:
    bpy.utils.unregister_class(AIMATION_PT_transpose)
    bpy.utils.unregister_class(AIMATION_UL_captures)
