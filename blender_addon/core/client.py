"""Typed REST client for the AImation Actor Core (bpy-free).

Mirrors the contracts in ``aimation_actor_core/api/routers/{sessions,jobs}.py``
and the CLI client (``aimation_actor_core/cli.py``): every request except
``GET /health`` carries ``Authorization: Bearer <token>``. The token is held
in memory only and is never logged or written anywhere (spec §3.3).
"""

from __future__ import annotations

import time

from blender_addon.core import config
from blender_addon.core.http import CoreHttpError, Transport

_TERMINAL_SUCCESS = "succeeded"
_TERMINAL_FAILURE = frozenset({"failed", "cancelled"})


class JobFailedError(RuntimeError):
    """The polled job reached the ``failed`` terminal state."""


class JobCancelledError(RuntimeError):
    """The polled job was cancelled."""


class JobTimeoutError(RuntimeError):
    """The polled job did not reach a terminal state within the budget."""


class CoreClient:
    """Thin HTTP client over one :class:`Transport`.

    Args:
        transport: pluggable transport (fake in tests, urllib in Blender).
        base_url: Core origin; validated by :func:`config.validate_base_url`.
        token: optional Bearer token (memory only, never persisted).
    """

    def __init__(self, transport: Transport, base_url: str, token: str | None = None) -> None:
        self._transport = transport
        self._base_url = config.validate_base_url(base_url)
        self._token = token or ""

    @property
    def token(self) -> str:
        """The in-memory Bearer token (clear it via :meth:`clear_token`)."""
        return self._token

    def clear_token(self) -> None:
        """Drop the token from memory (spec §3.3: cleared on disable/exit)."""
        self._token = ""

    def health(self) -> bool:
        """Return True when ``GET /health`` reports a healthy Core.

        Never raises: transport failures and non-``ok`` statuses map to
        False so the UI can show an offline indicator.
        """
        try:
            status, body = self._transport.request("GET", "/health")
        except CoreHttpError:
            return False
        return status < 400 and body.get("status") == "ok"

    def register_session(self, name: str = config.DEFAULT_SESSION_NAME) -> str:
        """Register a DCC session (``POST /sessions/register``) and return its id.

        The ``name`` argument maps to the server's ``dcc_type`` field
        (``"blender"`` for this add-on). The Core generates the session id
        server-side; the payload mirrors the ``DCCSession`` domain model.

        Args:
            name: dcc_type value for the register payload.

        Returns:
            The registered ``session_id``.

        Raises:
            CoreHttpError: On non-2xx responses (incl. 401 without a token).
            ValueError: If the response is missing ``session_id``.
        """
        payload: dict[str, object] = {
            "dcc_type": name,
            "dcc_version": "4.2+",
            "plugin_version": config.PLUGIN_VERSION,
            "capabilities": ["shadow_rig", "bake"],
        }
        status, body = self._transport.request(
            "POST", "/sessions/register", json=payload, token=self._token
        )
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError(f"register_session: response has no session_id (status {status})")
        return session_id

    def heartbeat(self, session_id: str) -> bool:
        """Refresh a session heartbeat; False when the session is unknown.

        ``POST /sessions/{session_id}/heartbeat``. Non-2xx (e.g. 404) maps
        to False so the heartbeat loop can degrade gracefully.
        """
        try:
            self._transport.request(
                "POST", f"/sessions/{session_id}/heartbeat", token=self._token
            )
        except CoreHttpError:
            return False
        return True

    def deregister_session(self, session_id: str) -> None:
        """Deregister a session via ``DELETE /sessions/{session_id}``.

        A 404 is tolerated (session already gone) so cleanup is idempotent.
        """
        try:
            self._transport.request("DELETE", f"/sessions/{session_id}", token=self._token)
        except CoreHttpError as exc:
            if exc.status != 404:
                raise

    def submit_video_to_motion(
        self, video_path: str, *, end: int | None = None, resize: int | None = None
    ) -> str:
        """Submit a video-to-motion job (``POST /jobs/video-to-motion``).

        The payload keys match the ``video-source`` node params verified in
        the CLI pipeline graph and docs/api-tutorial.md (``video_path``,
        ``end``, ``resize``); the router accepts a free-form dict. Note that
        in today's Core this endpoint completes as a stub echo — the live
        NeutralMotion producer is the full graph (see
        :meth:`submit_graph` and :func:`build_video_to_motion_graph`).

        Args:
            video_path: Video file name relative to the server's media root.
            end: Optional frame-extraction cut-off (see the Core node docs).
            resize: Optional frame resize side in pixels.

        Returns:
            The new ``job_id``.

        Raises:
            CoreHttpError: On non-2xx responses.
            ValueError: If the response is missing ``job_id``.
        """
        payload: dict[str, object] = {"video_path": video_path}
        if end is not None:
            payload["end"] = end
        if resize is not None:
            payload["resize"] = resize
        status, body = self._transport.request(
            "POST", "/jobs/video-to-motion", json=payload, token=self._token
        )
        job_id = body.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError(f"submit_video_to_motion: response has no job_id (status {status})")
        return job_id

    def submit_graph(self, graph: dict[str, object]) -> str:
        """Submit a node graph (``POST /jobs/graph/execute``); return ``job_id``.

        This is the only endpoint wired to the live pipeline in the current
        Core (synchronous executor per ADR-002), so it is the path that
        returns a genuine NeutralMotion document today.
        """
        status, body = self._transport.request(
            "POST", "/jobs/graph/execute", json=graph, token=self._token
        )
        job_id = body.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError(f"submit_graph: response has no job_id (status {status})")
        return job_id

    def cancel_job(self, job_id: str) -> dict[str, object]:
        """Request cancellation via ``POST /jobs/{job_id}/cancel``."""
        _, body = self._transport.request(
            "POST", f"/jobs/{job_id}/cancel", token=self._token
        )
        return body

    def get_job(self, job_id: str) -> dict[str, object]:
        """Return the current ``GET /jobs/{job_id}`` snapshot."""
        _, body = self._transport.request("GET", f"/jobs/{job_id}", token=self._token)
        return body

    def get_job_result(self, job_id: str) -> dict[str, object]:
        """Return ``GET /jobs/{job_id}/result`` (``{"status", "result"}``)."""
        _, body = self._transport.request("GET", f"/jobs/{job_id}/result", token=self._token)
        return body

    def poll_job_result(
        self,
        job_id: str,
        *,
        timeout_s: float = config.POLL_TIMEOUT_S,
        interval_s: float = config.POLL_INTERVAL_S,
    ) -> dict[str, object]:
        """Poll ``GET /jobs/{job_id}`` until terminal and return the result.

        Args:
            job_id: Job to poll.
            timeout_s: Total polling budget in seconds.
            interval_s: Seconds between polls.

        Returns:
            The ``get_job_result`` payload for a succeeded job.

        Raises:
            JobFailedError: If the job reaches ``failed``.
            JobCancelledError: If the job is cancelled.
            JobTimeoutError: If the terminal state is not reached in time.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            snapshot = self.get_job(job_id)
            status = snapshot.get("status")
            if status == _TERMINAL_SUCCESS:
                return self.get_job_result(job_id)
            if status in _TERMINAL_FAILURE:
                raise _terminal_error(status, snapshot.get("error"), job_id)
            if time.monotonic() >= deadline:
                raise JobTimeoutError(f"job {job_id} did not finish within {timeout_s:g}s")
            time.sleep(interval_s)


def _terminal_error(status: object, detail: object, job_id: str) -> RuntimeError:
    """Build the JobFailed/JobCancelled error for a terminal snapshot."""
    message = _error_text(detail, job_id)
    if status == "cancelled":
        return JobCancelledError(message)
    return JobFailedError(message)


def _error_text(detail: object, job_id: str) -> str:
    """Return ``detail`` when it is a non-empty string, else a job label."""
    if isinstance(detail, str) and detail:
        return detail
    return f"job {job_id}"


def build_video_to_motion_graph(
    video_path: str,
    *,
    end: int | None = config.VIDEO_END_FRAMES,
    resize: int | None = config.VIDEO_RESIZE_PX,
    height_cm: float | None = None,
) -> dict[str, object]:
    """Return the verified video pipeline graph (CLI-compatible shape).

    Mirrors ``aimation_actor_core.cli.build_pipeline_graph`` so the add-on
    can request a REAL NeutralMotion document from the Core without
    importing backend modules (a DCC plugin is a pure HTTP client).
    """
    v2m_params: dict[str, object] = {}
    if height_cm is not None:
        v2m_params["person_height_cm"] = height_cm
    src_params: dict[str, object] = {"video_path": video_path}
    if end is not None:
        src_params["end"] = end
    if resize is not None:
        src_params["resize"] = resize
    return {
        "version": "1.0",
        "nodes": [
            {"id": "src", "type": "video-source", "params": src_params},
            {"id": "p2d", "type": "pose-2d", "params": {"model": "synthetic"}},
            {"id": "p3d", "type": "pose-3d", "params": {"model": "synthetic"}},
            {"id": "v2m", "type": "video-to-motion", "params": v2m_params},
        ],
        "edges": [
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
        ],
    }