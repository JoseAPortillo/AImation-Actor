"""HTTP transport for the AImation Actor Core (bpy-free, stdlib only).

Uses ``urllib.request`` so the add-on runs on Blender's bundled Python
without extra dependencies (spec §2.2 dependency rules — Blender ships no
``httpx``).

Security (SpecSecDev §8): request bodies and Authorization tokens are never
logged; error messages carry only the HTTP status, the path and a short body
excerpt. This module is for JSON traffic only.
"""

from __future__ import annotations

import json as _json  # module alias: the request() param is named ``json``
import typing
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from blender_addon.core.config import REQUEST_TIMEOUT_S


class CoreHttpError(Exception):
    """Raised when the Core returns a non-2xx response or unparsable JSON.

    Attributes:
        status: HTTP status code (0 for transport-level failures such as a
            refused connection or timeout).
        detail: Short, sanitized error text (never tokens or full bodies).
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


@runtime_checkable
class Transport(Protocol):
    """Minimal transport contract: one JSON request/response round trip.

    Implementations must raise :class:`CoreHttpError` for any non-2xx
    response and for unparsable JSON bodies, and must not log request
    bodies or tokens. The ``json`` argument is the JSON-serializable request
    body (None = no body); ``token`` is passed as ``Authorization: Bearer``.
    """

    def request(
        self, method: str, path: str, json: object | None = None, token: str | None = None
    ) -> tuple[int, dict[str, object]]:
        """Perform one request; return ``(status, parsed JSON object)``."""


class UrllibTransport:
    """Concrete :class:`Transport` speaking urllib against one base URL.

    Args:
        base_url: validated Core origin, e.g. ``http://127.0.0.1:8765``.
        timeout_s: per-request timeout in seconds.
    """

    def __init__(self, base_url: str, timeout_s: float = REQUEST_TIMEOUT_S) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def request(
        self, method: str, path: str, json: object | None = None, token: str | None = None
    ) -> tuple[int, dict[str, object]]:
        """Send one JSON request and parse the JSON object response.

        Raises:
            CoreHttpError: On non-2xx responses (with a short sanitized
                detail), connection failures, timeouts, and malformed JSON.
        """
        url = self._base_url + path
        headers = {"Accept": "application/json"}
        if method in {"POST", "PUT", "PATCH"} or json is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"

        data: bytes | None = None
        if json is not None:
            data = _json.dumps(json).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise CoreHttpError(int(exc.code), _error_detail(exc.read())) from exc
        except urllib.error.URLError as exc:
            raise CoreHttpError(0, f"connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise CoreHttpError(0, f"request timed out after {self._timeout_s:g}s") from exc

        if status == 204 or not raw:
            return status, {}
        return status, _parse_json_object(raw, url)


def _parse_json_object(raw: bytes, url: str) -> dict[str, object]:
    """Parse ``raw`` as a JSON object; raise :class:`CoreHttpError` otherwise."""
    text = raw.decode("utf-8", errors="replace")
    try:
        body: object = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise CoreHttpError(200, f"malformed JSON from {url}: {_short(text)}") from exc
    if not isinstance(body, dict):
        raise CoreHttpError(200, f"expected JSON object from {url}, got {type(body).__name__}")
    return typing.cast(dict[str, object], body)


def _error_detail(raw: bytes) -> str:
    """Extract a short detail from an error body (FastAPI-style or text)."""
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        body: object = _json.loads(text)
    except _json.JSONDecodeError:
        body = None
    if isinstance(body, dict):
        for key in ("detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return _short(text) or "request failed"


def _short(text: str, limit: int = 200) -> str:
    """Truncate ``text`` so error messages never grow unbounded."""
    return text[:limit]