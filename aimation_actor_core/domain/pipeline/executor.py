"""Graph executor contract (graph-execution capability).

Defines the :class:`GraphExecutor` domain protocol and the
:class:`GraphExecutionResult` it produces. The concrete synchronous adapter
lives in :mod:`infrastructure` (Approach 2), so ``domain`` never depends on
concrete execution.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from aimation_actor_core.domain.pipeline.graph import Graph
from aimation_actor_core.domain.pipeline.registry import NodeRegistry


class GraphExecutionResult(BaseModel):
    """Aggregated outcome of a graph run.

    Attributes:
        outputs: Terminal node outputs keyed by node id.
        logs: Ordered per-node log lines accumulated during execution.
    """

    outputs: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)


class GraphExecutor(Protocol):
    """Contract for executing a validated :class:`Graph` (SDD §5.1).

    Implementations are responsible for validation, topological dispatch,
    timeouts, failure isolation, and result/log aggregation.
    """

    async def run(self, graph: Graph, registry: NodeRegistry) -> GraphExecutionResult:
        """Execute ``graph`` against ``registry`` and return the aggregated result."""
        ...
