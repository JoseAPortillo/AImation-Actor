"""Node registry contract (domain/pipeline).

Defines the interface that the node catalog exposes to the API layer
(``/nodes/types``, plan §9.3). The concrete implementation lives in
:mod:`infrastructure` and is injected at the composition root (SDD §2.4),
so ``domain`` and ``api`` never import concrete node implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aimation_actor_core.domain.pipeline.node import INode
from aimation_actor_core.domain.pipeline.schema import NodeSchema


@runtime_checkable
class NodeRegistry(Protocol):
    """Read access to the registered node catalog.

    Nodes are registered statically at import time (SDD §4.3 — never from
    user-supplied input). This protocol exposes the allowlist to callers.
    """

    def get(self, node_type: str) -> INode | None:
        """Return the node instance for a type, or ``None`` if unknown."""
        ...

    def list_schemas(self) -> list[NodeSchema]:
        """Return the schemas of all registered node types (the allowlist)."""
        ...

    def contains(self, node_type: str) -> bool:
        """Whether ``node_type`` is in the registered allowlist."""
        ...
