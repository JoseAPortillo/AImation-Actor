"""Concurrency regression tests for :class:`InMemoryJobStore`.

The graph pipeline is CPU-bound (blocking onnxruntime inference inside async
node coroutines, see ``infrastructure/ai_models``) and must never run directly
on the FastAPI event loop. These tests prove that while a slow graph job is
executing: the loop stays responsive, the executor runs on a worker thread,
the job still reaches SUCCEEDED, and exceptions raised in the worker thread
still land in the FAILED branch exactly like a direct await would.
"""

from __future__ import annotations

import asyncio
import threading
import time

from aimation_actor_core.domain.job.job import JobKind, JobStatus
from aimation_actor_core.domain.pipeline import Edge, Graph, GraphNode, PortRef
from aimation_actor_core.domain.pipeline.executor import GraphExecutionResult
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.infrastructure.virtual import StaticNodeRegistry
from aimation_actor_core.infrastructure.virtual.executor import NodeExecutionError
from aimation_actor_core.infrastructure.virtual.stores import InMemoryJobStore


def _node(node_id: str, node_type: str, **params: object) -> GraphNode:
    return GraphNode(id=node_id, type=node_type, params=dict(params))


def _edge(edge_id: str, src: str, sport: str, dst: str, dport: str) -> Edge:
    return Edge(
        id=edge_id,
        source=PortRef(node=src, port=sport),
        target=PortRef(node=dst, port=dport),
    )


def _chain_graph() -> Graph:
    """A realistic 3-node chain (frame-range → pass-through → pass-through)."""
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


class _SlowExecutor:
    """Fake :class:`GraphExecutor` mimicking the CPU-bound pipeline.

    ``run`` is async like the real executor but blocks in :func:`time.sleep`
    without ever yielding, exactly like the onnxruntime inference calls inside
    the real node coroutines.
    """

    def __init__(self, block_s: float, entered: threading.Event) -> None:
        self._block_s = block_s
        self._entered = entered
        self.run_thread_ident: int | None = None

    async def run(self, graph: Graph, registry: NodeRegistry) -> GraphExecutionResult:
        self.run_thread_ident = threading.get_ident()
        self._entered.set()
        time.sleep(self._block_s)
        return GraphExecutionResult(
            outputs={"pt2": {"output": [0, 1, 2]}},
            logs=[
                "executed src (frame-range)",
                "executed pt1 (pass-through)",
                "executed pt2 (pass-through)",
            ],
        )


class _FailingExecutor:
    """Fake :class:`GraphExecutor` that fails after crossing the thread boundary."""

    async def run(self, graph: Graph, registry: NodeRegistry) -> GraphExecutionResult:
        raise NodeExecutionError("pt1", "boom in worker thread")


async def test_slow_job_keeps_event_loop_responsive_and_succeeds() -> None:
    entered = threading.Event()
    executor = _SlowExecutor(block_s=0.5, entered=entered)
    store = InMemoryJobStore(executor=executor, registry=StaticNodeRegistry())
    payload = _chain_graph().model_dump()
    job = store.submit(JobKind.GRAPH_EXECUTE, payload)
    assert job.status is JobStatus.QUEUED
    loop_ident = threading.get_ident()

    task = asyncio.create_task(store.execute_graph_async(job.job_id, payload))

    # Yield to the loop until the executor thread signals it has started, so
    # the task can reach its `to_thread` step (blocking on the event directly
    # would starve the loop and deadlock the test).
    deadline = time.monotonic() + 2
    while not entered.is_set():
        assert time.monotonic() < deadline, "executor thread never started"
        await asyncio.sleep(0.005)

    # The loop must not be blocked while the job's executor sleeps: a
    # heartbeat-style coroutine completes well inside the 0.5 s job window,
    # and the job is still observably RUNNING (state lives on the async side).
    await asyncio.wait_for(asyncio.sleep(0), timeout=0.15)
    assert store.get(job.job_id).status is JobStatus.RUNNING  # type: ignore[union-attr]

    assert executor.run_thread_ident is not None
    assert executor.run_thread_ident != loop_ident

    await asyncio.wait_for(task, timeout=2)
    final = store.get(job.job_id)
    assert final is not None
    assert final.status is JobStatus.SUCCEEDED
    assert final.error is None
    assert final.logs == [
        "executed src (frame-range)",
        "executed pt1 (pass-through)",
        "executed pt2 (pass-through)",
    ]
    assert final.result == {"outputs": {"pt2": {"output": [0, 1, 2]}}}


async def test_executor_worker_thread_error_lands_in_failed() -> None:
    store = InMemoryJobStore(executor=_FailingExecutor(), registry=StaticNodeRegistry())
    payload = _chain_graph().model_dump()
    job = store.submit(JobKind.GRAPH_EXECUTE, payload)

    await store.execute_graph_async(job.job_id, payload)

    final = store.get(job.job_id)
    assert final is not None
    assert final.status is JobStatus.FAILED
    assert final.error is not None
    assert "boom in worker thread" in final.error