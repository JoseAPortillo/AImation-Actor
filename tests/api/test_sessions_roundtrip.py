"""Tests for DCC session endpoints (Phase B round-trip).

Tests cover:
- push_result: queue golden poses for addon delivery
- pending: addon polls for queued payloads
- submit_edited_poses: addon sends edited poses back
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aimation_actor_core.api.deps import get_session_store, require_token
from aimation_actor_core.api.routers.sessions import router
from aimation_actor_core.domain.dcc.push_payload import PushPayload
from aimation_actor_core.domain.dcc.session import DCCSession, DCCType, SessionStore
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion, NeutralMeta, KeyPose
from aimation_actor_core.infrastructure.virtual.stores import InMemorySessionStore


class _FakeSettings:
    """Minimal settings for test client."""
    session_token = "test-token"


@pytest.fixture()
def app() -> FastAPI:
    """Create a test app with the sessions router."""
    app = FastAPI()
    app.state.settings = _FakeSettings()
    app.include_router(router)
    return app


@pytest.fixture()
def store() -> InMemorySessionStore:
    """Create a fresh in-memory session store."""
    return InMemorySessionStore()


@pytest.fixture()
def client(app: FastAPI, store: InMemorySessionStore) -> TestClient:
    """Create a test client with the store injected."""
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[require_token] = lambda: "test-token"
    return TestClient(app)


@pytest.fixture()
def registered_session(client: TestClient, store: InMemorySessionStore) -> DCCSession:
    """Register a session and return it."""
    payload = {
        "dcc_type": "blender",
        "dcc_version": "4.2+",
        "plugin_version": "0.1.0",
        "capabilities": ["shadow_rig", "bake"],
    }
    resp = client.post("/sessions/register", json=payload)
    assert resp.status_code == 201
    return DCCSession(**resp.json())


@pytest.fixture()
def sample_motion() -> NeutralMotion:
    """Create a sample NeutralMotion document."""
    return NeutralMotion(
        meta=NeutralMeta(fps=24.0, units="cm"),
        frames=[],
        keyposes=[KeyPose(frame=1, weight=1.0)],
    )


class TestPushResult:
    """Tests for POST /sessions/{id}/push_result."""

    def test_push_result_queues_payload(
        self, client: TestClient, registered_session: DCCSession, sample_motion: NeutralMotion
    ) -> None:
        """Push result should queue the payload for the session."""
        payload = {
            "kind": "golden_poses",
            "motion": sample_motion.model_dump(),
        }
        resp = client.post(f"/sessions/{registered_session.session_id}/push_result", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["session_id"] == registered_session.session_id
        assert data["kind"] == "golden_poses"

    def test_push_result_unknown_session(self, client: TestClient, sample_motion: NeutralMotion) -> None:
        """Push result to unknown session should return 404."""
        payload = {
            "kind": "golden_poses",
            "motion": sample_motion.model_dump(),
        }
        resp = client.post("/sessions/nonexistent/push_result", json=payload)
        assert resp.status_code == 404


class TestPending:
    """Tests for GET /sessions/{id}/pending."""

    def test_pending_returns_queued_payload(
        self, client: TestClient, registered_session: DCCSession, sample_motion: NeutralMotion
    ) -> None:
        """Pending endpoint should return the next queued payload."""
        # First, push a payload
        push_payload = {
            "kind": "golden_poses",
            "motion": sample_motion.model_dump(),
        }
        client.post(f"/sessions/{registered_session.session_id}/push_result", json=push_payload)

        # Now poll for pending
        resp = client.get(f"/sessions/{registered_session.session_id}/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "golden_poses"
        assert "motion" in data

    def test_pending_returns_204_when_empty(self, client: TestClient, registered_session: DCCSession) -> None:
        """Pending endpoint should return 204 when no payloads are queued."""
        resp = client.get(f"/sessions/{registered_session.session_id}/pending")
        assert resp.status_code == 204

    def test_pending_unknown_session(self, client: TestClient) -> None:
        """Pending endpoint should return 404 for unknown session."""
        resp = client.get("/sessions/nonexistent/pending")
        assert resp.status_code == 404

    def test_pending_fifo_order(
        self, client: TestClient, registered_session: DCCSession, sample_motion: NeutralMotion
    ) -> None:
        """Pending endpoint should return payloads in FIFO order."""
        session_id = registered_session.session_id

        # Push two payloads
        payload1 = {"kind": "golden_poses", "motion": sample_motion.model_dump()}
        payload2 = {"kind": "golden_poses", "motion": sample_motion.model_dump()}
        client.post(f"/sessions/{session_id}/push_result", json=payload1)
        client.post(f"/sessions/{session_id}/push_result", json=payload2)

        # First poll should return first payload
        resp1 = client.get(f"/sessions/{session_id}/pending")
        assert resp1.status_code == 200

        # Second poll should return second payload
        resp2 = client.get(f"/sessions/{session_id}/pending")
        assert resp2.status_code == 200

        # Third poll should return 204
        resp3 = client.get(f"/sessions/{session_id}/pending")
        assert resp3.status_code == 204


class TestSubmitEditedPoses:
    """Tests for POST /sessions/{id}/submit_edited_poses."""

    def test_submit_edited_poses(
        self, client: TestClient, registered_session: DCCSession, sample_motion: NeutralMotion
    ) -> None:
        """Submit edited poses should accept and store the payload."""
        payload = {
            "kind": "edited_poses",
            "motion": sample_motion.model_dump(),
        }
        resp = client.post(
            f"/sessions/{registered_session.session_id}/submit_edited_poses",
            json=payload,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "received"
        assert data["kind"] == "edited_poses"

    def test_submit_edited_poses_unknown_session(
        self, client: TestClient, sample_motion: NeutralMotion
    ) -> None:
        """Submit edited poses to unknown session should return 404."""
        payload = {
            "kind": "edited_poses",
            "motion": sample_motion.model_dump(),
        }
        resp = client.post("/sessions/nonexistent/submit_edited_poses", json=payload)
        assert resp.status_code == 404


class TestSessionStoreQueue:
    """Tests for the InMemorySessionStore queue methods."""

    def test_enqueue_dequeue(self, store: InMemorySessionStore, sample_motion: NeutralMotion) -> None:
        """Enqueue and dequeue should work as FIFO."""
        session = store.register(DCCSession(
            dcc_type=DCCType.BLENDER,
            dcc_version="4.2+",
            plugin_version="0.1.0",
        ))

        payload = PushPayload(kind="golden_poses", motion=sample_motion)
        assert store.enqueue(session.session_id, payload) is True

        result = store.dequeue(session.session_id)
        assert result is not None
        assert result.kind == "golden_poses"

    def test_pending_count(self, store: InMemorySessionStore, sample_motion: NeutralMotion) -> None:
        """Pending count should return the number of queued payloads."""
        session = store.register(DCCSession(
            dcc_type=DCCType.BLENDER,
            dcc_version="4.2+",
            plugin_version="0.1.0",
        ))

        assert store.pending_count(session.session_id) == 0

        payload = PushPayload(kind="golden_poses", motion=sample_motion)
        store.enqueue(session.session_id, payload)
        assert store.pending_count(session.session_id) == 1

        store.dequeue(session.session_id)
        assert store.pending_count(session.session_id) == 0

    def test_enqueue_unknown_session(self, store: InMemorySessionStore, sample_motion: NeutralMotion) -> None:
        """Enqueue to unknown session should return False."""
        payload = PushPayload(kind="golden_poses", motion=sample_motion)
        assert store.enqueue("nonexistent", payload) is False

    def test_deregister_clears_queue(self, store: InMemorySessionStore, sample_motion: NeutralMotion) -> None:
        """Deregistering a session should clear its queue."""
        session = store.register(DCCSession(
            dcc_type=DCCType.BLENDER,
            dcc_version="4.2+",
            plugin_version="0.1.0",
        ))

        payload = PushPayload(kind="golden_poses", motion=sample_motion)
        store.enqueue(session.session_id, payload)
        assert store.pending_count(session.session_id) == 1

        store.deregister(session.session_id)
        assert store.pending_count(session.session_id) == 0
