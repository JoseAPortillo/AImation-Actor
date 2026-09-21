"""UI property group for the AImation Actor add-on (bpy glue).

Holds only user-visible settings and transient status. NO secrets: the
session token never touches these (or any) properties (spec §3.3 / §8.1).
The extra ``job_id`` field exists so the Stop button can address the running
job.
"""

from __future__ import annotations

import bpy

from blender_addon.core import config


class AImationActorProps(bpy.types.PropertyGroup):
    """Property group exposed as ``scene.aimation_actor``."""

    video_path: bpy.props.StringProperty(
        name="Video",
        description="Video file to convert to motion",
        subtype="FILE_PATH",
        default="",
        maxlen=1024,
    )

    status: bpy.props.StringProperty(
        name="Status",
        description="Last job status / message",
        default="Idle",
        maxlen=512,
    )

    core_url: bpy.props.StringProperty(
        name="Core URL",
        description="AImation Actor Core base URL (loopback only)",
        default=config.CORE_URL,
        maxlen=1024,
    )

    session_name: bpy.props.StringProperty(
        name="Session Name",
        description="DCC session name registered with the Core",
        default=config.DEFAULT_SESSION_NAME,
        maxlen=128,
    )

    job_id: bpy.props.StringProperty(
        name="Job ID",
        description="Current job identifier (for stop/cancel)",
        default="",
        maxlen=128,
    )


def register_scene_props() -> None:
    """Attach the property group to Scene (custom prop hook, not secrets)."""
    bpy.types.Scene.aimation_actor = bpy.props.PointerProperty(type=AImationActorProps)


def unregister_scene_props() -> None:
    """Detach the property group from Scene."""
    if hasattr(bpy.types.Scene, "aimation_actor"):
        del bpy.types.Scene.aimation_actor