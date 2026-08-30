"""``aimation`` — CLI client for the AImation Actor Core REST API.

An external HTTP client, like the Tauri frontend or a DCC plugin: it talks to
the server over HTTP only and never imports the backend's ``api``, ``domain``
or ``infrastructure`` modules. Configuration comes from the environment
(``AIMATION_URL``, ``AIMATION_TOKEN``), mirroring the backend's ``AIMATION_``
env prefix. The HTTP layer is injectable so tests can swap in fake transports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

PROG = "aimation"
DEFAULT_URL = "http://127.0.0.1:8765"
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
MAX_POLLS = 60
POLL_INTERVAL_SECONDS = 0.5


class CliError(Exception):
    """Fatal CLI error — printed to stderr and mapped to a non-zero exit."""


class ApiClient:
    """Thin HTTP wrapper around the AImation Actor Core REST API.

    Attributes:
        base_url: Server origin (scheme + host + port).
        token: Bearer token; empty means no auth header is sent.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        """Return the Authorization header when a token is configured."""
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _require_token(self) -> None:
        """Raise :class:`CliError` when auth is needed but no token is set."""
        if not self.token:
            raise CliError("AIMATION_TOKEN not set")

    def _expect_object(self, response: httpx.Response) -> dict[str, Any]:
        """Return the JSON object body of a 2xx response, else raise."""
        if response.status_code >= 400:
            raise CliError(_error_message(response))
        if not response.content:
            raise CliError(f"empty response from {response.url}")
        body = response.json()
        if not isinstance(body, dict):
            raise CliError(f"expected a JSON object from {response.url}, got {type(body).__name__}")
        return body

    def _expect_list(self, response: httpx.Response) -> list[Any]:
        """Return the JSON array body of a 2xx response, else raise."""
        if response.status_code >= 400:
            raise CliError(_error_message(response))
        if not response.content:
            raise CliError(f"empty response from {response.url}")
        body = response.json()
        if not isinstance(body, list):
            raise CliError(f"expected a JSON array from {response.url}, got {type(body).__name__}")
        return body

    def health(self) -> dict[str, Any]:
        """Return ``GET /health`` (public — no token needed)."""
        return self._expect_object(self._client.get("/health", headers=self._headers()))

    def nodes(self) -> list[dict[str, Any]]:
        """Return ``GET /nodes/types`` — the node catalog."""
        self._require_token()
        return self._expect_list(self._client.get("/nodes/types", headers=self._headers()))

    def graph_execute(self, graph: dict[str, Any]) -> dict[str, Any]:
        """Submit a graph via ``POST /jobs/graph/execute``; return the job snapshot."""
        self._require_token()
        return self._expect_object(
            self._client.post("/jobs/graph/execute", json=graph, headers=self._headers())
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the ``GET /jobs/{job_id}`` snapshot."""
        self._require_token()
        return self._expect_object(self._client.get(f"/jobs/{job_id}", headers=self._headers()))

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        """Return ``GET /jobs/{job_id}/result``."""
        self._require_token()
        return self._expect_object(
            self._client.get(f"/jobs/{job_id}/result", headers=self._headers())
        )

    def get_job_logs(self, job_id: str) -> list[str]:
        """Return ``GET /jobs/{job_id}/logs``."""
        self._require_token()
        return self._expect_list(self._client.get(f"/jobs/{job_id}/logs", headers=self._headers()))

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _error_message(response: httpx.Response) -> str:
    """Build a concise human-readable message from a non-2xx response."""
    try:
        body: object = response.json()
    except ValueError:
        body = None
    detail = ""
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error") or ""
    if not detail:
        detail = response.text[:200].strip() or response.reason_phrase
    return f"HTTP {response.status_code}: {detail}"


def build_pipeline_graph(
    video_path: str,
    *,
    end: int = 5,
    resize: int = 64,
    height_cm: float | None = None,
) -> dict[str, Any]:
    """Build the video-source → pose-2d → pose-3d → video-to-motion graph.

    Matches the verified pipeline shape from docs/api-tutorial.md §3.

    Args:
        video_path: Video file name, relative to the server's media root.
        end: Extract frames up to this second (default 5).
        resize: Frame resize side in pixels (default 64).
        height_cm: Optional actor height fed to video-to-motion.

    Returns:
        The graph payload as a JSON-serializable dict.
    """
    v2m_params: dict[str, Any] = {}
    if height_cm is not None:
        v2m_params["person_height_cm"] = height_cm
    return {
        "version": "1.0",
        "nodes": [
            {
                "id": "src",
                "type": "video-source",
                "params": {"video_path": video_path, "end": end, "resize": resize},
            },
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


def poll_until_terminal(
    client: ApiClient,
    job_id: str,
    *,
    max_polls: int = MAX_POLLS,
    interval: float = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Poll a job until it reaches a terminal status or the budget is spent.

    Args:
        client: API client used to fetch job snapshots.
        job_id: The job to poll.
        max_polls: Upper bound on the number of polls.
        interval: Seconds to sleep between polls.

    Returns:
        The terminal job snapshot.

    Raises:
        CliError: If the job never reaches ``succeeded``/``failed``/``cancelled``.
    """
    for _ in range(max_polls):
        snapshot = client.get_job(job_id)
        if snapshot.get("status") in TERMINAL_STATUSES:
            return snapshot
        time.sleep(interval)
    raise CliError(f"job {job_id} did not reach a terminal state within {max_polls} polls")


def _save_pretty_json(data: object, path: str) -> None:
    """Write ``data`` to ``path`` as pretty-printed JSON."""
    try:
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write {path}: {exc}") from exc


def _load_graph(path: str) -> dict[str, Any]:
    """Read and parse a graph JSON file."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data: object = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(f"cannot read graph file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError(f"graph file {path} must contain a JSON object")
    return data


def _submit_and_poll(client: ApiClient, graph: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Submit a graph, poll to terminal, and return ``(job_id, snapshot)``."""
    job = client.graph_execute(graph)
    job_id = str(job["job_id"])
    return job_id, poll_until_terminal(client, job_id)


def _report_failure(job_id: str, snapshot: dict[str, Any]) -> int:
    """Print a failed job's error and logs; return a non-zero exit code."""
    if snapshot.get("error"):
        print(f"error: {snapshot['error']}", file=sys.stderr)
    for line in snapshot.get("logs", []):
        print(line)
    return 1


def _cmd_health(client: ApiClient, args: argparse.Namespace) -> int:
    """Health check: print the JSON response; exit non-zero when unhealthy."""
    data = client.health()
    print(json.dumps(data, indent=2))
    if data.get("status") != "ok":
        print(f"error: health status is {data.get('status')!r}", file=sys.stderr)
        return 1
    return 0


def _cmd_nodes(client: ApiClient, args: argparse.Namespace) -> int:
    """Print the node catalog as a compact table."""
    for node in client.nodes():
        print(
            f"{node['type']:<16} [{node['category']}] "
            f"in={len(node['inputs'])} out={len(node['outputs'])}"
        )
    return 0


def _cmd_run(client: ApiClient, args: argparse.Namespace) -> int:
    """Run the full pipeline on a video, poll to terminal, and save the motion."""
    job_id, snapshot = _submit_and_poll(
        client,
        build_pipeline_graph(args.video_path, end=args.end, height_cm=args.height_cm),
    )
    print(f"job {job_id}: {snapshot['status']}")
    if snapshot["status"] == "succeeded":
        if args.output:
            motion = snapshot.get("result", {}).get("outputs", {}).get("v2m", {}).get("motion")
            if motion is None:
                raise CliError(f"job {job_id} succeeded but has no v2m.motion output")
            _save_pretty_json(motion, args.output)
        return 0
    return _report_failure(job_id, snapshot)


def _cmd_graph(client: ApiClient, args: argparse.Namespace) -> int:
    """Execute a graph JSON file, poll to terminal, and save the result."""
    job_id, snapshot = _submit_and_poll(client, _load_graph(args.file))
    print(f"job {job_id}: {snapshot['status']}")
    if snapshot["status"] == "succeeded":
        if args.output:
            _save_pretty_json(client.get_job_result(job_id), args.output)
        return 0
    return _report_failure(job_id, snapshot)


def _cmd_job(client: ApiClient, args: argparse.Namespace) -> int:
    """Print a job snapshot, its result, or its logs."""
    if args.job_action is None:
        print(json.dumps(client.get_job(args.job_id), indent=2))
    elif args.job_action == "result":
        print(json.dumps(client.get_job_result(args.job_id), indent=2))
    else:
        for line in client.get_job_logs(args.job_id):
            print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``aimation`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="AImation Actor Core REST API client.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="check server health (no token required)")
    health.set_defaults(func=_cmd_health)

    nodes = sub.add_parser("nodes", help="list the node catalog")
    nodes.set_defaults(func=_cmd_nodes)

    run = sub.add_parser("run", help="run the video-to-motion pipeline on a video")
    run.add_argument("video_path", help="video file, relative to the server media root")
    run.add_argument(
        "--end", type=int, default=5, help="extract frames up to this second (default: 5)"
    )
    run.add_argument("--height-cm", type=float, default=None, help="actor height in cm (optional)")
    run.add_argument("--output", default=None, help="write the v2m.motion JSON to this file")
    run.set_defaults(func=_cmd_run)

    job = sub.add_parser("job", help="inspect a job")
    job.add_argument("job_id", help="job identifier")
    job_sub = job.add_subparsers(dest="job_action")
    job_sub.add_parser("result", help="print the job result JSON")
    job_sub.add_parser("logs", help="print the job logs")
    job.set_defaults(func=_cmd_job)

    graph = sub.add_parser("graph", help="execute a graph from a JSON file")
    graph.add_argument("file", help="graph JSON file (.aimgraph shape)")
    graph.add_argument("--output", default=None, help="write the result JSON to this file")
    graph.set_defaults(func=_cmd_graph)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (console script ``aimation``)."""
    args = _build_parser().parse_args(argv)
    client = ApiClient(
        base_url=os.environ.get("AIMATION_URL", DEFAULT_URL),
        token=os.environ.get("AIMATION_TOKEN", ""),
    )
    try:
        return int(args.func(client, args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: request failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover - also reachable via entry point
    raise SystemExit(main())
