"""Pure, bpy-free core for the AImation Actor Blender add-on.

This package must import under a plain Python interpreter (pytest): it uses
only the standard library and never imports ``bpy``.

- :mod:`blender_addon.core.config`       defaults + URL/token policy
- :mod:`blender_addon.core.http`         transport abstraction over urllib
- :mod:`blender_addon.core.client`       typed Core REST client
- :mod:`blender_addon.core.session`      session lifecycle (register/heartbeat/deregister)
- :mod:`blender_addon.core.motion_prep`  NeutralMotion -> bake-ready payloads
"""

from __future__ import annotations