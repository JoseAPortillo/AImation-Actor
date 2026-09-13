"""In-memory implementations of the domain store interfaces.

These are the virtual/in-memory adapters used until real durable storage
(SQLite, filesystem) and real AI execution land. They live in
:mod:`infrastructure` and are injected at the composition root (SDD §2.4),
so the API layer never depends on a concrete store.

NOTE: In-memory state is lost on process restart. Production persistence is a
later phase (SDD §6 deployment/ops).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from aimation_actor_core.domain.dcc.session import DCCSession, SessionStore
from aimation_actor_core.domain.job.job import Job, JobKind, JobStatus, JobStore
from aimation_actor_core.domain.pipeline.executor import GraphExecutionResult, GraphExecutor
from aimation_actor_core.domain.pipeline.graph import Graph
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.infrastructure.virtual.executor import (
    GraphValidationError,
    NodeExecutionError,
)

_TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


def _drive_executor_on_thread(
    executor: GraphExecutor,
    graph: Graph,
    registry: NodeRegistry,
) -> GraphExecutionResult:
    """Drive an async graph executor to completion on a dedicated worker thread.

    :meth:`GraphExecutor.run` is a coroutine whose body performs CPU-bound
    inference (blocking onnxruntime session calls) that never yields to the
    event loop. ``asyncio.to_thread`` alone is not enough here: calling the
    ``async def`` in a worker thread would just produce an unawaited coroutine.
    Running it with :func:`asyncio.run` on a private thread-local event loop
    keeps the pipeline work off the FastAPI loop while preserving the async
    protocol and per-node timeouts. The worker never touches ``self._jobs``;
    job state is mutated only by the awaiting async task.
    """
    return asyncio.run(executor.run(graph, registry))


def _json_safe(value: Any) -> Any:  # noqa: ANN401 - generic coercion of arbitrary node outputs
    """Recursively convert numpy/opaque values into JSON-serializable primitives.

    Real AI node outputs (e.g. ``video-source`` frames) carry ``numpy.ndarray``
    payloads. These are not JSON-serializable by pydantic, so graph-execute job
    results are flattened here before storage — the pixel payload is converted
    to a nested list, and numpy scalars to Python natives. Keeps
    ``/jobs/graph/execute`` JSON-safe for any node output.
    """
    return _coerce(value)


def _coerce(value: Any) -> Any:  # noqa: ANN401 - generic coercion of arbitrary node outputs
    if hasattr(value, "tolist"):
        return _coerce(value.tolist())
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    return value


class InMemorySessionStore(SessionStore):
    """Thread-safe in-memory session registry."""

    def __init__(self) -> None:
        self._sessions: dict[str, DCCSession] = {}

    def register(self, session: DCCSession) -> DCCSession:
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> DCCSession | None:
        return self._sessions.get(session_id)

    def list_active(self) -> list[DCCSession]:
        return list(self._sessions.values())

    def touch(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        self._sessions[session_id] = session.heartbeat()
        return True

    def deregister(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None


class InMemoryJobStore(JobStore):
    """In-memory job registry with asynchronous graph execution.

    ``GRAPH_EXECUTE`` jobs are created in QUEUED status and executed in a
    background task via :meth:`execute_graph_async`. The client polls
    ``GET /jobs/{job_id}`` for status updates. Other kinds keep the immediate
    stub completion until their real pipelines land.
    """

    def __init__(
        self,
        executor: GraphExecutor | None = None,
        registry: NodeRegistry | None = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._executor = executor
        self._registry = registry

    def submit(self, kind: JobKind, payload: dict[str, Any]) -> Job:
        if kind is not JobKind.GRAPH_EXECUTE:
            return self._submit_stub(kind, payload)
        return self._submit_graph_queued(payload)

    async def execute_graph_async(self, job_id: str, payload: dict[str, Any]) -> None:
        """Execute a graph job in the background (updates job status).

        The CPU-bound pipeline runs off the event loop on a worker thread, so
        ``/health`` and ``/jobs`` polling stay responsive while a job runs.
        """
        if self._executor is None or self._registry is None:
            raise RuntimeError("graph executor/registry not wired to InMemoryJobStore")

        # Mark as RUNNING — but a queued cancel must stick: never clobber a
        # CANCELLED job, and skip execution entirely when already cancelled.
        current = self._jobs[job_id]
        if current.status is JobStatus.CANCELLED:
            return
        self._jobs[job_id] = current.model_copy(update={"status": JobStatus.RUNNING})

        try:
            graph = Graph.model_validate(payload)
            result = await asyncio.to_thread(
                _drive_executor_on_thread, self._executor, graph, self._registry
            )
        except (GraphValidationError, NodeExecutionError, ValidationError) as exc:
            if self._jobs[job_id].status is JobStatus.CANCELLED:
                return
            failed = Job(
                job_id=job_id,
                kind=JobKind.GRAPH_EXECUTE,
                status=JobStatus.FAILED,
                error=str(exc),
            )
            self._jobs[job_id] = failed
            return

        if self._jobs[job_id].status is JobStatus.CANCELLED:
            return
        succeeded = Job(
            job_id=job_id,
            kind=JobKind.GRAPH_EXECUTE,
            status=JobStatus.SUCCEEDED,
            result={"outputs": _json_safe(result.outputs)},
            logs=result.logs,
        )
        self._jobs[job_id] = succeeded

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """Return the current snapshots of every known job."""
        return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status in _TERMINAL_STATUSES:
            return False
        self._jobs[job_id] = job.model_copy(update={"status": JobStatus.CANCELLED})
        return True

    def _submit_stub(self, kind: JobKind, payload: dict[str, Any]) -> Job:
        job = Job(
            kind=kind,
            status=JobStatus.SUCCEEDED,
            result={
                "kind": kind.value,
                "note": "stub execution — AI pipeline not yet connected",
                "echo": payload,
            },
            logs=[f"submitted {kind.value} job (stub)"],
        )
        self._jobs[job.job_id] = job
        return job

    def _submit_graph_queued(self, payload: dict[str, Any]) -> Job:
        """Create a QUEUED graph job (execution happens in background)."""
        job = Job(kind=JobKind.GRAPH_EXECUTE, status=JobStatus.QUEUED)
        self._jobs[job.job_id] = job
        return job
