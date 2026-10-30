"""The add-on's persistent settings.

The capture folder lives in the preferences, not in the scene: it describes the
machine's capture output directory and should survive across ``.blend`` files.
"""

from __future__ import annotations

import bpy

__all__ = ["CAPTURE_FOLDER_DEFAULT", "AImationPreferences", "preferences"]

#: Blender-relative default; the animator points it at the application's export
#: folder on first use (the Import Capture button does that implicitly).
CAPTURE_FOLDER_DEFAULT = "//captures"


def _on_folder(_self, context) -> None:
    from . import props

    # The folder field can be drawn from either window, so the scene it should
    # refresh is the owner, not necessarily the context scene.
    owner = props.tool_scene(context)
    if owner is None:
        return
    props.refresh_captures(owner, context)


class AImationPreferences(bpy.types.AddonPreferences):
    """The add-on's settings block in Blender's preferences."""

    bl_idname = __package__ or ""

    capture_folder: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Capture folder",
        description="Folder holding the FBX captures exported by AImation Actor",
        subtype="DIR_PATH",
        default=CAPTURE_FOLDER_DEFAULT,
        update=_on_folder,
    )

    def draw(self, context) -> None:
        self.layout.prop(self, "capture_folder")


def preferences(context=None) -> AImationPreferences | None:
    """The live preferences instance, or ``None`` when the add-on is disabled."""
    ctx = context if context is not None else bpy.context
    addons = getattr(getattr(ctx, "preferences", None), "addons", None)
    if addons is None:
        return None
    entry = addons.get(__package__ or "")
    return None if entry is None else entry.preferences


def register() -> None:
    bpy.utils.register_class(AImationPreferences)


def unregister() -> None:
    bpy.utils.unregister_class(AImationPreferences)
