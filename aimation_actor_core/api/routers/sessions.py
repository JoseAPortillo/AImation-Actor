"""DCC session endpoints (SDD §5.2, plan §9.3).

Session lifecycle: register → heartbeat (keep-alive) → push_result →
deregister. All behind the instance-token dependency.

Phase B adds:
- push_result: queue typed payloads for addon delivery
- pending: addon polls for queued payloads
- submit_edited_poses: addon sends edited poses back to core
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from aimation_actor_core.api.deps import get_session_store, require_token
from aimation_actor_core.domain.dcc.push_payload import PushPayload
from aimation_actor_core.domain.dcc.session import DCCSession, SessionStore

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_token)])


@router.post(
    "/register",
    response_model=DCCSession,
    status_code=status.HTTP_201_CREATED,
    summary="Register a DCC plugin session",
)
def register_session(
    payload: DCCSession,
    store: SessionStore = Depends(get_session_store),
) -> DCCSession:
    """Register (or re-register) a DCC session with the Core.

    ``session_id`` is optional on input: omitted generates a new one, provided
    (reconnect) resumes that state (Plan_DCC_Maya.md §session).
    """
    return store.register(payload)


@router.get("", response_model=list[DCCSession], summary="List active sessions")
def list_sessions(store: SessionStore = Depends(get_session_store)) -> list[DCCSession]:
    """Return all active DCC sessions."""
    return store.list_active()


@router.post(
    "/{session_id}/heartbeat",
    response_model=DCCSession,
    summary="Refresh a session heartbeat",
)
def heartbeat(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> DCCSession:
    """Refresh ``last_heartbeat`` for a session."""
    if not store.touch(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    session = store.get(session_id)
    assert session is not None
    return session


@router.post(
    "/{session_id}/push_result",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a payload for delivery to a DCC session",
)
def push_result(
    session_id: str,
    payload: PushPayload,
    store: SessionStore = Depends(get_session_store),
) -> dict[str, str]:
    """Queue a typed payload for delivery to the given session.

    The addon polls ``GET /sessions/{id}/pending`` to retrieve queued payloads.
    """
    if not store.enqueue(session_id, payload):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return {"status": "queued", "session_id": session_id, "kind": payload.kind}


@router.get(
    "/{session_id}/pending",
    response_model=PushPayload | None,
    summary="Poll for pending payloads (addon delivery)",
)
def get_pending(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> PushPayload | None:
    """Return the next pending payload for a session, or 204 if empty.

    The addon polls this endpoint every 2s to receive queued payloads.
    """
    if store.get(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    payload = store.dequeue(session_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT, detail="no pending payloads")
    return payload


@router.post(
    "/{session_id}/submit_edited_poses",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive edited poses from a DCC session",
)
def submit_edited_poses(
    session_id: str,
    payload: PushPayload,
    store: SessionStore = Depends(get_session_store),
) -> dict[str, str]:
    """Receive edited poses from the addon and store them.

    The frontend can later retrieve these edited poses for further processing.
    """
    if store.get(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    # Store edited poses as a queued payload for the frontend to retrieve
    edited_payload = PushPayload(
        kind="edited_poses",
        motion=payload.motion,
        source_frame_range=payload.source_frame_range,
        request_id=payload.request_id,
    )
    store.enqueue(session_id, edited_payload)
    return {"status": "received", "session_id": session_id, "kind": "edited_poses"}


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Deregister a DCC session",
)
def deregister(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> None:
    """Remove a session (e.g. plugin unload)."""
    if not store.deregister(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
