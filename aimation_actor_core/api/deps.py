"""FastAPI dependencies: per-instance token auth (SDD §4.3) and DI access.

The DCC plugins and Tauri app authenticate every request with
``Authorization: Bearer <instance-token>`` (Plan_DCC_Maya.md §auth). The token
is generated once at startup and stored on ``app.state``.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from aimation_actor_core.domain.dcc.session import SessionStore
from aimation_actor_core.domain.job.job import JobStore
from aimation_actor_core.domain.pipeline.registry import NodeRegistry


def _http_unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Reject requests without a valid instance Bearer token.

    The token is compared constant-time against the one in settings.
    """
    expected: str = request.app.state.settings.session_token
    if not expected:
        raise _http_unauthorized("server has no instance token configured")

    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise _http_unauthorized("missing Bearer token")

    # Constant-time comparison to avoid timing side-channels (SDD §4.3).
    import hmac

    if not hmac.compare_digest(credential, expected):
        raise _http_unauthorized("invalid token")


def get_session_store(request: Request) -> SessionStore:
    """Return the injected session store from ``app.state``."""
    store = request.app.state.session_store
    assert isinstance(store, SessionStore)
    return store


def get_job_store(request: Request) -> JobStore:
    """Return the injected job store from ``app.state``."""
    store = request.app.state.job_store
    assert isinstance(store, JobStore)
    return store


def get_node_registry(request: Request) -> NodeRegistry:
    """Return the injected node registry from ``app.state``."""
    registry = request.app.state.node_registry
    assert isinstance(registry, NodeRegistry)
    return registry
