"""AImation Transpose — retarget captured sparse animation onto a control rig.

The tool is deliberately a thin Blender shell: everything that can be computed
without ``bpy`` lives in a plain module (``captures``, ``clock``) so the
repository's pytest run covers it. The ``bpy`` side is validated with
``blender_addon/tests/headless_smoke.py``, the same policy the application's
FBX read bridge follows.

Specs: ``odd/tasks/blender-transpose.md``.
"""

from __future__ import annotations

from . import operators, prefs, props, ui

_MODULES = (prefs, props, operators, ui)


def register() -> None:
    for module in _MODULES:
        module.register()


def unregister() -> None:
    for module in reversed(_MODULES):
        module.unregister()
