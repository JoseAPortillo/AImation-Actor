"""Job domain contract — asynchronous processing units (plan §9.3).

Jobs encapsulate long-running AI processing (video-to-motion, blocking, graph
execution). This module owns the job entity/state and the :class:`JobStore`
interface. The actual execution is an implementation detail of the
composition-root-injected store/manager (which may run CPU/GPU work out of the
event loop).

Design note: the job object is a snapshot; consumers poll by ``job_id``
(plan §9.3 ``GET /jobs/{id}``) rather than holding references.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


def new_job_id() -> str:
    """Generate a fresh job id (uuid v4)."""
    return str(uuid.uuid4())


class JobKind(StrEnum):
    """Supported job kinds (plan §9.3)."""

    VIDEO_TO_MOTION = "video-to-motion"
    BLOCKING_TO_MOTION = "blocking-to-motion"
    GRAPH_EXECUTE = "graph-execute"


class JobStatus(StrEnum):
    """Lifecycle status of a job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(BaseModel):
    """A processing job snapshot.

    Attributes:
        job_id: Unique job identifier.
        kind: What kind of work this job performs.
        status: Current :class:`JobStatus`.
        error: Optional failure detail when ``status == failed``.
        result: Optional structured result payload when succeeded.
        logs: Per-node / free-form log lines (plan §9.3 ``GET /jobs/{id}/logs``).
    """

    model_config = ConfigDict(frozen=True)

    job_id: str = Field(default_factory=new_job_id, min_length=1)
    kind: JobKind
    status: JobStatus = JobStatus.QUEUED
    error: str | None = None
    result: dict[str, Any] | None = None
    logs: list[str] = Field(default_factory=list)


@runtime_checkable
class JobStore(Protocol):
    """Read/write access to the job registry.

    Implementations are responsible for the actual processing lifecycle; the
    protocol only fixes the storage/shape contract.
    """

    def submit(self, kind: JobKind, payload: dict[str, Any]) -> Job:
        """Create and schedule a job, returning its initial snapshot."""
        ...

    def get(self, job_id: str) -> Job | None:
        """Return the latest job snapshot, or ``None`` if unknown."""
        ...

    def cancel(self, job_id: str) -> bool:
        """Request cancellation; return ``False`` if unknown."""
        ...
