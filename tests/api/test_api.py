"""API layer tests: token auth + routers (SDD §4.3, plan §9.3)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aimation_actor_core.infrastructure.virtual import StaticNodeRegistry
from aimation_actor_core.main import create_app
from aimation_actor_core.shared.config import Settings

TEST_TOKEN = "test-instance-token-0123456789abcdef"


def _client() -> TestClient:
    app = create_app(settings=Settings(session_token=TEST_TOKEN))
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


class TestAuth:
    def test_health_is_public(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_reports_video_loaded(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["video"] == "loaded"

    def test_health_reports_pose_backend(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.status_code == 200
        # Should report pose backend (synthetic or onnx)
        assert "pose" in r.json()
        assert r.json()["pose"] in ["synthetic", "onnx"]

    def test_health_reports_pose3d_backend(self) -> None:
        c = _client()
        r = c.get("/health")
        assert r.status_code == 200
        # Should report pose3d backend (synthetic or onnx)
        assert "pose3d" in r.json()
        assert r.json()["pose3d"] in ["synthetic", "onnx"]

    def test_protected_endpoint_rejects_no_token(self) -> None:
        c = _client()
        r = c.get("/nodes/types")
        assert r.status_code == 401

    def test_protected_endpoint_rejects_wrong_token(self) -> None:
        c = _client()
        r = c.get("/nodes/types", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_protected_endpoint_accepts_valid_token(self) -> None:
        c = _client()
        r = c.get("/nodes/types", headers=_auth())
        assert r.status_code == 200


class TestNodes:
    def test_list_node_types_lists_seed_nodes(self) -> None:
        c = _client()
        r = c.get("/nodes/types", headers=_auth())
        assert r.status_code == 200
        types = {schema["type"] for schema in r.json()}
        # Three virtual seed nodes plus the real AI video-source, pose-2d and
        # pose-3d nodes.
        assert types == {
            "pass-through",
            "merge",
            "frame-range",
            "video-source",
            "pose-2d",
            "pose-3d",
        }

    def test_list_node_types_empty_registry(self) -> None:
        # Unseeded registry: GET /nodes/types returns an empty list without error
        # (node-registry spec "Empty registry returns empty list").
        app = create_app(settings=Settings(session_token=TEST_TOKEN))
        app.state.node_registry = StaticNodeRegistry()
        c = TestClient(app)
        r = c.get("/nodes/types", headers=_auth())
        assert r.status_code == 200
        assert r.json() == []


class TestSessions:
    def test_session_round_trip(self) -> None:
        c = _client()
        register = c.post(
            "/sessions/register",
            headers=_auth(),
            json={"dcc_type": "maya", "dcc_version": "2025.0", "plugin_version": "0.3.1"},
        )
        assert register.status_code == 201
        body = register.json()
        session_id = body["session_id"]
        assert body["dcc_type"] == "maya"
        assert body["capabilities"] == []

        listed = c.get("/sessions", headers=_auth())
        assert listed.status_code == 200
        assert any(s["session_id"] == session_id for s in listed.json())

        hb = c.post(f"/sessions/{session_id}/heartbeat", headers=_auth())
        assert hb.status_code == 200
        assert hb.json()["session_id"] == session_id

        pushed = c.post(f"/sessions/{session_id}/push_result", headers=_auth(), json={"motion": 1})
        assert pushed.status_code == 202
        assert pushed.json()["accepted"] is True

        deleted = c.delete(f"/sessions/{session_id}", headers=_auth())
        assert deleted.status_code == 204

        gone = c.get("/sessions", headers=_auth())
        assert all(s["session_id"] != session_id for s in gone.json())

    def test_heartbeat_unknown_session_404(self) -> None:
        c = _client()
        r = c.post("/sessions/nope/heartbeat", headers=_auth())
        assert r.status_code == 404

    def test_register_with_explicit_session_id(self) -> None:
        c = _client()
        r = c.post(
            "/sessions/register",
            headers=_auth(),
            json={
                "session_id": "fixed-session-1",
                "dcc_type": "blender",
                "dcc_version": "4.0",
                "plugin_version": "0.1.0",
                "capabilities": ["shadow_rig"],
            },
        )
        assert r.status_code == 201
        assert r.json()["session_id"] == "fixed-session-1"


class TestJobs:
    def test_video_to_motion_submit_and_poll(self) -> None:
        c = _client()
        submit = c.post("/jobs/video-to-motion", headers=_auth(), json={"video": "ref.mp4"})
        assert submit.status_code == 202
        job = submit.json()
        job_id = job["job_id"]
        assert job["kind"] == "video-to-motion"

        poll = c.get(f"/jobs/{job_id}", headers=_auth())
        assert poll.status_code == 200
        assert poll.json()["job_id"] == job_id

        result = c.get(f"/jobs/{job_id}/result", headers=_auth())
        assert result.status_code == 200
        assert result.json()["status"] == "succeeded"

        logs = c.get(f"/jobs/{job_id}/logs", headers=_auth())
        assert logs.status_code == 200
        assert isinstance(logs.json(), list)

    def test_graph_execute_end_to_end_succeeds(self) -> None:
        c = _client()
        r = c.post(
            "/jobs/graph/execute",
            headers=_auth(),
            json={
                "version": "0.1",
                "nodes": [
                    {"id": "src", "type": "frame-range", "params": {"start": 0, "end": 3}},
                    {"id": "pt1", "type": "pass-through"},
                    {"id": "pt2", "type": "pass-through"},
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": {"node": "src", "port": "frames"},
                        "target": {"node": "pt1", "port": "input"},
                    },
                    {
                        "id": "e2",
                        "source": {"node": "pt1", "port": "output"},
                        "target": {"node": "pt2", "port": "input"},
                    },
                ],
            },
        )
        assert r.status_code == 200
        job = r.json()
        assert job["kind"] == "graph-execute"
        assert job["status"] == "succeeded"
        assert len(job["logs"]) == 3
        assert job["result"]["outputs"]["pt2"]["output"] == [0, 1, 2]

    def test_graph_execute_unknown_type_fails(self) -> None:
        c = _client()
        r = c.post(
            "/jobs/graph/execute",
            headers=_auth(),
            json={"version": "0.1", "nodes": [{"id": "a", "type": "alien-node"}], "edges": []},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert r.json()["error"]

    def test_graph_execute_cycle_fails(self) -> None:
        c = _client()
        r = c.post(
            "/jobs/graph/execute",
            headers=_auth(),
            json={
                "version": "0.1",
                "nodes": [
                    {"id": "a", "type": "pass-through"},
                    {"id": "b", "type": "pass-through"},
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": {"node": "a", "port": "output"},
                        "target": {"node": "b", "port": "input"},
                    },
                    {
                        "id": "e2",
                        "source": {"node": "b", "port": "output"},
                        "target": {"node": "a", "port": "input"},
                    },
                ],
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "failed"

    def test_graph_execute_video_source_end_to_end(self, tmp_path: Path) -> None:
        # Build a synthetic video fixture under a tmp media_root, then run
        # video-source through the graph executor end-to-end.
        media_root = tmp_path / "media"
        media_root.mkdir()
        clip = media_root / "clip.avi"
        writer = cv2.VideoWriter(
            str(clip),
            cv2.VideoWriter_fourcc(*"MJPG"),
            25,
            (32, 32),
        )
        try:
            for i in range(5):
                writer.write(np.full((32, 32, 3), i * 10, dtype=np.uint8))
        finally:
            writer.release()

        app = create_app(settings=Settings(session_token=TEST_TOKEN, media_root=media_root))
        c = TestClient(app)
        r = c.post(
            "/jobs/graph/execute",
            headers=_auth(),
            json={
                "version": "0.1",
                "nodes": [
                    {"id": "src", "type": "video-source", "params": {"video_path": "clip.avi"}},
                    {"id": "pt", "type": "pass-through"},
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": {"node": "src", "port": "frames"},
                        "target": {"node": "pt", "port": "input"},
                    },
                ],
            },
        )
        assert r.status_code == 200
        job = r.json()
        assert job["status"] == "succeeded"
        outputs = job["result"]["outputs"]
        assert len(outputs["src"]["frames"]) == 5
        assert outputs["src"]["fps"] == pytest.approx(25)

    def test_unknown_job_404(self) -> None:
        c = _client()
        assert c.get("/jobs/missing", headers=_auth()).status_code == 404
