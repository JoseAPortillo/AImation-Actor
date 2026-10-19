"""Fake HMR2.0 engine worker: speaks the adapter's line-JSON protocol without
the real engine, so the subprocess bridge is testable in CI.

The real worker (``aimation_actor/adapters/ai/hmr2_worker.py``) imports the
HMR2.0 stack and needs CUDA; this fake runs on the plain application
interpreter and follows the same protocol:

    bootstrap line (adapter -> worker): {"hmr2_root": ..., "checkpoint": ...,
                                        "smpl_dir": ..., "half_precision": bool}
    ready line (worker -> adapter):     {"status": "ready", ...} | {"status": "error", ...}
    request line (adapter -> worker):   {"image_path": ..., "frame_index": ...}
    response line:                      {"status": "ok", ...} | {"status": "error", ...}

Behaviour is selected by the ``FAKE_HMR2_WORKER_MODE`` environment variable:

- ``ok`` (default): ready succeeds; every request gets the canned result.
- ``ready_error``: the ready line reports a fatal error.
- ``die_mid_request``: ready succeeds; the first request makes the process
  exit without answering.
"""

import json
import os
import sys

_MODE = os.environ.get("FAKE_HMR2_WORKER_MODE", "ok")
_CANNED_ROTATIONS = {
    "Pelvis": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    "L_Hip": [
        0.0, 0.0, 1.0,
        0.0, 1.0, 0.0,
        -1.0, 0.0, 0.0,
    ],  # a 90-degree rotation about Y in SMPL space (row-major 3x3)
}
_TEMPLATE_HIP_CM = 93.85


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    bootstrap = json.loads(sys.stdin.readline())
    if _MODE == "ready_error":
        _emit({"status": "error", "fatal": True, "message": "fake: no CUDA GPU"})
        return
    _emit({
        "status": "ready",
        "gpu": "fake",
        "vram_total_mib": 1024,
        "template_hip_height_cm": _TEMPLATE_HIP_CM,
    })
    pid_path = bootstrap.get("fake_pid_file")
    if pid_path:
        with open(pid_path, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    for line in sys.stdin:
        request = json.loads(line)
        if _MODE == "die_mid_request":
            os._exit(9)
        _emit({
            "status": "ok",
            "frame_index": request.get("frame_index"),
            "hip_height_cm": _TEMPLATE_HIP_CM,
            "per_frame_hip_height_m": 0.87,
            "rotations": _CANNED_ROTATIONS,
        })


if __name__ == "__main__":
    main()
