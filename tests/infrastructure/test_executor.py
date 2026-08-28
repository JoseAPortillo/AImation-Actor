"""Infrastructure tests for the synchronous graph executor and seed nodes.

Covers the graph-execution and node-registry specs at the adapter layer:
topological dispatch, per-node timeout, failure isolation, log ordering,
allowlist rejection, and the three seed nodes (pass-through / merge /
frame-range).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from aimation_actor_core.domain.pipeline import (
    DataType,
    Edge,
    Graph,
    GraphNode,
    NodeCategory,
    NodeOutput,
    NodeSchema,
    PortRef,
    PortSpec,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.node import ExecutionContext, INode
from aimation_actor_core.infrastructure.virtual import (
    FrameRangeNode,
    MergeNode,
    PassThroughNode,
    StaticNodeRegistry,
    SynchronousGraphExecutor,
    seeded_node_registry,
)
from aimation_actor_core.infrastructure.virtual.executor import (
    GraphValidationError,
    NodeExecutionError,
    NodeTimeoutError,
)


def _ctx(timeout_s: float = 30.0) -> ExecutionContext:
    return ExecutionContext(trace_id="trace-1", timeout_s=timeout_s)


def _graph(nodes: list[GraphNode], edges: list[Edge]) -> Graph:
    return Graph(version="0.1", nodes=nodes, edges=edges)


def _node(node_id: str, node_type: str, **params: object) -> GraphNode:
    return GraphNode(id=node_id, type=node_type, params=dict(params))


def _edge(edge_id: str, src: str, sport: str, dst: str, dport: str) -> Edge:
    return Edge(
        id=edge_id,
        source=PortRef(node=src, port=sport),
        target=PortRef(node=dst, port=dport),
    )


# --- Seed node behavior (node-registry spec) --------------------------------


async def test_pass_through_node_forwards_value() -> None:
    result = await PassThroughNode().execute({"input": [1, 2, 3]}, {}, _ctx())
    assert result.values["output"] == [1, 2, 3]


async def test_merge_node_concatenates_streams() -> None:
    result = await MergeNode().execute({"input_a": [1, 2], "input_b": [3, 4]}, {}, _ctx())
    assert result.values["merged"] == [1, 2, 3, 4]


async def test_frame_range_node_emits_half_open_indices() -> None:
    result = await FrameRangeNode().execute({}, {"start": 5, "end": 8}, _ctx())
    assert result.values["frames"] == [5, 6, 7]


def test_seeded_registry_lists_three_seed_nodes() -> None:
    registry = seeded_node_registry()
    schemas = {schema.type for schema in registry.list_schemas()}
    # Three virtual seed nodes plus the real AI video-source and pose-2d nodes.
    assert schemas == {"pass-through", "merge", "frame-range", "video-source", "pose-2d"}


def test_seed_nodes_declare_pinned_port_types() -> None:
    registry = seeded_node_registry()

    pass_through = registry.get("pass-through")
    assert pass_through is not None
    pt_schema = pass_through.get_schema()
    assert pt_schema.inputs[0].data_type is DataType.ANY
    assert pt_schema.outputs[0].data_type is DataType.ANY

    merge = registry.get("merge")
    assert merge is not None
    merge_schema = merge.get_schema()
    assert [p.data_type for p in merge_schema.inputs] == [
        DataType.FRAME_STREAM,
        DataType.FRAME_STREAM,
    ]
    assert merge_schema.outputs[0].data_type is DataType.FRAME_STREAM

    frame_range = registry.get("frame-range")
    assert frame_range is not None
    fr_schema = frame_range.get_schema()
    assert fr_schema.outputs[0].data_type is DataType.FRAME_STREAM
    assert {p.name: p.data_type for p in fr_schema.params} == {
        "start": DataType.NUMBER,
        "end": DataType.NUMBER,
    }


# --- Executor dispatch (graph-execution spec) --------------------------------


async def test_executor_runs_nodes_in_topological_order() -> None:
    graph = _graph(
        nodes=[
            _node("src", "frame-range", start=0, end=3),
            _node("pt", "pass-through"),
        ],
        edges=[_edge("e1", "src", "frames", "pt", "input")],
    )
    result = await SynchronousGraphExecutor().run(graph, seeded_node_registry())
    assert result.outputs["pt"]["output"] == [0, 1, 2]


async def test_logs_reflect_execution_order() -> None:
    graph = _graph(
        nodes=[
            _node("a", "frame-range", start=0, end=2),
            _node("b", "pass-through"),
            _node("c", "pass-through"),
        ],
        edges=[
            _edge("e1", "a", "frames", "b", "input"),
            _edge("e2", "b", "output", "c", "input"),
        ],
    )
    result = await SynchronousGraphExecutor().run(graph, seeded_node_registry())
    assert result.logs == [
        "executed a (frame-range)",
        "executed b (pass-through)",
        "executed c (pass-through)",
    ]


async def test_unknown_node_type_rejected_before_execution() -> None:
    graph = _graph(nodes=[_node("alien", "not-a-node")], edges=[])
    with pytest.raises(GraphValidationError) as exc_info:
        await SynchronousGraphExecutor().run(graph, seeded_node_registry())
    assert "unknown node type" in str(exc_info.value)


# --- Custom test nodes for timeout / failure tests ---------------------------


class _SlowNode(INode):
    """A node that sleeps past any reasonable timeout."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="slow",
            category=NodeCategory.LOGIC,
            title="Slow",
            inputs=[PortSpec(name="input", data_type=DataType.ANY)],
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        await asyncio.sleep(10)
        return NodeOutput(values={"output": 1})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


class _FailingNode(INode):
    """A node that always raises during execution."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="failing",
            category=NodeCategory.LOGIC,
            title="Failing",
            inputs=[PortSpec(name="input", data_type=DataType.ANY)],
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        raise RuntimeError("boom")

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


class _RecorderNode(INode):
    """A node that records itself into a shared list when executed."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="recorder",
            category=NodeCategory.LOGIC,
            title="Recorder",
            inputs=[PortSpec(name="input", data_type=DataType.ANY)],
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        self._calls.append("recorder")
        return NodeOutput(values={"output": 1})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


async def test_node_exceeding_timeout_fails() -> None:
    registry = StaticNodeRegistry()
    registry.register(_SlowNode())
    graph = _graph(nodes=[_node("slow", "slow")], edges=[])
    with pytest.raises(NodeTimeoutError):
        await SynchronousGraphExecutor(timeout_s=0.05).run(graph, registry)


async def test_mid_graph_failure_halts_downstream() -> None:
    calls: list[str] = []
    registry = StaticNodeRegistry()
    registry.register(_FailingNode())
    registry.register(_RecorderNode(calls))
    graph = _graph(
        nodes=[_node("f", "failing"), _node("down", "recorder")],
        edges=[_edge("e1", "f", "output", "down", "input")],
    )
    with pytest.raises(NodeExecutionError) as exc_info:
        await SynchronousGraphExecutor().run(graph, registry)
    assert "f" in str(exc_info.value)
    assert calls == []  # downstream node never executed
