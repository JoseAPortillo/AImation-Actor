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
- ``die_once``: like ``die_mid_request`` on the first process only; a marker
  file (``FAKE_DIED_MARKER``) makes a respawned worker serve ``ok``, so the
  adapter's respawn promise is testable with one configuration.
- ``hang``: ready succeeds; the first request takes the process hostage
  (never answers) so a timeout path can be exercised.
"""

import json
import os
import sys
import time

_MODE = os.environ.get("FAKE_HMR2_WORKER_MODE", "ok")
_CANNED_ROTATIONS = {
    # The pelvis is the engine's global orient. The engine's output frame is
    # the camera's (Y pointing down), so for a person standing upright the
    # network reports R_x(180) here -- measured on the bundled clip (T15).
    # The adapter undoes that flip; a canned identity would mean an
    # upside-down-camera person that the real engine does not produce.
    "Pelvis": [1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0],
    "L_Hip": [
        0.0, 0.0, 1.0,
        0.0, 1.0, 0.0,
        -1.0, 0.0, 0.0,
    ],  # a 90-degree rotation about Y in the engine's output frame
}
_CANNED_BIND_OFFSETS = {
    # SMPL frame, cm — the real template's values, rounded, as the real
    # worker reports them (the adapter converts them into the domain frame)
    "Pelvis": [-0.18, 93.851, 2.822],
    "L_Hip": [6.952, -9.141, -0.682],
    "R_Hip": [-6.767, -9.052, -0.432],
    "Spine_1": [-0.253, 10.896, -2.67],
    "L_Knee": [3.428, -37.52, -0.45],
    "R_Knee": [-3.829, -38.257, -0.885],
    "Spine_2": [0.549, 13.518, 0.109],
    "L_Ankle": [-1.36, -39.796, -4.369],
    "R_Ankle": [1.577, -39.841, -4.231],
    "Spine_3": [0.146, 5.292, 2.542],
    "L_Foot": [2.636, -5.579, 11.929],
    "R_Foot": [-2.537, -4.814, 12.335],
    "Neck": [-0.278, 21.387, -4.286],
    "L_Collar": [7.884, 12.175, -3.409],
    "R_Collar": [-8.176, 11.883, -3.862],
    "Head": [0.515, 6.497, 5.135],
    "L_Shoulder": [9.098, 3.047, -0.887],
    "R_Shoulder": [-9.601, 3.255, -0.914],
    "L_Elbow": [25.961, -1.277, -2.746],
    "R_Elbow": [-25.374, -1.333, -2.14],
    "L_Wrist": [24.923, 0.899, -0.117],
    "R_Wrist": [-25.53, 0.777, -0.556],
    "L_Hand": [8.404, -0.816, -1.495],
    "R_Hand": [-8.462, -0.612, -1.032],
}
_TEMPLATE_HIP_CM = 93.85


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _died_marker() -> str:
    return os.environ.get("FAKE_DIED_MARKER", "")


def _died_marker_exists() -> bool:
    marker = _died_marker()
    return bool(marker) and os.path.isfile(marker)


def _mark_died() -> None:
    marker = _died_marker()
    if marker:
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("died")


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
        "bind_offsets_cm": _CANNED_BIND_OFFSETS,
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
        response = {
            "status": "ok",
            "frame_index": request.get("frame_index"),
            "hip_height_cm": _TEMPLATE_HIP_CM,
            "per_frame_hip_height_m": 0.87,
            "rotations": _CANNED_ROTATIONS,
        }
        if _MODE == "projected":
            # The engine's own projection onto the captured frame, as JSON
            # lists (the wire is JSON; the adapter normalizes to tuples).
            response["projected_joints"] = {
                "Pelvis": [640.0, 360.0],
                "L_Hip": [604.5, 360.25],
            }
        _emit(response)


if __name__ == "__main__":
    main()
