"""Blender UI glue: property group, sidebar panel and operators (bpy required).

- :mod:`blender_addon.ui.properties`  AImationActorProps PropertyGroup
- :mod:`blender_addon.ui.panel`       VIEW3D_PT_AImationActor sidebar panel
- :mod:`blender_addon.ui.operators`   run/stop job operators + timers
"""

from __future__ import annotations

from blender_addon import compat


def register() -> None:
    """Register UI classes: property group, operators, panel, scene props."""
    from blender_addon.ui import operators, panel, properties

    compat.register_class(properties.AImationActorProps)
    compat.register_class(operators.AIMATION_OT_run_video)
    compat.register_class(operators.AIMATION_OT_stop_job)
    compat.register_class(panel.VIEW3D_PT_AImationActor)
    properties.register_scene_props()


def unregister() -> None:
    """Stop jobs/timers, then unregister classes in reverse order."""
    from blender_addon.ui import operators, panel, properties

    operators.cleanup_jobs()
    properties.unregister_scene_props()
    compat.unregister_class(panel.VIEW3D_PT_AImationActor)
    compat.unregister_class(operators.AIMATION_OT_stop_job)
    compat.unregister_class(operators.AIMATION_OT_run_video)
    compat.unregister_class(properties.AImationActorProps)