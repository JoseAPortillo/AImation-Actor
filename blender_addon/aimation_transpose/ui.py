"""The transposition panel (S1, S2, S9).

The panel lives in a 3D viewport sidebar and is deliberately reachable from
**either** window: the animator's own, and the viewer window the tool opens. The
viewer window's context scene is the preview scene, which holds none of the tool's
state, so every control is drawn against the owner scene (`props.tool_scene`) —
otherwise the tool looks like it vanished the moment the viewer opened.
"""

from __future__ import annotations

import bpy

from . import mapping, prefs, preview, props

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
        row = box.row()
        row.template_list(
            "AIMATION_UL_captures",
            "",
            scene,
            "capture_items",
            scene,
            "capture_index",
            rows=6,
        )
        # A list the animator cannot prune is a list they stop trusting (S2).
        row.column(align=True).operator("aimation.remove_capture", text="", icon="X")

        viewer = layout.box()
        open_already = preview.viewer_window() is not None
        viewer.label(
            text="3D viewer: open" if open_already else "3D viewer: closed",
            icon="VIEW3D",
        )
        # Playback and scrubbing live on the viewer window's own timeline: the
        # panel deliberately carries no play button and no second frame slider,
        # both would only duplicate what that timeline already does.
        viewer.operator("aimation.open_viewer", text="Open" if open_already else "Open viewer")

        preview_scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
        if preview_scene is None or scene.capture_last <= scene.capture_first:
            viewer.label(text="No capture loaded", icon="INFO")
        else:
            # Bind pose is what mapping shows; while a mapping session owns the
            # pose the toggle would let the animator break the very state the
            # clicks are measured against.
            bind_pose = viewer.row()
            bind_pose.enabled = not scene.mapping_active
            bind_pose.prop(scene, "preview_rest", text="Bind pose", toggle=True)
            if scene.preview_rest:
                # REST does not evaluate animation: without this the frozen
                # skeleton reads as a broken import rather than a chosen mode.
                viewer.label(text="Bind pose freezes the animation", icon="INFO")
                viewer.label(text="Untick it to watch it play.")

        mapping_box = layout.box()
        mapping_box.label(text="Mapping", icon="BONE_DATA")
        rig_field = mapping_box.row()
        # Locked while a session runs: the viewer is showing THIS rig in bind
        # pose, and switching it mid-session would leave the two out of step.
        rig_field.enabled = not scene.mapping_active
        rig_field.prop(scene, "target_rig", text="Rig")
        rig = scene.target_rig
        if rig is None:
            mapping_box.label(text="Pick the rig the animation drives", icon="INFO")
        elif rig.type != "ARMATURE":
            mapping_box.label(text=f"{rig.name} is not an armature", icon="ERROR")

        # A picker with nothing to offer must say why before the animator
        # clicks a bone and gets an empty search field (S9).
        blockage = mapping.problem(scene)
        if blockage:
            mapping_box.label(text=blockage, icon="ERROR")
        else:
            controls = mapping.available(scene)
            mapping_box.label(
                text=f"{controls} control(s) to pick from",
                icon="CHECKMARK",
            )

        linked = len(scene.mapping_items)
        mapping_box.label(
            text=f"{linked} bone(s) linked",
            icon="CHECKMARK" if linked else "DOT",
        )
        missing = mapping.unresolved(scene)
        if missing:
            mapping_box.label(text=f"{missing} link(s) point at missing controls", icon="ERROR")

        if scene.mapping_active:
            if scene.mapping_pending:
                mapping_box.label(
                    text=f"{scene.mapping_pending}: pick its control", icon="TIME"
                )
            else:
                mapping_box.label(text="Click a capture bone in the viewer", icon="INFO")
            if rig is not None:
                mapping_box.label(
                    text=f"{rig.name} is next to the capture, in bind pose",
                    icon="BONE_DATA",
                )
            mapping_box.label(text="Esc or right-click finishes", icon="INFO")
            mapping_box.operator("aimation.finish_mapping", text="Finish", icon="CHECKMARK")
        else:
            mapping_box.operator("aimation.map_bones", text="Map bones", icon="BONE_DATA")

        message = props.status(scene)
        if message:
            layout.label(text=message, icon="INFO")


def register() -> None:
    bpy.utils.register_class(AIMATION_UL_captures)
    bpy.utils.register_class(AIMATION_PT_transpose)


def unregister() -> None:
    bpy.utils.unregister_class(AIMATION_PT_transpose)
    bpy.utils.unregister_class(AIMATION_UL_captures)
