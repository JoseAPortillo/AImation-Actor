"""Job endpoints (plan §9.3).

Submission routes map to :class:`JobKind`. Polling routes return snapshots.
Execution is delegated to the injected :class:`JobStore`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from aimation_actor_core.api.deps import get_job_store, require_token
from aimation_actor_core.domain.job.job import Job, JobKind, JobStatus, JobStore

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_token)])


def _submit(
    store: JobStore, kind: JobKind, payload: dict[str, Any]
) -> Job:
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
def graph_execute(
    payload: dict[str, Any],
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Submit a full node-graph execution job (plan §9.3, example payload)."""
    return _submit(store, JobKind.GRAPH_EXECUTE, payload)


@router.get("/{job_id}", response_model=Job, summary="Job status")
def get_job(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> Job:
    """Return the current job snapshot."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job


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
