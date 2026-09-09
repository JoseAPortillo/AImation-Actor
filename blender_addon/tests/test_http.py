"""Tests for the urllib transport (real loopback HTTP server)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from blender_addon.core.config import validate_base_url
from blender_addon.core.http import CoreHttpError, UrllibTransport

if TYPE_CHECKING:
    from collections.abc import Iterator


class _PlanHandler(BaseHTTPRequestHandler):
    """Responds per a class-level plan: list of (status, body) responses."""

    plan: list[tuple[int, object]] = []
    seen: list[tuple[str, str | None, object]] = []

    def _respond(self) -> None:
        status, body = _PlanHandler.plan.pop(0)
        payload = b""
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode()
        elif isinstance(body, str):
            payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        _record(self)
        self._respond()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        _record(self)
        self._respond()

    def do_DELETE(self) -> None:  # noqa: N802 - http.server API
        _record(self)
        self._respond()

    def log_message(self, *args: object) -> None:  # silence test output
        del args


def _record(handler: _PlanHandler) -> None:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    body: object = None
    if length:
        raw = handler.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw.decode(errors="replace")
    auth = handler.headers.get("Authorization")
    _PlanHandler.seen.append((handler.path, auth, body))


@pytest.fixture()
def server() -> Iterator[str]:
    """Yield a live base URL for a ThreadingHTTPServer on 127.0.0.1:0."""
    _PlanHandler.plan = []
    _PlanHandler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _PlanHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _transport(url: str) -> UrllibTransport:
    return UrllibTransport(validate_base_url(url))


def test_get_parses_json(server: str) -> None:
    _PlanHandler.plan = [(200, {"status": "ok"})]
    status, body = _transport(server).request("GET", "/health")
    assert status == 200
    assert body == {"status": "ok"}
    assert _PlanHandler.seen[0][0] == "/health"


def test_post_json_and_token_header(server: str) -> None:
    _PlanHandler.plan = [(201, {"session_id": "s1"})]
    transport = _transport(server)
    status, body = transport.request(
        "POST", "/sessions/register", json={"dcc_type": "blender"}, token="tok-123"
    )
    assert status == 201
    assert body == {"session_id": "s1"}
    path, auth, payload = _PlanHandler.seen[0]
    assert path == "/sessions/register"
    assert auth == "Bearer tok-123"
    assert payload == {"dcc_type": "blender"}
    assert "tok-123" not in json.dumps(payload)


def test_no_auth_header_when_token_absent(server: str) -> None:
    _PlanHandler.plan = [(200, {"status": "ok"})]
    _transport(server).request("GET", "/health")
    assert _PlanHandler.seen[0][1] is None


def test_non_200_raises_with_fastapi_detail(server: str) -> None:
    _PlanHandler.plan = [(401, {"detail": "Not authenticated"})]
    with pytest.raises(CoreHttpError) as exc:
        _transport(server).request("GET", "/sessions")
    assert exc.value.status == 401
    assert exc.value.detail == "Not authenticated"


def test_500_plain_text_body(server: str) -> None:
    _PlanHandler.plan = [(500, "internal boom")]
    with pytest.raises(CoreHttpError) as exc:
        _transport(server).request("GET", "/sessions")
    assert exc.value.status == 500
    assert exc.value.detail == "internal boom"


def test_malformed_json_body(server: str) -> None:
    _PlanHandler.plan = [(200, "{not json")]
    with pytest.raises(CoreHttpError) as exc:
        _transport(server).request("GET", "/health")
    assert exc.value.status == 200
    assert "json" in exc.value.detail.lower() or "decode" in exc.value.detail.lower()


def test_non_dict_json_body(server: str) -> None:
    _PlanHandler.plan = [(200, ["not", "a", "dict"])]
    with pytest.raises(CoreHttpError) as exc:
        _transport(server).request("GET", "/health")
    assert exc.value.status == 200
    assert "object" in exc.value.detail.lower()


def test_204_no_content(server: str) -> None:
    _PlanHandler.plan = [(204, "")]
    status, body = _transport(server).request("DELETE", "/sessions/s1")
    assert status == 204
    assert body == {}


def test_connection_refused() -> None:
    # An unused loopback port: nothing is listening there. The transport maps
    # transport-level failures to CoreHttpError with status 0.
    transport = UrllibTransport("http://127.0.0.1:1")
    with pytest.raises(CoreHttpError) as exc:
        transport.request("GET", "/health")
    assert exc.value.status == 0
    assert "connection" in exc.value.detail.lower()