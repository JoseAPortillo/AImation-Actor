"""API layer tests: token auth + routers (SDD §4.3, plan §9.3)."""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from aimation_actor_core.infrastructure.virtual import StaticNodeRegistry
from aimation_actor_core.main import create_app
from aimation_actor_core.shared.config import Settings

TEST_TOKEN = "test-instance-token-0123456789abcdef"


def _client(tmp_path: Path | None = None) -> TestClient:
    media_root = tmp_path / "media" if tmp_path else Path("media")
    if tmp_path:
        media_root.mkdir(exist_ok=True)
    app = create_app(
        settings=Settings(session_token=TEST_TOKEN, media_root=media_root)
    )
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def _make_video(path: Path, n_frames: int = 5) -> Path:
    """Create a tiny synthetic video for testing."""
    clip = path
    writer = cv2.VideoWriter(
        str(clip),
        cv2.VideoWriter_fourcc(*"MJPG"),
        25,
        (32, 32),
    )
    try:
        for i in range(n_frames):
            writer.write(np.full((32, 32, 3), i * 10, dtype=np.uint8))
    finally:
        writer.release()
    return clip


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
        # Three virtual seed nodes plus the real AI video-source, pose-2d,
        # pose-3d, video-to-motion and temporal-cleanup nodes.
        assert types == {
            "pass-through",
            "merge",
            "frame-range",
            "video-source",
            "pose-2d",
            "pose-3d",
            "video-to-motion",
            "temporal-cleanup",
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


class TestMediaFrame:
    """Tests for GET /media/frame endpoint."""

    def test_returns_jpeg_with_frame_count(self, tmp_path: Path) -> None:
        """Authenticated request returns JPEG + X-Frame-Count header."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 1},
            headers=_auth(),
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert int(r.headers["x-frame-count"]) == 5
        # Verify it's valid JPEG by loading it
        img = cv2.imdecode(
            np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR
        )
        assert img is not None
        assert img.shape == (32, 32, 3)

    def test_first_frame_1based(self, tmp_path: Path) -> None:
        """frame_index=1 returns the first frame without error."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 1},
            headers=_auth(),
        )
        assert r.status_code == 200
        assert int(r.headers["x-frame-count"]) == 5

    def test_last_frame_1based(self, tmp_path: Path) -> None:
        """frame_index equal to frame count returns the last frame."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 5},
            headers=_auth(),
        )
        assert r.status_code == 200

    def test_out_of_range_frame_returns_400(self, tmp_path: Path) -> None:
        """frame_index beyond video length returns 400."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 100},
            headers=_auth(),
        )
        assert r.status_code == 400

    def test_zero_frame_returns_400(self, tmp_path: Path) -> None:
        """frame_index=0 (invalid for 1-based) returns 400."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 0},
            headers=_auth(),
        )
        assert r.status_code == 400

    def test_traversal_path_returns_400(self, tmp_path: Path) -> None:
        """Traversal in video_path is rejected before file read."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "../clip.avi", "frame_index": 1},
            headers=_auth(),
        )
        assert r.status_code == 400

    def test_unauthenticated_returns_401(self, tmp_path: Path) -> None:
        """Request without token returns 401."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 1},
        )
        assert r.status_code == 401

    def test_with_resize_width(self, tmp_path: Path) -> None:
        """width parameter resizes the frame."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/media/frame",
            params={"video_path": "clip.avi", "frame_index": 1, "width": 16},
            headers=_auth(),
        )
        assert r.status_code == 200
        img = cv2.imdecode(
            np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR
        )
        assert img is not None
        assert img.shape[1] == 16  # width resized


class TestMediaUpload:
    """Tests for POST /media/upload endpoint."""

    def test_valid_upload_stored(self, tmp_path: Path) -> None:
        """Authenticated upload stores file under media_root."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        video_bytes = _make_video_bytes()
        r = c.post(
            "/media/upload",
            headers=_auth(),
            files={"file": ("test_clip.avi", video_bytes, "video/avi")},
        )
        assert r.status_code == 200
        body = r.json()
        assert "reference" in body
        # File should exist under media_root
        stored = media_root / body["reference"]
        assert stored.exists()
        assert stored.is_file()

    def test_upload_returns_correct_reference(self, tmp_path: Path) -> None:
        """Upload returns a reference with uuid prefix and original basename."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        video_bytes = _make_video_bytes()
        r = c.post(
            "/media/upload",
            headers=_auth(),
            files={"file": ("myvideo.avi", video_bytes, "video/avi")},
        )
        assert r.status_code == 200
        ref = r.json()["reference"]
        assert ref.endswith("_myvideo.avi")
        # UUID prefix is 12 chars
        prefix = ref.split("_")[0]
        assert len(prefix) == 12

    def test_oversized_upload_returns_413(self, tmp_path: Path) -> None:
        """Upload exceeding max_video_bytes returns 413."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        # Create a tiny media_root with low max_video_bytes
        app = create_app(
            settings=Settings(
                session_token=TEST_TOKEN,
                media_root=media_root,
                max_video_bytes=100,  # 100 bytes max
            )
        )
        c = TestClient(app)
        # Create a file larger than 100 bytes
        large_bytes = b"\x00" * 200
        r = c.post(
            "/media/upload",
            headers=_auth(),
            files={"file": ("large.avi", large_bytes, "video/avi")},
        )
        assert r.status_code == 413

    def test_unauthenticated_upload_returns_401(self, tmp_path: Path) -> None:
        """Upload without token returns 401."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        video_bytes = _make_video_bytes()
        r = c.post(
            "/media/upload",
            files={"file": ("clip.avi", video_bytes, "video/avi")},
        )
        assert r.status_code == 401

    def test_traversal_filename_returns_400(self, tmp_path: Path) -> None:
        """Upload with path-traversal filename is rejected before write."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        video_bytes = _make_video_bytes()
        r = c.post(
            "/media/upload",
            headers=_auth(),
            files={"file": ("..\\..\\escape.bin", video_bytes, "video/avi")},
        )
        assert r.status_code == 400
        body = r.json()
        assert "traversal" in body["detail"].lower()
        # No file should have been written outside media_root
        outside = tmp_path / "escape.bin"
        assert not outside.exists()

    def test_slash_filename_returns_400(self, tmp_path: Path) -> None:
        """Upload with slash in filename is rejected."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        video_bytes = _make_video_bytes()
        r = c.post(
            "/media/upload",
            headers=_auth(),
            files={"file": ("sub/dir/file.avi", video_bytes, "video/avi")},
        )
        assert r.status_code == 400
        body = r.json()
        assert "traversal" in body["detail"].lower()


class TestDetect:
    """Tests for GET /detect/{video_path}/{frame_index} endpoint."""

    def test_valid_detect_returns_keypoints(self, tmp_path: Path) -> None:
        """Authenticated detect returns keypoints with confidence."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/detect/clip.avi/1",
            headers=_auth(),
        )
        assert r.status_code == 200
        body = r.json()
        assert "keypoints" in body
        assert "confidence" in body
        assert isinstance(body["keypoints"], list)
        assert len(body["keypoints"]) == 17
        assert body["confidence"] == pytest.approx(0.95)

    def test_synthetic_keypoints_match_expected(self, tmp_path: Path) -> None:
        """Synthetic backend returns fixed scripted keypoints."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get(
            "/detect/clip.avi/1",
            headers=_auth(),
        )
        assert r.status_code == 200
        body = r.json()
        labels = [kp["label"] for kp in body["keypoints"]]
        assert labels == [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle",
        ]

    def test_traversal_path_returns_400(self, tmp_path: Path) -> None:
        """Traversal in video_path is rejected before file read."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        c = _client(tmp_path)
        # Use URL-encoded traversal (%2E%2E%2F = ../) so it's not
        # normalized by the HTTP client before reaching the handler.
        r = c.get(
            "/detect/%2E%2E%2Fclip.avi/1",
            headers=_auth(),
        )
        assert r.status_code == 400

    def test_unauthenticated_returns_401(self, tmp_path: Path) -> None:
        """Request without token returns 401."""
        media_root = tmp_path / "media"
        media_root.mkdir()
        _make_video(media_root / "clip.avi")
        c = _client(tmp_path)
        r = c.get("/detect/clip.avi/1")
        assert r.status_code == 401


def _make_video_bytes(n_frames: int = 3) -> bytes:
    """Create a tiny synthetic video and return its bytes."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".avi", delete=False) as f:
        tmp = Path(f.name)
    try:
        _make_video(tmp, n_frames)
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
