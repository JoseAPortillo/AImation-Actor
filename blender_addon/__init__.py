"""AImation Actor — Blender add-on v0.1.

Lightweight HTTP client add-on that talks to the AImation Actor Core
(see ``docs/Plan_DCC_Blender.md``). This slice delivers the v0.1 core loop:
panel -> HTTP to core -> submit video job -> poll result -> create armature
and bake keyframes from the NeutralMotion JSON.

Package layout:

- ``blender_addon.core``   bpy-free pure Python (HTTP client, session
  lifecycle, motion prep) — importable under plain pytest.
- ``blender_addon.ui``     bpy glue: property group, sidebar panel, operators.
- ``blender_addon.rig``    bpy glue: armature build + keyframe baker.

bpy is NEVER imported at module top level here so that
``import blender_addon.core.client`` works in a plain (non-Blender) Python
interpreter; the bpy-glue submodules are imported lazily inside
:func:`register` / :func:`unregister` (docs/Plan_DCC_Blender.md §10.2).
"""

from __future__ import annotations

bl_info = {
    "name": "AImation Actor",
    "author": "AImation Team",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > AImation Actor",
    "description": "AI-assisted character animation via the local AImation Actor Core",
    "category": "Animation",
    "support": "COMMUNITY",
}


def register() -> None:
    """Register the add-on: UI glue (properties, panel, operators) + rig tools.

    Deferred imports keep this package importable without Blender; the
    submodules are imported here for the first time, which is safe because
    this function only ever runs inside Blender.
    """
    from blender_addon import rig, ui

    ui.register()
    rig.register()


def unregister() -> None:
    """Unregister the add-on in reverse order of registration."""
    from blender_addon import rig, ui

    rig.unregister()
    ui.unregister()