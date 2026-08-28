"""Node catalog schema — the metadata contract for graph nodes.

Belongs to the ``domain/pipeline`` layer (SDD §2.2). Pure Python + Pydantic.
This schema is the single source of truth that the Tauri/React Flow catalog
and the ``/nodes/types`` endpoint (plan §9.3) consume. Per Sub_Agents.md §4.3,
node types MUST stay in sync between TypeScript and Python.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NodeCategory(StrEnum):
    """Top-level grouping of nodes in the palette (plan §8.3)."""

    SOURCE = "source"
    AI = "ai"
    CLEANUP = "cleanup"
    RIGGING = "rigging"
    OUTPUT = "output"
    LOGIC = "logic"


class DataType(StrEnum):
    """Typed link between ports; incompatible types cannot connect (plan §8.5).

    The Tauri/React Flow frontend uses these to gate connection validity.
    """

    FRAMES = "frames"                      #: Extracted video frames.
    FRAME_STREAM = "frame_stream"          #: Live/streaming frame pipe.
    KEYPOINTS_2D = "keypoints_2d"          #: Per-frame 2D pose keypoints.
    POSE_3D = "pose_3d"                    #: Per-frame 3D pose.
    NEUTRAL_POSE = "neutral_pose"          #: A single neutral pose (domain Pose).
    NEUTRAL_ANIMATION = "neutral_animation"  #: A NeutralMotion document.
    VIDEO_PATH = "video_path"              #: Reference video file path.
    IMAGE = "image"                        #: A single image/frame.
    MESH = "mesh"                          #: 3D mesh data.
    GRAPH = "graph"                        #: A node graph (e.g. subgraph/macro).
    BOOLEAN = "boolean"
    NUMBER = "number"
    STRING = "string"
    ANY = "any"


class PortSpec(BaseModel):
    """A typed input, output, or parameter of a node.

    Attributes:
        name: Identifier for the port (matches the handle in React Flow and
            the key in the node's inputs/params dicts).
        data_type: :class:`DataType` governing connection/param typing.
        required: Whether the port must be connected/provided.
        default: Optional static default value for parameters.
        description: Human-readable purpose.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    data_type: DataType
    required: bool = True
    default: str | int | float | bool | None = None
    description: str = Field(default="")


class NodeSchema(BaseModel):
    """Static description of a node type registered in the catalog.

    Attributes:
        type: Unique node type identifier, e.g. ``"Pose2DDetector"``.
        category: :class:`NodeCategory` grouping.
        title: Human-readable display name.
        description: What the node does (auto-catalog, SDD §3.4).
        inputs: Typed input ports.
        outputs: Typed output ports.
        params: Typed configurable parameters (the node properties panel).
    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(min_length=1)
    category: NodeCategory
    title: str = Field(min_length=1)
    description: str = Field(default="")
    inputs: list[PortSpec] = Field(default_factory=list)
    outputs: list[PortSpec] = Field(default_factory=list)
    params: list[PortSpec] = Field(default_factory=list)
