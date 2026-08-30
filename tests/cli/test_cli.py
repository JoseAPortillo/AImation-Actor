"""CLI client tests: graph building, ApiClient HTTP behavior, command output.

The suite is deterministic and network-free: pure logic (pipeline graph
builder, polling) is tested directly, command runners get a fake
:class:`ApiClient` with canned responses, and the real :class:`ApiClient` is
exercised against ``httpx.MockTransport`` handlers to verify request paths,
auth headers, and error mapping.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from aimation_actor_core.cli import (
    ApiClient,
    CliError,
    _build_parser,
    _cmd_graph,
    _cmd_health,
    _cmd_job,
    _cmd_nodes,
    _cmd_run,
    build_pipeline_graph,
    main,
    poll_until_terminal,
)

FAKE_JOB_ID = "job-1"


def _api_client(handler: Callable[[httpx.Request], httpx.Response]) -> ApiClient:
    """Real ApiClient backed by an in-memory transport (no network)."""
    return ApiClient(
        base_url="http://testserver",
        token="test-token",
        client=httpx.Client(
            base_url="http://testserver",
            transport=httpx.MockTransport(handler),
        ),
    )


class _FakeClient(ApiClient):
    """ApiClient subclass returning canned responses without any HTTP."""

    def __init__(
        self,
        *,
        health_body: dict[str, Any] | None = None,
        nodes_body: list[dict[str, Any]] | None = None,
        job_id: str = FAKE_JOB_ID,
        snapshots: dict[str, dict[str, Any]] | None = None,
        result_body: dict[str, Any] | None = None,
        logs_body: list[str] | None = None,
    ) -> None:
        super().__init__(
            base_url="http://fake",
            token="test-token",
            client=httpx.Client(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
            ),
        )
        self._health_body = health_body or {"status": "ok"}
        self._nodes_body = nodes_body or []
        self._job_id = job_id
        self._snapshots = snapshots or {
            job_id: {"job_id": job_id, "status": "succeeded", "result": None, "logs": []}
        }
        self._result_body = result_body or {"status": "succeeded", "result": None}
        self._logs_body = logs_body or []
        self.submitted: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        return self._health_body

    def nodes(self) -> list[dict[str, Any]]:
        return self._nodes_body

    def graph_execute(self, graph: dict[str, Any]) -> dict[str, Any]:
        self.submitted.append(graph)
        return {"job_id": self._job_id, "kind": "graph-execute", "status": "queued"}

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._snapshots[job_id]

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        return self._result_body

    def get_job_logs(self, job_id: str) -> list[str]:
        return self._logs_body


class TestBuildPipelineGraph:
    def test_defaults_match_verified_pipeline(self) -> None:
        graph = build_pipeline_graph("sample.avi")
        assert graph["version"] == "1.0"
        assert graph["nodes"] == [
            {
                "id": "src",
                "type": "video-source",
                "params": {"video_path": "sample.avi", "end": 5, "resize": 64},
            },
            {"id": "p2d", "type": "pose-2d", "params": {"model": "synthetic"}},
            {"id": "p3d", "type": "pose-3d", "params": {"model": "synthetic"}},
            {"id": "v2m", "type": "video-to-motion", "params": {}},
        ]
        assert graph["edges"] == [
            {
                "id": "e1",
                "source": {"node": "src", "port": "frames"},
                "target": {"node": "p2d", "port": "frames"},
            },
            {
                "id": "e2",
                "source": {"node": "p2d", "port": "keypoints"},
                "target": {"node": "p3d", "port": "keypoints"},
            },
            {
                "id": "e3",
                "source": {"node": "p3d", "port": "keypoints_3d"},
                "target": {"node": "v2m", "port": "keypoints_3d"},
            },
        ]

    def test_options_override_defaults(self) -> None:
        graph = build_pipeline_graph("clip.avi", end=10, resize=32, height_cm=175.0)
        assert graph["nodes"][0]["params"] == {
            "video_path": "clip.avi",
            "end": 10,
            "resize": 32,
        }
        assert graph["nodes"][3]["params"] == {"person_height_cm": 175.0}


class TestApiClient:
    def test_health_is_public_and_sends_no_auth_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["authorization"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"status": "ok", "video": "loaded"})

        client = ApiClient(
            base_url="http://testserver",
            token="",
            client=httpx.Client(
                base_url="http://testserver",
                transport=httpx.MockTransport(handler),
            ),
        )
        assert client.health() == {"status": "ok", "video": "loaded"}
        assert captured["path"] == "/health"
        assert captured["authorization"] is None

    def test_nodes_sends_bearer_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/nodes/types"
            assert request.headers.get("Authorization") == "Bearer test-token"
            return httpx.Response(200, json=[])

        assert _api_client(handler).nodes() == []

    def test_graph_execute_posts_graph_json(self) -> None:
        graph = build_pipeline_graph("clip.avi")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/jobs/graph/execute"
            assert request.headers["Content-Type"].startswith("application/json")
            assert json.loads(request.read()) == graph
            return httpx.Response(
                200, json={"job_id": "j1", "kind": "graph-execute", "status": "queued"}
            )

        job = _api_client(handler).graph_execute(graph)
        assert job["job_id"] == "j1"

    def test_get_job_result_and_logs_paths(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/jobs/job-1/result":
                return httpx.Response(200, json={"status": "succeeded", "result": {"outputs": {}}})
            assert request.url.path == "/jobs/job-1/logs"
            return httpx.Response(200, json=["log line"])

        client = _api_client(handler)
        assert client.get_job_result("job-1")["status"] == "succeeded"
        assert client.get_job_logs("job-1") == ["log line"]

    def test_missing_token_fails_before_any_request(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json={})

        client = ApiClient(
            base_url="http://testserver",
            token="",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(CliError, match="AIMATION_TOKEN not set"):
            client.nodes()
        with pytest.raises(CliError, match="AIMATION_TOKEN not set"):
            client.get_job("job-1")
        assert calls == []

    def test_http_401_raises_with_detail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Not authenticated"})

        with pytest.raises(CliError) as exc_info:
            _api_client(handler).get_job("job-1")
        message = str(exc_info.value)
        assert "HTTP 401" in message
        assert "Not authenticated" in message

    def test_http_404_raises_with_detail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "job not found"})

        with pytest.raises(CliError, match="job not found"):
            _api_client(handler).get_job("missing")

    def test_error_without_json_body_falls_back_to_text(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal error")

        with pytest.raises(CliError, match="HTTP 500"):
            _api_client(handler).health()


class TestPoll:
    def test_returns_terminal_snapshot(self) -> None:
        snapshots = {FAKE_JOB_ID: {"job_id": FAKE_JOB_ID, "status": "succeeded", "logs": []}}
        snapshot = poll_until_terminal(
            _FakeClient(snapshots=snapshots), FAKE_JOB_ID, max_polls=1, interval=0
        )
        assert snapshot["status"] == "succeeded"

    def test_times_out_after_max_polls(self) -> None:
        snapshots = {FAKE_JOB_ID: {"job_id": FAKE_JOB_ID, "status": "running", "logs": []}}
        with pytest.raises(CliError, match=FAKE_JOB_ID):
            poll_until_terminal(
                _FakeClient(snapshots=snapshots), FAKE_JOB_ID, max_polls=3, interval=0
            )


class TestHealthCommand:
    def test_prints_json_and_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient(health_body={"status": "ok", "video": "loaded", "pose": "synthetic"})
        assert _cmd_health(client, _build_parser().parse_args(["health"])) == 0
        out = capsys.readouterr().out
        assert '"status": "ok"' in out
        assert '"video": "loaded"' in out

    def test_unhealthy_status_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient(health_body={"status": "degraded"})
        assert _cmd_health(client, _build_parser().parse_args(["health"])) == 1
        assert "degraded" in capsys.readouterr().err


class TestNodesCommand:
    def test_prints_compact_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient(
            nodes_body=[
                {
                    "type": "video-source",
                    "category": "source",
                    "title": "Video Source",
                    "inputs": [],
                    "outputs": [{"name": "frames"}, {"name": "fps"}],
                    "params": [],
                },
                {
                    "type": "pose-2d",
                    "category": "ai",
                    "title": "Pose 2D",
                    "inputs": [{"name": "frames"}],
                    "outputs": [{"name": "keypoints"}],
                    "params": [],
                },
            ]
        )
        assert _cmd_nodes(client, _build_parser().parse_args(["nodes"])) == 0
        assert capsys.readouterr().out == (
            "video-source     [source] in=0 out=2\npose-2d          [ai] in=1 out=1\n"
        )


class TestRunCommand:
    def test_success_saves_motion_and_passes_options(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        motion = {"skeleton": [{"bone": "hip"}], "frames": [0, 1]}
        snapshots = {
            FAKE_JOB_ID: {
                "job_id": FAKE_JOB_ID,
                "status": "succeeded",
                "result": {"outputs": {"v2m": {"motion": motion}}},
                "logs": [],
            }
        }
        client = _FakeClient(snapshots=snapshots)
        out_file = tmp_path / "motion.json"
        args = _build_parser().parse_args(
            ["run", "clip.avi", "--end", "3", "--height-cm", "170.5", "--output", str(out_file)]
        )
        assert _cmd_run(client, args) == 0
        assert out_file.read_text(encoding="utf-8") == json.dumps(motion, indent=2) + "\n"
        assert "job job-1: succeeded" in capsys.readouterr().out
        assert client.submitted == [build_pipeline_graph("clip.avi", end=3, height_cm=170.5)]

    def test_success_without_output_only_prints_status(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        snapshots = {
            FAKE_JOB_ID: {
                "job_id": FAKE_JOB_ID,
                "status": "succeeded",
                "result": {"outputs": {"v2m": {"motion": 1}}},
                "logs": [],
            }
        }
        client = _FakeClient(snapshots=snapshots)
        assert _cmd_run(client, _build_parser().parse_args(["run", "clip.avi"])) == 0
        assert "job job-1: succeeded" in capsys.readouterr().out

    def test_failed_prints_error_and_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        snapshots = {
            FAKE_JOB_ID: {
                "job_id": FAKE_JOB_ID,
                "status": "failed",
                "error": "boom",
                "logs": ["l1", "l2"],
            }
        }
        client = _FakeClient(snapshots=snapshots)
        assert _cmd_run(client, _build_parser().parse_args(["run", "clip.avi"])) == 1
        captured = capsys.readouterr()
        assert "job job-1: failed" in captured.out
        assert "boom" in captured.err
        assert "l1" in captured.out
        assert "l2" in captured.out

    def test_succeeded_without_motion_output_raises(self, tmp_path: Path) -> None:
        snapshots = {
            FAKE_JOB_ID: {
                "job_id": FAKE_JOB_ID,
                "status": "succeeded",
                "result": {"outputs": {}},
                "logs": [],
            }
        }
        client = _FakeClient(snapshots=snapshots)
        args = _build_parser().parse_args(["run", "clip.avi", "--output", str(tmp_path / "m.json")])
        with pytest.raises(CliError, match="v2m.motion"):
            _cmd_run(client, args)


class TestGraphCommand:
    def test_success_saves_result(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        graph = build_pipeline_graph("clip.avi")
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        result_body = {
            "status": "succeeded",
            "result": {"outputs": {"v2m": {"motion": {"a": 1}}}, "logs": []},
        }
        client = _FakeClient(result_body=result_body)
        out_file = tmp_path / "result.json"
        args = _build_parser().parse_args(["graph", str(graph_file), "--output", str(out_file)])
        assert _cmd_graph(client, args) == 0
        assert json.loads(out_file.read_text(encoding="utf-8")) == result_body
        assert client.submitted == [graph]
        assert "job job-1: succeeded" in capsys.readouterr().out

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        with pytest.raises(CliError, match="cannot read graph file"):
            _cmd_graph(_FakeClient(), _build_parser().parse_args(["graph", str(missing)]))

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(CliError, match="cannot read graph file"):
            _cmd_graph(_FakeClient(), _build_parser().parse_args(["graph", str(bad)]))


class TestJobCommand:
    def test_prints_snapshot(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient()
        assert _cmd_job(client, _build_parser().parse_args(["job", FAKE_JOB_ID])) == 0
        out = capsys.readouterr().out
        assert '"job_id": "job-1"' in out
        assert '"status": "succeeded"' in out

    def test_prints_result(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient(
            result_body={"status": "succeeded", "result": {"outputs": {"v2m": {"motion": 1}}}}
        )
        assert _cmd_job(client, _build_parser().parse_args(["job", FAKE_JOB_ID, "result"])) == 0
        assert '"motion": 1' in capsys.readouterr().out

    def test_prints_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        client = _FakeClient(logs_body=["a", "b"])
        assert _cmd_job(client, _build_parser().parse_args(["job", FAKE_JOB_ID, "logs"])) == 0
        assert capsys.readouterr().out == "a\nb\n"


class TestMain:
    def test_token_required_command_without_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("AIMATION_TOKEN", raising=False)
        assert main(["nodes"]) == 1
        assert capsys.readouterr().err == "error: AIMATION_TOKEN not set\n"
