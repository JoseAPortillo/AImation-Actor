"""Graph payload contract and DAG validation (graph-model capability).

Owns the canonical :class:`Graph`/``GraphNode``/``Edge``/``PortRef`` models
aligned with the future ``.aimgraph`` format (ADR-001), plus pure domain
validation: unique ids, dangling-edge rejection, cycle detection via
topological sort, port-type compatibility, and node allowlisting (SDD §4.3).

Pure domain layer — depends only on Pydantic, the standard library, and the
existing ``domain/pipeline`` contracts (``schema``, ``node``, ``registry``).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.domain.pipeline.node import ValidationResult
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.domain.pipeline.schema import DataType, PortSpec


class GraphCycleError(ValueError):
    """Raised when a directed cycle is detected during topological ordering."""


class PortRef(BaseModel):
    """A reference to a named port on a specific node within the graph.

    Attributes:
        node: The node id owning the port.
        port: The port name on that node.
    """

    model_config = ConfigDict(frozen=True)

    node: str = Field(min_length=1)
    port: str = Field(min_length=1)


class Edge(BaseModel):
    """A directed connection between an output port and an input port.

    Attributes:
        id: Non-empty edge identifier.
        source: The source (output) :class:`PortRef`.
        target: The destination (input) :class:`PortRef`.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    source: PortRef
    target: PortRef


class GraphNode(BaseModel):
    """A single node instance within a :class:`Graph`.

    Attributes:
        id: Unique, non-empty node identifier.
        type: The allowlisted node type this instance instantiates.
        params: Optional validated parameter values keyed by param name.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class Graph(BaseModel):
    """A validated node-graph payload aligned with ``.aimgraph`` (ADR-001).

    Attributes:
        version: Graph format version string.
        nodes: The node instances in the graph.
        edges: The directed connections between node ports.
    """

    model_config = ConfigDict(extra="allow")

    version: str = Field(min_length=1)
    nodes: list[GraphNode]
    edges: list[Edge] = Field(default_factory=list)


def ports_compatible(source: DataType, target: DataType) -> bool:
    """Whether two :class:`DataType` values may be connected.

    Compatibility follows D6: equal types, or either side typed ``ANY``
    (a universal relay).
    """
    return source == target or source == DataType.ANY or target == DataType.ANY


def topological_sort(graph: Graph) -> list[str]:
    """Return node ids in topological (execution) order via Kahn's algorithm.

    Every node id appears exactly once, ordered such that each edge points from
    an earlier to a later node.

    Args:
        graph: The graph to order.

    Returns:
        The node ids in a valid topological order.

    Raises:
        GraphCycleError: If the graph is not a DAG (contains a cycle).
    """
    node_ids = {node.id for node in graph.nodes}
    indegree: dict[str, int] = {node.id: 0 for node in graph.nodes}
    adjacency: dict[str, list[str]] = {node.id: [] for node in graph.nodes}

    for edge in graph.edges:
        source = edge.source.node
        target = edge.target.node
        # Dangling edges are a separate concern handled by ``validate_graph``.
        if source not in node_ids or target not in node_ids:
            continue
        adjacency[source].append(target)
        indegree[target] += 1

    ready = deque(node.id for node in graph.nodes if indegree[node.id] == 0)
    order: list[str] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for neighbor in adjacency[current]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                ready.append(neighbor)

    if len(order) != len(graph.nodes):
        raise GraphCycleError("graph contains a directed cycle")
    return order


def _node_type(graph: Graph, node_id: str) -> str | None:
    for node in graph.nodes:
        if node.id == node_id:
            return node.type
    return None


def _port_data_type(ports: list[PortSpec], port_name: str) -> DataType | None:
    for port in ports:
        if port.name == port_name:
            return port.data_type
    return None


def validate_graph(graph: Graph, registry: NodeRegistry) -> ValidationResult:
    """Validate a graph against the domain rules, collecting all errors.

    Checks, in order: duplicate node ids, dangling edge references, cycle
    detection, node-type allowlisting, and port-type compatibility. Unknown
    node types and incompatible connections are rejected before execution.

    Args:
        graph: The graph to validate.
        registry: The allowlist registry used for type and port resolution.

    Returns:
        A :class:`ValidationResult`; ``valid`` is ``True`` only when the graph
        is a fully valid DAG whose nodes are allowlisted and whose ports match.
    """
    errors: list[str] = []

    # 1. Unique node ids.
    counts: dict[str, int] = {}
    for node in graph.nodes:
        counts[node.id] = counts.get(node.id, 0) + 1
    for node_id, count in counts.items():
        if count > 1:
            errors.append(f"duplicate node id: {node_id}")

    # 2. Dangling edge references.
    node_ids = {node.id for node in graph.nodes}
    for edge in graph.edges:
        for ref in (edge.source, edge.target):
            if ref.node not in node_ids:
                errors.append(f"edge {edge.id} references missing node: {ref.node}")

    # 3. Cycle detection.
    try:
        topological_sort(graph)
    except GraphCycleError:
        errors.append("graph contains a cycle")

    # 4. Node-type allowlist (collect every unknown type).
    for node in graph.nodes:
        if not registry.contains(node.type):
            errors.append(f"unknown node type: {node.type}")

    # 5. Port-type compatibility.
    for edge in graph.edges:
        src_type = _node_type(graph, edge.source.node)
        dst_type = _node_type(graph, edge.target.node)
        if src_type is None or dst_type is None:
            continue  # dangling edge already reported
        src_node = registry.get(src_type)
        dst_node = registry.get(dst_type)
        if src_node is None or dst_node is None:
            continue  # unknown type already reported
        src_dt = _port_data_type(src_node.get_schema().outputs, edge.source.port)
        dst_dt = _port_data_type(dst_node.get_schema().inputs, edge.target.port)
        if src_dt is None or dst_dt is None:
            errors.append(f"edge {edge.id} references unknown port")
            continue
        if not ports_compatible(src_dt, dst_dt):
            errors.append(f"edge {edge.id} port type mismatch: {src_dt.value} -> {dst_dt.value}")

    return ValidationResult(valid=not errors, errors=errors)
