"""Job endpoints (plan §9.3).

Submission routes map to :class:`JobKind`. Polling routes return snapshots.
Execution is delegated to the injected :class:`JobStore`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from aimation_actor_core.api.deps import get_job_store, require_token
from aimation_actor_core.domain.job.job import Job, JobKind, JobSnapshot, JobStatus, JobStore
from aimation_actor_core.domain.pipeline.graph import Graph

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_token)])


def _submit(store: JobStore, kind: JobKind, payload: dict[str, Any]) -> Job:
    return store.submit(kind, payload)


@router.post(
    "/video-to-motion",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate animation from video",
)
def video_to_motion(
    payload: dict[str, Any],
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Submit a video-to-motion job."""
    return _submit(store, JobKind.VIDEO_TO_MOTION, payload)


@router.post(
    "/blocking-to-motion",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate animation from blocking",
)
def blocking_to_motion(
    payload: dict[str, Any],
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Submit a blocking-to-motion job."""
    return _submit(store, JobKind.BLOCKING_TO_MOTION, payload)


@router.post(
    "/graph/execute",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute a complete node graph",
)
async def graph_execute(
    graph: Graph,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Enqueue a node graph for background execution (async, non-blocking).

    The validated :class:`Graph` is serialized and delegated to the injected
    :class:`JobStore`, which creates a QUEUED job and schedules execution in
    a background task. The client polls ``GET /jobs/{job_id}`` for status.
    """
    payload = graph.model_dump()
    job = store.submit(JobKind.GRAPH_EXECUTE, payload)
    background_tasks.add_task(store.execute_graph_async, job.job_id, payload)
    return job


@router.get("/{job_id}", response_model=JobSnapshot, summary="Job status")
def get_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> JobSnapshot:
    """Return the current job snapshot (slim — result lives on ``/result``)."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobSnapshot.from_job(job)


@router.get("/{job_id}/result", summary="Job result")
def get_job_result(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> dict[str, Any]:
    """Return the job result payload (or a descriptor if not ready)."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if job.status != JobStatus.SUCCEEDED:
        return {"status": job.status.value, "result": None}
    return {"status": job.status.value, "result": job.result}


@router.get("/{job_id}/logs", summary="Per-node job logs")
def get_job_logs(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> list[str]:
    """Return the job's log lines (plan §9.3)."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job.logs


@router.post("/{job_id}/cancel", response_model=Job, summary="Cancel a job")
def cancel_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Request cancellation of a queued/running job."""
    cancelled = store.cancel(job_id)
    if not cancelled:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return job
    job = store.get(job_id)
    assert job is not None
    return job
