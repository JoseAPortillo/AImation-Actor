"""Sidebar panel for the AImation Actor add-on (bpy glue).

Spec §7.1: ``VIEW3D_PT_AImationActor`` in the 3D Viewport sidebar. The
sidebar tab is ``AiMation`` (the add-on category stays ``Animation`` per the
spec's bl_info §10.2 — the spec defines no sidebar tab string, only the panel
id name).
"""

from __future__ import annotations

import bpy


class VIEW3D_PT_AImationActor(bpy.types.Panel):
    """3D Viewport sidebar panel: video source, run/stop, status."""

    bl_idname = "VIEW3D_PT_AImationActor"
    bl_label = "AImation Actor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AiMation"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Show only when a scene is available."""
        return context.scene is not None

    def draw(self, context: bpy.types.Context) -> None:
        """Draw the panel layout (spec §7.1: source, generate, status)."""
        props = context.scene.aimation_actor
        layout = self.layout

        box = layout.box()
        box.label(text="Core Connection", icon="LINKED")
        box.prop(props, "core_url")
        box.prop(props, "session_name")

        box = layout.box()
        box.label(text="Source", icon="FILE_MOVIE")
        box.prop(props, "video_path")

        run_row = layout.row(align=True)
        run_row.operator("aimation.run_video", icon="PLAY", text="Run Video to Motion")
        layout.row(align=True).operator("aimation.stop_job", icon="CANCEL", text="Stop Job")

        if props.job_id:
            layout.label(text=f"job: {props.job_id}", icon="KEYFRAME")

        status_row = layout.row()
        status_row.label(text="Status", icon="INFO")
        status_row = layout.row()
        status_row.prop(props, "status", text="")
        if props.status.startswith("ERROR"):
            status_row.alert = True
        elif props.status.startswith("RUNNING"):
            status_row.enabled = False