"""DCC session domain contract (SDD §5.2).

A DCC plugin (Maya/Blender) registers a session with the Core so the Tauri
app and the Core can route results to the right host. This module owns the
session entity and the :class:`SessionStore` read/write interface. Concrete
storage lives in :mod:`infrastructure` and is injected at the composition root.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Timezone-aware current UTC time (naive datetimes are rejected)."""
    return datetime.now(UTC)


def new_session_id() -> str:
    """Generate a fresh :class:`DCCSession.session_id` (uuid v4)."""
    return str(uuid.uuid4())


class DCCType(StrEnum):
    """Supported host DCC applications (SDD §5.2 ``dcc_type``)."""

    MAYA = "maya"
    BLENDER = "blender"


class DCCSession(BaseModel):
    """A registered DCC plugin session (SDD §5.2).

    Values match the plan §10 DCC-session payload. Timestamps are timezone-aware
    UTC datetimes and serialize to ISO8601.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=new_session_id, min_length=1)
    dcc_type: DCCType
    dcc_version: str = Field(min_length=1)
    plugin_version: str = Field(min_length=1)
    registered_at: datetime = Field(default_factory=utcnow)
    last_heartbeat: datetime = Field(default_factory=utcnow)
    capabilities: list[str] = Field(default_factory=list)

    def heartbeat(self) -> DCCSession:
        """Return a copy with ``last_heartbeat`` refreshed."""
        return self.model_copy(update={"last_heartbeat": utcnow()})


@runtime_checkable
class SessionStore(Protocol):
    """Read/write access to the set of active DCC sessions."""

    def register(self, session: DCCSession) -> DCCSession:
        """Store a (new) session, returning it (with defaults resolved)."""
        ...

    def get(self, session_id: str) -> DCCSession | None:
        """Return the session by id, or ``None`` if unknown."""
        ...

    def list_active(self) -> list[DCCSession]:
        """Return all active sessions."""
        ...

    def touch(self, session_id: str) -> bool:
        """Refresh ``last_heartbeat``; return ``False`` if unknown."""
        ...

    def deregister(self, session_id: str) -> bool:
        """Remove a session; return ``False`` if unknown."""
        ...
