"""In-memory implementations of the domain store interfaces.

These are the virtual/in-memory adapters used until real durable storage
(SQLite, filesystem) and real AI execution land. They live in
:mod:`infrastructure` and are injected at the composition root (SDD §2.4),
so the API layer never depends on a concrete store.

NOTE: In-memory state is lost on process restart. Production persistence is a
later phase (SDD §6 deployment/ops).
"""

from __future__ import annotations

from aimation_actor_core.domain.dcc.session import DCCSession, SessionStore
from aimation_actor_core.domain.job.job import Job, JobKind, JobStatus, JobStore


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
    """In-memory job registry with immediate (stub) completion.

    The job is recorded with status ``succeeded`` right away so the polling
    contract is exercisable end-to-end. Real CPU/GPU execution replaces the
    stub in a later phase.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def submit(self, kind: JobKind, payload: dict[str, object]) -> Job:
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

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status == JobStatus.SUCCEEDED:
            return False
        self._jobs[job_id] = job.model_copy(update={"status": JobStatus.CANCELLED})
        return True
