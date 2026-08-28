"""Job lifecycle tests for :class:`InMemoryJobStore` GRAPH_EXECUTE delegation.

Covers the job-lifecycle spec at the store layer: `QUEUED → RUNNING → terminal`
transitions, RUNNING observability via an injected blocking node, per-node log
accumulation, failure detail capture, and cancellation semantics.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from aimation_actor_core.domain.job.job import Job, JobKind, JobStatus
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
    StaticNodeRegistry,
    SynchronousGraphExecutor,
    seeded_node_registry,
)
from aimation_actor_core.infrastructure.virtual.stores import InMemoryJobStore


def _store(
    registry: StaticNodeRegistry | None = None,
) -> InMemoryJobStore:
    return InMemoryJobStore(
        executor=SynchronousGraphExecutor(),
        registry=registry or seeded_node_registry(),
    )


def _node(node_id: str, node_type: str, **params: object) -> GraphNode:
    return GraphNode(id=node_id, type=node_type, params=dict(params))


def _edge(edge_id: str, src: str, sport: str, dst: str, dport: str) -> Edge:
    return Edge(
        id=edge_id,
        source=PortRef(node=src, port=sport),
        target=PortRef(node=dst, port=dport),
    )


def _chain_graph() -> Graph:
    """A 3-node chain: frame-range → pass-through → pass-through."""
    return Graph(
        version="0.1",
        nodes=[
            _node("src", "frame-range", start=0, end=3),
            _node("pt1", "pass-through"),
            _node("pt2", "pass-through"),
        ],
        edges=[
            _edge("e1", "src", "frames", "pt1", "input"),
            _edge("e2", "pt1", "output", "pt2", "input"),
        ],
    )


class _BlockingNode(INode):
    """A node that signals entry, then blocks until a gate is released.

    The blocking is done via :func:`asyncio.to_thread` on a
    :class:`threading.Event`, so the test's main thread can release the gate
    while the executor's event loop stays responsive.
    """

    def __init__(self, gate: threading.Event, entered: threading.Event) -> None:
        self._gate = gate
        self._entered = entered

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="blocking",
            category=NodeCategory.LOGIC,
            title="Blocking",
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        self._entered.set()
        await asyncio.to_thread(self._gate.wait)
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


def _run_in_thread(
    store: InMemoryJobStore, graph: Graph, holder: dict[str, Job]
) -> threading.Thread:
    def _submit() -> None:
        holder["job"] = store.submit(JobKind.GRAPH_EXECUTE, graph.model_dump())

    thread = threading.Thread(target=_submit)
    thread.start()
    return thread


# --- Status transitions (job-lifecycle spec) ---------------------------------


def test_graph_execute_reaches_succeeded() -> None:
    job = _store().submit(JobKind.GRAPH_EXECUTE, _chain_graph().model_dump())
    assert job.status is JobStatus.SUCCEEDED
    assert job.error is None


def test_successful_job_result_contains_terminal_outputs() -> None:
    job = _store().submit(JobKind.GRAPH_EXECUTE, _chain_graph().model_dump())
    assert job.result is not None
    assert job.result["outputs"]["pt2"]["output"] == [0, 1, 2]


def test_job_logs_contain_per_node_entries() -> None:
    job = _store().submit(JobKind.GRAPH_EXECUTE, _chain_graph().model_dump())
    assert job.logs == [
        "executed src (frame-range)",
        "executed pt1 (pass-through)",
        "executed pt2 (pass-through)",
    ]


def test_unknown_node_type_job_fails() -> None:
    graph = Graph(version="0.1", nodes=[_node("alien", "not-a-node")], edges=[])
    job = _store().submit(JobKind.GRAPH_EXECUTE, graph.model_dump())
    assert job.status is JobStatus.FAILED
    assert job.error is not None
    assert "unknown node type" in job.error


def test_cycle_job_fails() -> None:
    graph = Graph(
        version="0.1",
        nodes=[_node("a", "pass-through"), _node("b", "pass-through")],
        edges=[
            _edge("e1", "a", "output", "b", "input"),
            _edge("e2", "b", "output", "a", "input"),
        ],
    )
    job = _store().submit(JobKind.GRAPH_EXECUTE, graph.model_dump())
    assert job.status is JobStatus.FAILED
    assert job.error is not None


def test_failed_job_includes_error_detail() -> None:
    registry = StaticNodeRegistry()
    registry.register(_FailingNode())
    graph = Graph(version="0.1", nodes=[_node("f", "failing")], edges=[])
    job = _store(registry=registry).submit(JobKind.GRAPH_EXECUTE, graph.model_dump())
    assert job.status is JobStatus.FAILED
    assert job.error is not None
    assert "f" in job.error
    assert "boom" in job.error


# --- RUNNING observability (blocking node + cross-thread poll) ---------------


def test_running_state_is_observable_before_terminal() -> None:
    gate = threading.Event()
    entered = threading.Event()
    registry = StaticNodeRegistry()
    registry.register(_BlockingNode(gate, entered))
    store = _store(registry=registry)
    graph = Graph(version="0.1", nodes=[_node("b", "blocking")], edges=[])

    holder: dict[str, Job] = {}
    thread = _run_in_thread(store, graph, holder)
    try:
        assert entered.wait(timeout=5), "blocking node never entered"

        running = [job for job in store.list() if job.status is JobStatus.RUNNING]
        assert len(running) == 1
        running_id = running[0].job_id
        assert store.get(running_id).status is JobStatus.RUNNING  # type: ignore[union-attr]
    finally:
        gate.set()
        thread.join(timeout=5)

    final = store.get(holder["job"].job_id)
    assert final is not None
    assert final.status is JobStatus.SUCCEEDED


# --- Cancellation semantics (job-lifecycle spec) ------------------------------


def test_cancel_running_job_returns_true_and_sticks() -> None:
    gate = threading.Event()
    entered = threading.Event()
    registry = StaticNodeRegistry()
    registry.register(_BlockingNode(gate, entered))
    store = _store(registry=registry)
    graph = Graph(version="0.1", nodes=[_node("b", "blocking")], edges=[])

    holder: dict[str, Job] = {}
    thread = _run_in_thread(store, graph, holder)
    try:
        assert entered.wait(timeout=5), "blocking node never entered"
        running = [job for job in store.list() if job.status is JobStatus.RUNNING]
        assert len(running) == 1
        job_id = running[0].job_id

        assert store.cancel(job_id) is True
        cancelled = store.get(job_id)
        assert cancelled is not None
        assert cancelled.status is JobStatus.CANCELLED
    finally:
        gate.set()
        thread.join(timeout=5)

    final = store.get(job_id)
    assert final is not None
    assert final.status is JobStatus.CANCELLED  # terminal result did not overwrite cancel


def test_cancel_succeeded_job_returns_false() -> None:
    store = _store()
    job = store.submit(JobKind.GRAPH_EXECUTE, _chain_graph().model_dump())
    assert job.status is JobStatus.SUCCEEDED
    assert store.cancel(job.job_id) is False


def test_cancel_failed_job_returns_false() -> None:
    store = _store()
    graph = Graph(version="0.1", nodes=[_node("alien", "not-a-node")], edges=[])
    job = store.submit(JobKind.GRAPH_EXECUTE, graph.model_dump())
    assert job.status is JobStatus.FAILED
    assert store.cancel(job.job_id) is False


def test_cancel_unknown_job_returns_false() -> None:
    assert _store().cancel("missing") is False


# --- Kind-agnostic stub path preserved ----------------------------------------


def test_non_graph_kind_completes_without_executor() -> None:
    store = InMemoryJobStore()  # no executor/registry wired
    job = store.submit(JobKind.VIDEO_TO_MOTION, {"video": "x.mp4"})
    assert job.status is JobStatus.SUCCEEDED
