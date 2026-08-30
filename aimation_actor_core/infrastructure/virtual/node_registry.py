"""Static, in-memory node registry (SDD §4.3 — static registration).

Nodes are registered at import time, never from user input. This adapter is
populated once at the composition root and injected where a
:class:`NodeRegistry` is required.
"""

from __future__ import annotations

from pathlib import Path

from aimation_actor_core.domain.pipeline.node import INode
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.domain.pipeline.schema import NodeSchema
from aimation_actor_core.infrastructure.ai_models.pose_2d import Pose2DNode
from aimation_actor_core.infrastructure.video.frame_extractor import (
    FrameExtractorNode,
)
from aimation_actor_core.infrastructure.virtual.nodes import (
    FrameRangeNode,
    MergeNode,
    PassThroughNode,
)


class StaticNodeRegistry(NodeRegistry):
    """An allowlist of statically registered node instances."""

    def __init__(self, nodes: dict[str, INode] | None = None) -> None:
        self._nodes: dict[str, INode] = nodes or {}

    def register(self, node: INode) -> None:
        """Register a node instance under its schema type (idempotent)."""
        node_type = node.get_schema().type
        self._nodes[node_type] = node

    def get(self, node_type: str) -> INode | None:
        return self._nodes.get(node_type)

    def list_schemas(self) -> list[NodeSchema]:
        return [node.get_schema() for node in self._nodes.values()]

    def contains(self, node_type: str) -> bool:
        return node_type in self._nodes


def seeded_node_registry(media_root: Path = Path("media")) -> StaticNodeRegistry:
    """Build a :class:`StaticNodeRegistry` pre-seeded with the built-in nodes.

    Registers the three virtual seed nodes plus the real AI preprocessing
    nodes ``video-source`` and ``pose-2d``. ``media_root`` allowlists the video
    paths that ``video-source`` may read (path allowlist, SDD §4.3).

    Used by the composition root to wire the static allowlist for
    ``GET /nodes/types`` and graph execution (SDD §4.3 — static registration,
    never from user input).
    """
    registry = StaticNodeRegistry()
    registry.register(PassThroughNode())
    registry.register(MergeNode())
    registry.register(FrameRangeNode())
    registry.register(FrameExtractorNode(media_root=media_root))
    registry.register(Pose2DNode())
    return registry
