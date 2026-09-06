"""Unit tests for the graph model and DAG validation (graph-model spec).

Covers the graph payload contract (`Graph`/`GraphNode`/`Edge`/`PortRef`) plus
domain validation: unique ids, dangling-edge rejection, cycle detection via
topological sort, port-type compatibility, and node allowlisting.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.pipeline import (
    DataType,
    Edge,
    Graph,
    GraphCycleError,
    GraphNode,
    INode,
    NodeCategory,
    NodeOutput,
    NodeRegistry,
    NodeSchema,
    PortRef,
    PortSpec,
    ValidationResult,
    topological_sort,
    validate_graph,
)
from aimation_actor_core.domain.pipeline.node import ExecutionContext


class _InertNode(INode):
    """INode whose execute/validate are inert; schema supplied by subclasses."""

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        return NodeOutput()

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


class _FrameSourceNode(_InertNode):
    """Emits FRAMES on its ``frames`` output port."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="frame-source",
            category=NodeCategory.SOURCE,
            title="Frame Source",
            outputs=[PortSpec(name="frames", data_type=DataType.FRAMES)],
        )


class _FrameSinkNode(_InertNode):
    """Consumes FRAMES on its ``frames`` input port."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="frame-sink",
            category=NodeCategory.OUTPUT,
            title="Frame Sink",
            inputs=[PortSpec(name="frames", data_type=DataType.FRAMES)],
        )


class _NumberSinkNode(_InertNode):
    """Consumes a NUMBER on its ``count`` input port."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="number-sink",
            category=NodeCategory.OUTPUT,
            title="Number Sink",
            inputs=[PortSpec(name="count", data_type=DataType.NUMBER)],
        )


class _PassThroughNode(_InertNode):
    """Relay node typed ANY -> ANY."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="pass-through",
            category=NodeCategory.LOGIC,
            title="Pass Through",
            inputs=[PortSpec(name="input", data_type=DataType.ANY)],
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )


class _FakeRegistry:
    """Structural NodeRegistry holding the fake nodes above."""

    def __init__(self, nodes: dict[str, INode] | None = None) -> None:
        self._nodes: dict[str, INode] = nodes or {}

    def get(self, node_type: str) -> INode | None:
        return self._nodes.get(node_type)

    def list_schemas(self) -> list[NodeSchema]:
        return [node.get_schema() for node in self._nodes.values()]

    def contains(self, node_type: str) -> bool:
        return node_type in self._nodes


def _full_registry() -> NodeRegistry:
    return _FakeRegistry(
        {
            "frame-source": _FrameSourceNode(),
            "frame-sink": _FrameSinkNode(),
            "number-sink": _NumberSinkNode(),
            "pass-through": _PassThroughNode(),
        }
    )


def _node(node_id: str, node_type: str) -> GraphNode:
    return GraphNode(id=node_id, type=node_type)


def _edge(
    edge_id: str,
    src_node: str,
    src_port: str,
    dst_node: str,
    dst_port: str,
) -> Edge:
    return Edge(
        id=edge_id,
        source=PortRef(node=src_node, port=src_port),
        target=PortRef(node=dst_node, port=dst_port),
    )


def test_well_formed_graph_validates() -> None:
    graph = Graph(
        version="0.1",
        nodes=[
            _node("src", "frame-source"),
            _node("pt", "pass-through"),
            _node("sink", "frame-sink"),
        ],
        edges=[
            _edge("e1", "src", "frames", "pt", "input"),
            _edge("e2", "pt", "output", "sink", "frames"),
        ],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is True
    assert result.errors == []


def test_aimgraph_extra_fields_round_trip() -> None:
    raw: dict[str, object] = {
        "version": "0.1",
        "nodes": [{"id": "n1", "type": "frame-source", "metadata": {"label": "keep"}}],
        "edges": [],
        "future_field": "preserved",
    }
    graph = Graph.model_validate(raw)
    reloaded = Graph.model_validate(graph.model_dump())
    assert reloaded.version == "0.1"
    assert reloaded.nodes[0].id == "n1"
    assert reloaded.model_extra == {"future_field": "preserved"}
    assert reloaded.nodes[0].model_extra == {"metadata": {"label": "keep"}}


def test_duplicate_node_id_rejected() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("dup", "frame-source"), _node("dup", "frame-sink")],
        edges=[],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is False
    assert any("dup" in err for err in result.errors)


def test_edge_references_missing_node_rejected() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("src", "frame-source")],
        edges=[_edge("e1", "src", "frames", "ghost", "input")],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is False
    assert any("ghost" in err for err in result.errors)


def test_acyclic_dag_sorts_in_topological_order() -> None:
    graph = Graph(
        version="0.1",
        nodes=[
            _node("a", "frame-source"),
            _node("b", "pass-through"),
            _node("c", "frame-sink"),
        ],
        edges=[
            _edge("e1", "a", "frames", "b", "input"),
            _edge("e2", "b", "output", "c", "frames"),
        ],
    )
    order = topological_sort(graph)
    assert order == ["a", "b", "c"]


def test_cycle_rejected_before_execution() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("a", "pass-through"), _node("b", "pass-through")],
        edges=[
            _edge("e1", "a", "output", "b", "input"),
            _edge("e2", "b", "output", "a", "input"),
        ],
    )
    with pytest.raises(GraphCycleError):
        topological_sort(graph)
    result = validate_graph(graph, _full_registry())
    assert result.valid is False
    assert any("cycle" in err for err in result.errors)


def test_compatible_port_connection_accepted() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("src", "frame-source"), _node("sink", "frame-sink")],
        edges=[_edge("e1", "src", "frames", "sink", "frames")],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is True
    assert result.errors == []


def test_mismatched_port_types_rejected() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("src", "frame-source"), _node("sink", "number-sink")],
        edges=[_edge("e1", "src", "frames", "sink", "count")],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is False
    assert any("mismatch" in err for err in result.errors)


def test_any_port_accepts_any_type() -> None:
    graph = Graph(
        version="0.1",
        nodes=[
            _node("src", "frame-source"),
            _node("pt", "pass-through"),
            _node("sink", "number-sink"),
        ],
        edges=[
            _edge("e1", "src", "frames", "pt", "input"),
            _edge("e2", "pt", "output", "sink", "count"),
        ],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is True
    assert result.errors == []


def test_unknown_node_type_rejected() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("a", "alien-node"), _node("b", "other-alien")],
        edges=[],
    )
    result = validate_graph(graph, _full_registry())
    assert result.valid is False
    assert any("alien-node" in err for err in result.errors)
    assert any("other-alien" in err for err in result.errors)


def test_empty_node_id_rejected_by_model() -> None:
    with pytest.raises(ValidationError):
        GraphNode(id="", type="frame-source")
