"""The shared subprocess bridge behind both out-of-process AI engines (R4).

The application process never imports an engine stack (FR-IMP-03's
isolation, AGENTS.md "Pose engine decision"), so both AI adapters —
HMR2.0 for capture and CondMDI for inbetweening — run their worker as an
external interpreter over the same line-JSON stdin/stdout protocol. The
mechanics of that were duplicated verbatim between the adapters until
this extraction (spec.md's parked after-MVP refactor): spawning with the
no-window flags, pumping stdout on a daemon thread, filtering protocol
lines out of whatever else the engine prints, the ready handshake, the
request round trip, and the teardown that must never orphan a multi-gigabyte
CUDA context.

What stays engine-specific deliberately: the timeouts (a capture request
answers in seconds, a diffusion fill in minutes), the bootstrap payload,
the validation errors, and the typed error class — the bridge raises
through a factory the adapter passes in, so every message a user or test
has ever seen stays byte-identical, worded with the adapter's own engine
label and activity noun.

This module is standard-library only, like the adapters it serves: CI
needs no torch, and the worker scripts (``hmr2_worker.py``,
``condmdi_worker.py``) and their wire protocol are untouched by this
extraction.
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

__all__ = ["EngineWorkerBridge"]

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_TERMINATE_GRACE_S = 5.0


class EngineWorkerBridge:
    """One engine's persistent subprocess: spawn, speak, tear down.

    The lifecycle mirrors what both adapters repeated before the
    extraction (the comments below keep their measured justifications):

    - every failure path goes through :meth:`discard`; dropping the
      references without stopping the process would leave an orphan
      holding its VRAM (T10 measured 2.67 GB for the capture worker)
      with no way to reach it, and a stale ``ready`` would stop the next
      request from respawning;
    - :meth:`ensure_ready` is lazy — constructing an adapter spawns
      nothing, and the first use validates through the adapter's own
      callback, keeping every missing-piece message actionable where it
      is known.
    """

    def __init__(
        self,
        *,
        python_executable: Path,
        worker_script: Path,
        env: Mapping[str, str] | None,
        ready_timeout_s: float,
        request_timeout_s: float,
        engine_label: str,
        activity: str,
        checkpoint: Path,
        error: Callable[[str], RuntimeError],
    ) -> None:
        self._python_executable = python_executable
        self._worker_script = worker_script
        self._env = env
        self._ready_timeout_s = ready_timeout_s
        self._request_timeout_s = request_timeout_s
        self._engine_label = engine_label
        self._activity = activity
        self._checkpoint = checkpoint
        self._error = error
        self._worker: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] | None = None
        self._ready: dict | None = None

    # -- observable state (adapters and their tests read these) ---------------- #

    @property
    def worker(self) -> subprocess.Popen[str] | None:
        """The live process, or ``None`` — every discard clears it."""
        return self._worker

    @property
    def ready(self) -> dict | None:
        """The parsed ready line, or ``None`` before the handshake."""
        return self._ready

    # -- lifecycle -------------------------------------------------------------- #

    def ensure_ready(
        self, validate: Callable[[], None], build_bootstrap: Callable[[], dict]
    ) -> dict:
        """Validate, spawn if needed, and wait for the worker's ready line.

        ``validate`` is the adapter's missing-piece gate and
        ``build_bootstrap`` its request payload — the bridge owns only the
        mechanics in between.
        """
        if self._ready is not None:
            return self._ready
        validate()
        self._spawn(build_bootstrap())
        line = self._next_protocol_line(self._ready_timeout_s)
        if line is None:
            self.discard()
            raise self._error(
                f"the {self._engine_label} engine worker exited before becoming ready "
                f"(checkpoint: {self._checkpoint}); run the engine probe to diagnose it"
            )
        ready = json.loads(line)
        if ready.get("status") != "ready":
            self.discard()
            raise self._error(
                f"the {self._engine_label} engine cannot start: "
                f"{ready.get('message', ready)}"
            )
        self._ready = ready
        return ready

    def request(self, request: dict) -> dict:
        """Write one request line and await the next protocol answer.

        A worker that died mid-request is discarded and answered with the
        typed error envelope — the adapter's response check turns it into
        its own failure, and the next call respawns (M5 L24).
        """
        worker = self._worker
        if worker is None or worker.stdin is None:
            raise self._error(f"the {self._engine_label} engine worker is not running")
        try:
            worker.stdin.write(json.dumps(request) + "\n")
            worker.stdin.flush()
        except OSError:
            self.discard()
            raise self._error(
                f"the {self._engine_label} engine worker stopped responding; "
                f"the next {self._activity} restarts it"
            ) from None
        line = self._next_protocol_line(self._request_timeout_s)
        if line is None:
            self.discard()
            return {
                "status": "error",
                "fatal": True,
                "message": "the engine worker exited mid-request",
            }
        return json.loads(line)

    def discard(self) -> None:
        """Tear the worker down: terminate the process, forget all state."""
        worker = self._worker
        self._worker = None
        self._lines = None
        self._ready = None
        if worker is None:
            return
        with contextlib.suppress(OSError):
            worker.stdin.close()
        try:
            worker.wait(timeout=_TERMINATE_GRACE_S)
        except subprocess.TimeoutExpired:
            worker.terminate()
            try:
                worker.wait(timeout=_TERMINATE_GRACE_S)
            except subprocess.TimeoutExpired:
                worker.kill()

    def shutdown(self) -> None:
        """Terminate the engine worker; idempotent (safe at app close)."""
        self.discard()

    # -- the mechanics ----------------------------------------------------------- #

    def _spawn(self, bootstrap: dict) -> None:
        self._worker = subprocess.Popen(
            [str(self._python_executable), str(self._worker_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=self._env,
            creationflags=_CREATE_NO_WINDOW,
        )
        collected: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read_lines, args=(collected,), daemon=True).start()
        self._lines = collected
        assert self._worker.stdin is not None
        self._worker.stdin.write(json.dumps(bootstrap) + "\n")
        self._worker.stdin.flush()

    def _read_lines(self, collected: queue.Queue[str | None]) -> None:
        worker = self._worker
        if worker is None or worker.stdout is None:
            collected.put(None)
            return
        for line in worker.stdout:
            collected.put(line)
        collected.put(None)  # EOF: the worker exited

    def _next_protocol_line(self, timeout: float) -> str | None:
        """The next protocol line, skipping anything the engine printed.

        ``None`` means the worker exited before answering; exceeding
        ``timeout`` is a hung GPU — the worker is terminated on the spot,
        never left orphaned (R3/R4-2's measured rule).
        """
        assert self._lines is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                self.discard()
                raise self._error(
                    f"the {self._engine_label} engine did not answer within "
                    f"{timeout:.0f} s; check the GPU and the engine environment"
                )
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue  # stray engine print, not a protocol line
            if isinstance(payload, dict) and "status" in payload:
                return line
