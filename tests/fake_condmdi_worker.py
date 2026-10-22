"""Fake CondMDI engine worker: speaks the adapter's line-JSON protocol without
the real engine, so the subprocess bridge is testable in CI.

The real worker (``aimation_actor/adapters/ai/condmdi_worker.py``) imports the
pinned CondMDI stack (torch 1.13, CLIP) and needs a GPU; this fake runs on the
plain application interpreter and follows the same protocol:

    bootstrap line (adapter -> worker): {"engine_root", "repo_dir", "checkpoint",
                                         "mean_path", "std_path", "half_precision"}
    ready line (worker -> adapter):     {"status": "ready", ...} | {"status": "error", ...}
    request line (adapter -> worker):   {"span_frames", "keys", "bind_offsets"}
    response line:                      {"status": "ok", ...} | {"status": "error", ...}

Behaviour is selected by the ``FAKE_CONDMDI_WORKER_MODE`` environment variable:

- ``ok`` (default): ready succeeds; every request gets a deterministic turning
  motion (the pelvis rotates about +Z by ``0.05`` rad per motion sample, height
  90 cm), ``span_frames`` samples long.
- ``ready_error``: the ready line reports a fatal error.
- ``fill_error``: ready succeeds; every request gets a non-fatal error line.
- ``die_mid_request``: ready succeeds; the first request makes the process
  exit without answering.
- ``die_once``: like ``die_mid_request`` on the first process only; a marker
  file (``FAKE_DIED_MARKER``) makes a respawned worker serve ``ok``, so the
  adapter's respawn promise is testable with one configuration.
- ``hang``: ready succeeds; the first request takes the process hostage.

A counter file (``FAKE_CONDMDI_COUNT_FILE``) logs one line per request so
tests can assert exactly how many engine calls a fill makes; a dump file
(``FAKE_CONDMDI_REQUEST_DUMP``) logs each full request as JSONL so tests can
assert exactly what the adapter put on the wire (``guide_frames``, S6).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

_MODE = os.environ.get("FAKE_CONDMDI_WORKER_MODE", "ok")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _died_marker() -> str | None:
    return os.environ.get("FAKE_DIED_MARKER")


def _count_request() -> None:
    path = os.environ.get("FAKE_CONDMDI_COUNT_FILE")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("request\n")


def _dump_request(request: dict) -> None:
    path = os.environ.get("FAKE_CONDMDI_REQUEST_DUMP")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(request) + "\n")


def _canned_pose(sample: int) -> dict:
    """One motion frame of the deterministic turning motion, in domain form."""
    angle = sample * 0.05
    half = angle / 2.0
    return {
        "Pelvis": {
            "quat": [math.cos(half), 0.0, 0.0, math.sin(half)],
            "trans": [0.0, 0.0, 90.0],
        }
    }


def _mark_died() -> None:
    marker = _died_marker()
    if marker:
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("died")


def main() -> None:
    bootstrap = json.loads(sys.stdin.readline())
    if _MODE == "ready_error":
        _emit({"status": "error", "fatal": True, "message": "fake: no CondMDI GPU on this box"})
        return
    _emit({
        "status": "ready",
        "gpu": "fake",
        "vram_total_mib": 2048,
        "motion_fps": 20.0,
        "max_frames": 196,
    })

    pid_path = bootstrap.get("fake_pid_file")
    if pid_path:
        with open(pid_path, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))

    for line in sys.stdin:
        request = json.loads(line)
        if _MODE == "die_mid_request" or (_MODE == "die_once" and not _died_marker_exists()):
            _mark_died()
            os._exit(9)
        if _MODE == "hang":
            time.sleep(600)
        _count_request()
        _dump_request(request)
        if _MODE == "fill_error":
            _emit({"status": "error", "message": "fake: sampling diverged", "fatal": True})
            continue
        span = int(request.get("span_frames", 0))
        poses = [{"frame": sample, "pose": _canned_pose(sample)} for sample in range(span + 1)]
        _emit({"status": "ok", "poses": poses})


def _died_marker_exists() -> bool:
    marker_path = _died_marker()
    return bool(marker_path) and os.path.exists(marker_path)


if __name__ == "__main__":
    main()
