"""Static, in-memory node registry (SDD §4.3 — static registration).

Nodes are registered at import time, never from user input. This adapter is
populated once at the composition root and injected where a
:class:`NodeRegistry` is required.
"""

from __future__ import annotations

from aimation_actor_core.domain.pipeline.node import INode
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.domain.pipeline.schema import NodeSchema


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
