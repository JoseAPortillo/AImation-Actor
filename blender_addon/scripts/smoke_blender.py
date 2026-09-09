"""Headless Blender smoke test for the add-on's bpy glue (runs inside Blender).

Usage:
    blender --background --python blender_addon/scripts/smoke_blender.py

Verifies: module import, bl_info, registration, scene props, operator
registration, panel class, and (optionally) a live Core health ping. Exit
code 0 + ``SMOKE_OK`` on success, non-zero + ``SMOKE_FAIL`` otherwise.
"""

from __future__ import annotations

import pathlib
import sys

SMOKE_OK = "SMOKE_OK"
SMOKE_FAIL = "SMOKE_FAIL"


def main() -> int:
    """Register the add-on, run assertions, print the verdict, unregister."""
    # Repo root = the folder CONTAINING the blender_addon package
    # (smoke_blender.py -> scripts -> blender_addon -> repo root).
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import bpy

    from blender_addon import bl_info, register, unregister
    from blender_addon.ui.operators import AIMATION_OT_run_video, AIMATION_OT_stop_job
    from blender_addon.ui.panel import VIEW3D_PT_AImationActor

    try:
        register()

        assert bl_info["version"] == (0, 1, 0), f"bl_info version is {bl_info['version']}"
        assert hasattr(bpy.types.Scene, "aimation_actor"), "Scene.aimation_actor missing"
        props = bpy.context.scene.aimation_actor
        assert props.core_url.startswith("http://127.0.0.1"), "core_url default wrong"

        # Operators must be reachable under their bl_idnames.
        run_op = getattr(bpy.ops, AIMATION_OT_run_video.bl_idname)
        stop_op = getattr(bpy.ops, AIMATION_OT_stop_job.bl_idname)
        assert run_op is not None and stop_op is not None

        panel_cls = bpy.types.Panel.bl_rna_get_subclass_py(VIEW3D_PT_AImationActor.bl_idname)
        assert panel_cls is not None, f"{VIEW3D_PT_AImationActor.bl_idname} not registered"
        assert panel_cls.bl_category == "AiMation"
        assert panel_cls.bl_space_type == "VIEW_3D"

        # Optional live health ping against the Core (server may be offline).
        from blender_addon.core import config
        from blender_addon.core.client import CoreClient
        from blender_addon.core.http import UrllibTransport

        client = CoreClient(UrllibTransport(config.CORE_URL), base_url=config.CORE_URL)
        healthy = client.health()
        print(f"core health at {config.CORE_URL}: {'online' if healthy else 'offline'}")

        print(SMOKE_OK)
        return 0
    except AssertionError as exc:
        print(f"{SMOKE_FAIL}: assertion failed: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any import/register error
        print(f"{SMOKE_FAIL}: {type(exc).__name__}: {exc}")
        return 1
    finally:
        unregister()


if __name__ == "__main__":
    sys.exit(main())