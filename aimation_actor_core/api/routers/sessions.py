"""DCC session endpoints (SDD §5.2, plan §9.3).

Session lifecycle: register → heartbeat (keep-alive) → push_result →
deregister. All behind the instance-token dependency.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from aimation_actor_core.api.deps import get_session_store, require_token
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
    summary="Send a result to a DCC session",
)
def push_result(
    session_id: str,
    payload: dict[str, Any],
    store: SessionStore = Depends(get_session_store),
) -> dict[str, Any]:
    """Queue/deliver a result to the given session (delivery to be wired)."""
    if store.get(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return {"accepted": True, "session_id": session_id, "payload_keys": list(payload.keys())}


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister a DCC session",
)
def deregister(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> None:
    """Remove a session (e.g. plugin unload)."""
    if not store.deregister(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
