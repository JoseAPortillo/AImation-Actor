"""Default configuration for the Blender add-on core (no secrets).

Security model (spec §8 / SpecSecDev):
- The Core URL defaults to the loopback address; only http(s) schemes are
  accepted and the default host set is loopback-only.
- The session token is NEVER configured here and NEVER persisted anywhere:
  it is read per-run from the ``AIMATION_SESSION_TOKEN`` environment
  variable (same convention as the CLI and Tauri frontend — see
  docs/api-tutorial.md) and lives in memory only (spec §3.3).
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

CORE_URL: str = "http://127.0.0.1:8765"
DEFAULT_SESSION_NAME: str = "blender"
DCC_TYPE: str = "blender"
PLUGIN_VERSION: str = "0.1.0"

TOKEN_ENV_VAR: str = "AIMATION_SESSION_TOKEN"

REQUEST_TIMEOUT_S: float = 10.0
POLL_TIMEOUT_S: float = 120.0
POLL_INTERVAL_S: float = 1.0
HEARTBEAT_INTERVAL_S: float = 5.0

# Pipeline defaults mirroring the verified CLI shape (cli.py build_pipeline_graph).
# ``video-source`` treats ``end`` as a *frame index* (not seconds), so
# ``end=5`` extracts the first 5 frames; ``resize`` is the pixel side.
VIDEO_END_FRAMES: int = 5
VIDEO_RESIZE_PX: int = 64

# Graph submissions may run a full pipeline that exceeds REQUEST_TIMEOUT_S.
GRAPH_REQUEST_TIMEOUT_S: float = 120.0

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
_SCHEME_RE = re.compile(r"^https?$", re.IGNORECASE)


def validate_base_url(url: str) -> str:
    """Validate and return ``url`` for client use.

    Rejects non-http(s) schemes outright (SpecSecDev §8: HTTP URLs only) and
    rejects non-loopback hosts so the add-on can never silently talk to a
    remote endpoint.

    Args:
        url: Candidate Core base URL, e.g. ``"http://127.0.0.1:8765"``.

    Returns:
        The URL with any trailing slash stripped.

    Raises:
        ValueError: If the scheme is not http(s) or the host is not loopback.
    """
    parsed = urlparse(url)
    if _SCHEME_RE.fullmatch(parsed.scheme or "") is None:
        raise ValueError(f"rejected Core URL {url!r}: only http(s) URLs are allowed")
    if not parsed.hostname:
        raise ValueError(f"rejected Core URL {url!r}: missing host")
    if parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise ValueError(f"rejected Core URL {url!r}: host {parsed.hostname!r} is not loopback")
    return url.rstrip("/")


def session_token_from_env() -> str:
    """Return the instance token from the environment (memory only).

    Returns:
        The ``AIMATION_SESSION_TOKEN`` value, or ``""`` when unset.
    """
    return os.environ.get(TOKEN_ENV_VAR, "")