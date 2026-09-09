"""Tests for the CoreClient: exact paths, payloads and error semantics."""

from __future__ import annotations

import pytest

from blender_addon.core.client import (
    CoreClient,
    JobCancelledError,
    JobFailedError,
    JobTimeoutError,
    build_video_to_motion_graph,
)
from blender_addon.core.http import CoreHttpError


class FakeTransport:
    """Records requests; returns a scripted series of (status, body).

    An entry may also be an exception instance; it is raised instead of
    returned (simulates transport-level failures).
    """

    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses: list[object] = responses or []
        self.calls: list[tuple[str, str, object, str | None]] = []

    def request(
        self, method: str, path: str, json: object = None, token: str | None = None
    ) -> tuple[int, dict[str, object]]:
        self.calls.append((method, path, json, token))
        if not self.responses:
            return (500, {"detail": "no scripted response"})
        entry = self.responses.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, body = entry
        assert isinstance(body, dict)
        return (status, body)


def _client(
    responses: list[object] | None = None,
    token: str = "tok",
) -> tuple[CoreClient, FakeTransport]:
    transport = FakeTransport(responses)
    return CoreClient(transport, base_url="http://127.0.0.1:8765", token=token), transport


def test_health_ok() -> None:
    client, transport = _client([(200, {"status": "ok"})])
    assert client.health() is True
    # health carries NO token (public endpoint; token stays off the wire).
    assert transport.calls == [("GET", "/health", None, None)]


def test_health_never_raises() -> None:
    client, _ = _client([(500, {"detail": "boom"})])
    assert client.health() is False


def test_health_false_on_non_ok_status() -> None:
    client, _ = _client([(200, {"status": "degraded"})])
    assert client.health() is False


def test_register_session_payload() -> None:
    client, transport = _client([(201, {"session_id": "s1"})])
    session_id = client.register_session("my-session")
    assert session_id == "s1"
    method, path, payload, token = transport.calls[0]
    assert (method, path) == ("POST", "/sessions/register")
    assert token == "tok"
    assert payload == {
        "dcc_type": "my-session",
        "dcc_version": "4.2+",
        "plugin_version": "0.1.0",
        "capabilities": ["shadow_rig", "bake"],
    }


def test_register_session_uses_generated_id() -> None:
    client, _ = _client([(201, {"dcc_type": "blender", "session_id": "gen-1"})])
    assert client.register_session("blender") == "gen-1"


def test_register_session_missing_id_raises() -> None:
    client, _ = _client([(201, {"dcc_type": "blender"})])
    with pytest.raises(ValueError, match="no session_id"):
        client.register_session("blender")


def test_heartbeat() -> None:
    client, transport = _client([(200, {})])
    assert client.heartbeat("s1") is True
    assert transport.calls[0][:2] == ("POST", "/sessions/s1/heartbeat")
    assert transport.calls[0][3] == "tok"


def test_heartbeat_false_on_404() -> None:
    client, transport = _client([CoreHttpError(404, "missing")])
    assert client.heartbeat("gone") is False
    assert transport.calls[0][:2] == ("POST", "/sessions/gone/heartbeat")


def test_deregister_session() -> None:
    client, transport = _client([(204, {})])
    client.deregister_session("s1")
    assert transport.calls[0][:2] == ("DELETE", "/sessions/s1")


def test_deregister_tolerates_404() -> None:
    client, transport = _client([CoreHttpError(404, "missing")])
    client.deregister_session("gone")  # must not raise
    assert transport.calls[0][:2] == ("DELETE", "/sessions/gone")


def test_submit_video_to_motion_omits_none_params() -> None:
    client, transport = _client([(202, {"job_id": "j1", "status": "queued"})])
    job_id = client.submit_video_to_motion("Video_30fps.mp4", end=24)
    assert job_id == "j1"
    method, path, payload, token = transport.calls[0]
    assert (method, path) == ("POST", "/jobs/video-to-motion")
    assert token == "tok"
    assert payload == {"video_path": "Video_30fps.mp4", "end": 24}


def test_submit_video_to_motion_includes_resize() -> None:
    client, transport = _client([(202, {"job_id": "j1"})])
    client.submit_video_to_motion("v.mp4", end=10, resize=128)
    assert transport.calls[0][2] == {"video_path": "v.mp4", "end": 10, "resize": 128}


def test_submit_graph_uses_build_helper() -> None:
    client, transport = _client([(200, {"job_id": "g1"})])
    graph = build_video_to_motion_graph("v.mp4", end=24)
    job_id = client.submit_graph(graph)
    assert job_id == "g1"
    method, path, payload, _ = transport.calls[0]
    assert (method, path) == ("POST", "/jobs/graph/execute")
    assert payload == graph
    assert payload["version"] == "1.0"
    assert [node["id"] for node in payload["nodes"]] == ["src", "p2d", "p3d", "v2m"]
    assert payload["nodes"][0]["params"]["video_path"] == "v.mp4"


def test_build_video_to_motion_graph_applies_cli_defaults() -> None:
    graph = build_video_to_motion_graph("v.mp4")
    src_params = graph["nodes"][0]["params"]
    assert src_params["video_path"] == "v.mp4"
    assert src_params["end"] == 5
    assert src_params["resize"] == 64


def test_get_job_and_result_paths() -> None:
    client, transport = _client(
        [(200, {"id": "j1", "status": "succeeded"}), (200, {"status": "done", "result": {"x": 1}})]
    )
    assert client.get_job("j1")["status"] == "succeeded"
    assert client.get_job_result("j1")["result"] == {"x": 1}
    assert [call[:2] for call in transport.calls] == [
        ("GET", "/jobs/j1"),
        ("GET", "/jobs/j1/result"),
    ]


def test_cancel_job() -> None:
    client, transport = _client([(200, {})])
    client.cancel_job("j1")
    assert transport.calls[0][:2] == ("POST", "/jobs/j1/cancel")


def test_poll_job_result_when_succeeded() -> None:
    client, transport = _client(
        [
            (200, {"id": "j1", "status": "running"}),
            (200, {"id": "j1", "status": "succeeded"}),
            (200, {"status": "done", "result": {"outputs": {}}}),
        ]
    )
    result = client.poll_job_result("j1", timeout_s=5, interval_s=0.01)
    assert result["result"] == {"outputs": {}}
    assert transport.calls[-1][:2] == ("GET", "/jobs/j1/result")


def test_poll_job_result_raises_on_failed() -> None:
    client, _ = _client([(200, {"id": "j1", "status": "failed", "error": "bad video"})])
    with pytest.raises(JobFailedError, match="bad video"):
        client.poll_job_result("j1", timeout_s=5, interval_s=0.01)


def test_poll_job_result_raises_on_cancelled() -> None:
    client, _ = _client([(200, {"id": "j1", "status": "cancelled"})])
    with pytest.raises(JobCancelledError):
        client.poll_job_result("j1", timeout_s=5, interval_s=0.01)


def test_poll_job_result_times_out() -> None:
    client, transport = _client(
        [
            (200, {"id": "j1", "status": "queued"}),
            (200, {"id": "j1", "status": "queued"}),
            (200, {"id": "j1", "status": "queued"}),
        ]
    )
    with pytest.raises(JobTimeoutError):
        client.poll_job_result("j1", timeout_s=0.02, interval_s=0.01)
    assert len(transport.calls) >= 2


def test_core_http_error_propagates() -> None:
    client, _ = _client([CoreHttpError(401, "Not authenticated")])
    with pytest.raises(CoreHttpError) as exc:
        client.get_job("j1")
    assert exc.value.status == 401


def test_clear_token() -> None:
    client, transport = _client([(200, {"id": "j1"})])
    client.clear_token()
    client.get_job("j1")
    # clear_token empties the token string; an empty token never hits the
    # Authorization header (the transport guards on truthiness).
    assert transport.calls[0][3] == ""