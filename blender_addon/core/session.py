"""Session lifecycle manager for the Blender add-on (memory-only token).

Implements spec §3 of docs/Plan_DCC_Blender.md: register on enable, heartbeat
every N seconds, deregister on disable. The token stays inside the owning
:class:`~blender_addon.core.client.CoreClient` and is cleared on
:meth:`SessionManager.shutdown` — it is never written to disk, preferences or
the .blend file (spec §3.3 / §8.1).
"""

from __future__ import annotations

import threading

from blender_addon.core import config
from blender_addon.core.client import CoreClient


class SessionManager:
    """Owns one DCC session id and its heartbeat thread.

    Args:
        client: CoreClient whose token authenticates all session calls.
        heartbeat_interval_s: Seconds between heartbeats (spec §3.4: 5 s).
    """

    def __init__(
        self,
        client: CoreClient,
        *,
        heartbeat_interval_s: float = config.HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._client = client
        self._heartbeat_interval_s = heartbeat_interval_s
        self._session_id: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def session_id(self) -> str | None:
        """The registered session id, or None before/after registration."""
        return self._session_id

    @property
    def is_active(self) -> bool:
        """True while a session is registered."""
        return self._session_id is not None

    @property
    def heartbeat_interval_s(self) -> float:
        """The configured heartbeat interval in seconds."""
        return self._heartbeat_interval_s

    def register(self, name: str = config.DEFAULT_SESSION_NAME) -> str:
        """Register the session with the Core and store its id (memory only).

        Idempotent: a second call returns the existing session id without
        hitting the network.
        """
        if self._session_id is not None:
            return self._session_id
        self._session_id = self._client.register_session(name=name)
        return self._session_id

    def heartbeat_now(self) -> bool:
        """Send an immediate heartbeat for the current session.

        Returns:
            True on success; False when no session is registered or the Core
            answered non-2xx.
        """
        if self._session_id is None:
            return False
        return self._client.heartbeat(self._session_id)

    def start_heartbeat(self) -> None:
        """Start the daemon heartbeat thread (no-op if already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._heartbeat_loop, name="aimation-heartbeat", daemon=True
        )
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        """Daemon loop: heartbeat every interval until stopped."""
        while not self._stop.wait(self._heartbeat_interval_s):
            if self._session_id is None:
                continue
            # The loop must survive any transport/serialization hiccup; the
            # session is still valid — the next tick retries.
            try:
                self._client.heartbeat(self._session_id)
            except Exception:  # noqa: BLE001 - keep the keep-alive loop alive
                continue

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread and join it with a bounded wait."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def deregister(self) -> None:
        """Deregister the session, stopping the heartbeat first."""
        self.stop_heartbeat()
        if self._session_id is not None:
            try:
                self._client.deregister_session(self._session_id)
            finally:
                self._session_id = None

    def shutdown(self) -> None:
        """Deregister and drop the token from memory (add-on disable)."""
        self.deregister()
        self._client.clear_token()

    def __repr__(self) -> str:
        """Debug representation that never exposes the token."""
        return (
            f"SessionManager(session_id={self._session_id!r}, "
            f"heartbeat_interval_s={self._heartbeat_interval_s!r})"
        )