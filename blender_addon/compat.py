"""Blender version compatibility shims (spec §2.1 ``utils/compat.py``).

Minimal on purpose: this slice targets Blender 4.2+, where the modern class
registration API (``bpy.utils.register_class`` / ``unregister_class``) is
stable. The helpers here make re-registration (F8 script reload) safer and
centralize the version checks.

This module requires ``bpy`` — it is bpy glue, never pure core.
"""

from __future__ import annotations

import bpy


def blender_version() -> tuple[int, int, int]:
    """Return the running Blender version as ``(major, minor, patch)``."""
    return (bpy.app.version[0], bpy.app.version[1], bpy.app.version[2])


def register_class(cls: type) -> None:
    """Register ``cls`` with Blender, tolerating an already-registered class.

    Re-running ``register()`` after an F8 reload raises ``ValueError`` in
    stock Blender; this shim swallows that specific error so registration is
    idempotent.
    """
    try:
        bpy.utils.register_class(cls)
    except ValueError:
        pass


def unregister_class(cls: type) -> None:
    """Unregister ``cls``, tolerating a class that was never registered."""
    try:
        bpy.utils.unregister_class(cls)
    except ValueError:
        pass