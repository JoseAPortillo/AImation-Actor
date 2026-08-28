"""Synchronous in-request graph executor adapter (graph-execution capability).

Implements the domain :class:`GraphExecutor` protocol with a synchronous driver
over async node coroutines (ADR-002): validate, topologically sort, then run
each node's ``execute`` coroutine in dependency order, bounding each with a
per-node timeout and aggregating outputs and log lines.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from aimation_actor_core.domain.pipeline.executor import GraphExecutionResult, GraphExecutor
from aimation_actor_core.domain.pipeline.graph import (
    Edge,
    Graph,
    GraphNode,
    topological_sort,
    validate_graph,
)
from aimation_actor_core.domain.pipeline.node import ExecutionContext, NodeOutput
from aimation_actor_core.domain.pipeline.registry import NodeRegistry


class GraphValidationError(Exception):
    """Raised when the graph fails domain validation before any node runs."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class NodeExecutionError(Exception):
    """Raised when a node fails during execution (downstream nodes never run)."""

    def __init__(self, node_id: str, reason: str) -> None:
        self.node_id = node_id
        self.reason = reason
        super().__init__(f"node {node_id} failed: {reason}")


class NodeTimeoutError(NodeExecutionError):
    """Raised when a node exceeds its per-node execution budget (SDD §4.3)."""

    def __init__(self, node_id: str, timeout_s: float) -> None:
        super().__init__(node_id, f"timed out after {timeout_s}s")


class SynchronousGraphExecutor(GraphExecutor):
    """Drive a validated :class:`Graph` to completion in topological order."""

    def __init__(self, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    async def run(
        self,
        graph: Graph,
        registry: NodeRegistry,
        *,
        trace_id: str | None = None,
    ) -> GraphExecutionResult:
        validation = validate_graph(graph, registry)
        if not validation.valid:
            raise GraphValidationError(validation.errors)

        order = topological_sort(graph)
        nodes_by_id: dict[str, GraphNode] = {node.id: node for node in graph.nodes}
        incoming: dict[str, list[Edge]] = {node.id: [] for node in graph.nodes}
        for edge in graph.edges:
            incoming[edge.target.node].append(edge)

        run_trace = trace_id or uuid.uuid4().hex
        outputs: dict[str, Any] = {}
        logs: list[str] = []

        for node_id in order:
            graph_node = nodes_by_id[node_id]
            node = registry.get(graph_node.type)
            if node is None:
                # validate_graph guarantees the allowlist, so this is defensive.
                raise GraphValidationError([f"unknown node type: {graph_node.type}"])
            inputs = {
                edge.target.port: outputs[edge.source.node][edge.source.port]
                for edge in incoming[node_id]
            }
            context = ExecutionContext(trace_id=run_trace, timeout_s=self._timeout_s)
            try:
                output: NodeOutput = await asyncio.wait_for(
                    node.execute(inputs, graph_node.params, context),
                    timeout=self._timeout_s,
                )
            except TimeoutError as exc:
                raise NodeTimeoutError(node_id, self._timeout_s) from exc
            except Exception as exc:
                raise NodeExecutionError(node_id, str(exc)) from exc
            outputs[node_id] = output.values
            logs.append(f"executed {node_id} ({graph_node.type})")

        return GraphExecutionResult(outputs=outputs, logs=logs)
