"""Tests for the SessionManager lifecycle (memory-only token)."""

from __future__ import annotations

import time

import pytest

from blender_addon.core.session import SessionManager


class FakeClient:
    """Records session calls; scriptable results."""

    def __init__(self) -> None:
        self.token = "tok-secret"
        self.registered: list[str] = []
        self.heartbeats: list[str] = []
        self.deregistered: list[str] = []
        self.cleared = False
        self.register_result: str | None = "session-1"
        self.fail_heartbeat = False

    def register_session(self, name: str) -> str:
        self.registered.append(name)
        if self.register_result is None:
            raise ValueError("no session_id")
        return self.register_result

    def heartbeat(self, session_id: str) -> bool:
        self.heartbeats.append(session_id)
        return not self.fail_heartbeat

    def deregister_session(self, session_id: str) -> None:
        self.deregistered.append(session_id)

    def clear_token(self) -> None:
        self.cleared = True


@pytest.fixture()
def manager() -> tuple[SessionManager, FakeClient]:
    client = FakeClient()
    return SessionManager(client, heartbeat_interval_s=0.05), client


def test_register_and_is_active(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    assert not session.is_active
    assert session.session_id is None
    assert session.register(name="blender") == "session-1"
    assert session.is_active
    assert session.session_id == "session-1"
    assert client.registered == ["blender"]


def test_register_is_idempotent(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    assert session.register() == "session-1"
    assert session.register() == "session-1"
    assert len(client.registered) == 1


def test_heartbeat_now(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    assert session.heartbeat_now() is False  # not registered yet
    session.register()
    assert session.heartbeat_now() is True
    assert client.heartbeats == ["session-1"]


def test_heartbeat_now_false_on_core_failure(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    session.register()
    client.fail_heartbeat = True
    assert session.heartbeat_now() is False


def test_heartbeat_thread_ticks(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    session.register()
    session.start_heartbeat()
    try:
        time.sleep(0.2)
        assert len(client.heartbeats) >= 1
    finally:
        session.stop_heartbeat()


def test_stop_heartbeat_is_idempotent(manager: tuple[SessionManager, FakeClient]) -> None:
    session, _ = manager
    session.stop_heartbeat()
    session.stop_heartbeat()  # must not raise


def test_deregister_stops_heartbeat_and_clears_id(
    manager: tuple[SessionManager, FakeClient],
) -> None:
    session, client = manager
    session.register()
    session.start_heartbeat()
    session.deregister()
    assert client.deregistered == ["session-1"]
    assert session.session_id is None
    assert not session.is_active


def test_deregister_without_registration_is_safe(
    manager: tuple[SessionManager, FakeClient],
) -> None:
    session, client = manager
    session.deregister()
    assert client.deregistered == []


def test_shutdown_clears_token(manager: tuple[SessionManager, FakeClient]) -> None:
    session, client = manager
    session.register()
    session.shutdown()
    assert client.cleared is True
    assert session.session_id is None


def test_repr_and_str_never_expose_token(
    manager: tuple[SessionManager, FakeClient],
) -> None:
    session, _ = manager
    session.register()
    assert "tok-secret" not in repr(session)
    assert "tok-secret" not in str(session)
    assert "session-1" in repr(session)