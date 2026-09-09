"""Blender rig glue: armature build + keyframe baking (bpy required).

- :mod:`blender_addon.rig.armature`  ``ensure_armature()`` from the neutral skeleton
- :mod:`blender_addon.rig.baker`     ``bake_motion()`` keyframe insertion

``register()`` / ``unregister()`` are no-ops in this slice (no rig classes
to register yet).
"""

from __future__ import annotations


def register() -> None:
    """Placeholder: nothing to register in the rig package yet."""


def unregister() -> None:
    """Placeholder: nothing to unregister in the rig package yet."""