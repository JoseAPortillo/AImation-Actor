"""Job operators: run video-to-motion and stop it (bpy glue).

Threading model (spec §7.2): network + polling run on a daemon worker
thread; bpy data is NEVER touched there. The worker writes plain-Python
state (:class:`_JobState`); a ``bpy.app.timers`` callback on the main thread
mirrors that state into the UI properties and, on success, calls
``ensure_armature`` + ``bake_motion`` (main thread = bpy-safe). ESC-style
cancellation is exposed via the Stop operator and honoured by the poll loop.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import bpy

from blender_addon.core import config
from blender_addon.core.client import (
    CoreClient,
    build_video_to_motion_graph,
)
from blender_addon.core.http import CoreHttpError, UrllibTransport
from blender_addon.core.session import SessionManager

_TIMER_INTERVAL_S = 0.5


@dataclass
class _JobState:
    """Worker<->main-thread handoff (plain Python, safe to share).

    Attributes:
        phase: idle | running | complete | error | cancelled.
        message: Human-readable status text for the panel.
        job_id: The most recent job id (for the UI + stop).
        cancel_requested: Set by the Stop operator; polled by the worker.
        payload: Final ``{"motion": ..., "elapsed_s": ...}`` on success.
    """

    phase: str = "idle"
    message: str = "Idle"
    job_id: str = ""
    cancel_requested: bool = False
    payload: dict[str, object] | None = None


_STATE = _JobState()
_LOCK = threading.Lock()


class AIMATION_OT_run_video(bpy.types.Operator):
    """Submit the selected video to the Core, poll, then build+bake."""

    bl_idname = "aimation.run_video"
    bl_label = "Run Video to Motion"
    bl_description = "Convert the selected video to motion and bake it onto a shadow armature"

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Validate inputs, spawn the worker thread and start the UI timer."""
        props = context.scene.aimation_actor
        if _active_job():
            self.report({"WARNING"}, "A job is already running")
            return {"CANCELLED"}

        video_path = props.video_path.strip()
        if not video_path:
            self.report({"ERROR"}, "Select a video file first")
            return {"CANCELLED"}
        base_url = _validated_base_url(props.core_url.strip())
        if base_url is None:
            self.report({"ERROR"}, "Core URL must be http(s) on a loopback host")
            return {"CANCELLED"}

        token = config.session_token_from_env()
        client = CoreClient(UrllibTransport(base_url), base_url=base_url, token=token)
        session = SessionManager(client)
        session_name = props.session_name.strip() or config.DEFAULT_SESSION_NAME

        with _LOCK:
            _STATE.phase = "running"
            _STATE.message = "Submitting job..."
            _STATE.job_id = ""
            _STATE.cancel_requested = False
            _STATE.payload = None

        worker = threading.Thread(
            target=_run_job_worker,
            args=(client, session, video_path, session_name, base_url),
            name="aimation-job",
            daemon=True,
        )
        worker.start()
        if not bpy.app.timers.is_registered(_sync_timer):
            bpy.app.timers.register(_sync_timer, first_interval=_TIMER_INTERVAL_S)
        return {"FINISHED"}


class AIMATION_OT_stop_job(bpy.types.Operator):
    """Request cancellation of the running job (ESC-equivalent)."""

    bl_idname = "aimation.stop_job"
    bl_label = "Stop Job"
    bl_description = "Cancel the running job and clean up the session"

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Set the cancel flag; the worker stops polling and cancels server-side."""
        del context
        with _LOCK:
            was_running = _STATE.phase == "running"
            _STATE.cancel_requested = True
        if not was_running:
            self.report({"INFO"}, "No job is running")
            return {"CANCELLED"}
        self.report({"INFO"}, "Cancelling job...")
        return {"FINISHED"}


def _validated_base_url(raw: str) -> str | None:
    """Validate the user-provided Core URL against the loopback policy."""
    try:
        return config.validate_base_url(raw or config.CORE_URL)
    except ValueError:
        return None


def _run_job_worker(
    client: CoreClient,
    session: SessionManager,
    video_path: str,
    session_name: str,
    base_url: str,
) -> None:
    """Daemon thread: register session, submit, poll, hand the motion to main.

    The video path is reduced to its basename because the Core resolves
    ``video_path`` relative to its own media root (frame_extractor allowlist);
    the selected file must live under that root.
    """
    relative_video = os.path.basename(video_path.strip()) or video_path.strip()
    try:
        _set_message("Registering session...")
        session.register(name=session_name)
        session.start_heartbeat()
        started = time.monotonic()

        _set_message("Submitting video-to-motion job...")
        job_id = client.submit_video_to_motion(relative_video)
        _set_job_id(job_id)
        result = _poll_to_result(client, job_id, started)
        if result is None:
            return  # cancelled path already reported
        motion = _extract_motion(result)

        if motion is None:
            # Today's Core completes the direct v2m job as a mediated stub
            # echo; escalate to the full pipeline graph — the live producer
            # of NeutralMotion documents.
            _set_message("RUNNING: escalating to full pipeline graph...")
            graph_client = CoreClient(
                UrllibTransport(base_url, timeout_s=config.GRAPH_REQUEST_TIMEOUT_S),
                base_url=base_url,
                token=client.token,
            )
            graph_id = graph_client.submit_graph(build_video_to_motion_graph(relative_video))
            _set_job_id(graph_id)
            result = _poll_to_result(client, graph_id, started)
            if result is None:
                return
            motion = _extract_motion(result)

        if motion is None:
            _set_done_phase("error", "ERROR: job succeeded but no NeutralMotion was produced")
            return

        elapsed = time.monotonic() - started
        _set_complete(job_id, motion, elapsed)
    except CoreHttpError as exc:
        _set_done_phase("error", f"ERROR: {exc}")
    except Exception as exc:  # noqa: BLE001 - report any failure, never crash the thread
        _set_done_phase("error", f"ERROR: {exc}")
    finally:
        try:
            session.deregister()
        except Exception:  # noqa: BLE001 - cleanup must never mask the result
            pass


def _poll_to_result(
    client: CoreClient, job_id: str, started: float
) -> dict[str, object] | None:
    """Poll a job to terminal honouring cancellation; None when cancelled."""
    deadline = time.monotonic() + config.POLL_TIMEOUT_S
    while True:
        if _cancel_flag():
            try:
                client.cancel_job(job_id)
            except CoreHttpError:
                pass
            _set_done_phase("cancelled", "Cancelled by user")
            return None
        snapshot = client.get_job(job_id)
        status = snapshot.get("status")
        if status == "succeeded":
            return client.get_job_result(job_id)
        if status in ("failed", "cancelled"):
            _set_done_phase("error", f"ERROR: job {status}: {snapshot.get('error') or 'no detail'}")
            return None
        if time.monotonic() >= deadline:
            _set_done_phase("error", f"ERROR: job {job_id} timed out")
            return None
        _set_message(f"RUNNING: {job_id} ({time.monotonic() - started:.0f}s)")
        time.sleep(config.POLL_INTERVAL_S)


def _extract_motion(result: dict[str, object]) -> dict[str, object] | None:
    """Pull the NeutralMotion from a job result payload (either result shape).

    - graph/execute: ``result.outputs.v2m.motion``
    - direct v2m:    stub echo without a motion (returns None).
    """
    inner = result.get("result")
    if not isinstance(inner, dict):
        return None
    outputs = inner.get("outputs")
    if not isinstance(outputs, dict):
        return None
    v2m = outputs.get("v2m")
    if not isinstance(v2m, dict):
        return None
    motion = v2m.get("motion")
    if isinstance(motion, dict):
        return motion
    return None


def _sync_timer() -> float | None:
    """Main-thread tick: mirror worker state into UI props; bake on success.

    Returns None to stop the timer (terminal states), else the next interval.
    """
    with _LOCK:
        phase = _STATE.phase
        message = _STATE.message
        job_id = _STATE.job_id
        payload = _STATE.payload
    props = _props()
    if props is None:
        return _TIMER_INTERVAL_S

    if phase == "complete":
        try:
            _finish_on_main_thread(props, payload)
        except Exception as exc:  # noqa: BLE001 - surface bake failures in the panel
            props.status = f"ERROR: bake failed: {exc}"
        _reset_state()
        return None
    if phase in ("error", "cancelled"):
        props.status = message
        props.job_id = job_id
        _reset_state()
        return None

    props.status = message
    props.job_id = job_id
    return _TIMER_INTERVAL_S


def _finish_on_main_thread(props: object, payload: dict[str, object] | None) -> None:
    """Build the armature and bake the motion (bpy imports kept main-thread)."""
    if payload is None:
        raise RuntimeError("completed job has no payload")
    motion = payload.get("motion")
    if not isinstance(motion, dict):
        raise RuntimeError("completed job payload has no motion document")

    from blender_addon.core import motion_prep as _motion_prep
    from blender_addon.rig import armature as _armature
    from blender_addon.rig import baker as _baker

    prepared = _motion_prep.keyframe_payload(motion)
    frames = prepared.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("motion document has no keyframed frames")
    frame_start = int(frames[0]["frame"])
    frame_end = int(frames[-1]["frame"])

    armature = _armature.ensure_armature(skeleton=motion.get("skeleton"))
    action = _baker.bake_motion(
        armature,
        motion,
        prepared,
        frame_start=frame_start,
        frame_end=frame_end,
    )
    props.status = f"SUCCESS: baked '{action.name}' on {armature.name}"  # type: ignore[attr-defined]


def cleanup_jobs() -> None:
    """Stop any active job/timer and release the in-memory token (unload)."""
    with _LOCK:
        _STATE.cancel_requested = True
        _STATE.phase = "idle"
        _STATE.message = "Idle"
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)


def _props() -> bpy.types.PropertyGroup | None:
    """Return the scene property group, or None outside a scene context."""
    scene = bpy.context.scene
    if scene is None:
        return None
    return scene.aimation_actor


def _reset_state() -> None:
    """Return the shared state to idle (also untracks the client/session)."""
    with _LOCK:
        _STATE.phase = "idle"
        _STATE.message = "Idle"
        _STATE.job_id = ""
        _STATE.cancel_requested = False
        _STATE.payload = None


def _active_job() -> bool:
    """True while a job is running or waiting to be baked on the main thread."""
    with _LOCK:
        return _STATE.phase in ("running", "complete")


def _cancel_flag() -> bool:
    """Return the user's cancel request (atomic read, no locking needed)."""
    with _LOCK:
        return _STATE.cancel_requested


def _set_message(text: str) -> None:
    """Set the running-phase status message."""
    with _LOCK:
        _STATE.phase = "running"
        _STATE.message = text


def _set_job_id(job_id: str) -> None:
    """Record the current job id for the UI."""
    with _LOCK:
        _STATE.job_id = job_id


def _set_complete(job_id: str, motion: dict[str, object], elapsed: float) -> None:
    """Mark the job complete and hand the motion to the main thread."""
    with _LOCK:
        _STATE.phase = "complete"
        _STATE.job_id = job_id
        _STATE.message = f"Completed in {elapsed:.1f}s"
        _STATE.payload = {"motion": motion, "elapsed_s": elapsed}
        _STATE.cancel_requested = False


def _set_done_phase(phase: str, message: str) -> None:
    """Mark the job terminal with a final message (error/cancelled)."""
    with _LOCK:
        _STATE.phase = phase
        _STATE.message = message
        _STATE.cancel_requested = False


# ---------------------------------------------------------------------------
# Phase B: Round-trip Blender operators
# ---------------------------------------------------------------------------


@dataclass
class _RoundTripState:
    """State for the round-trip polling modal operator.

    Attributes:
        active: Whether the modal is running.
        session_id: The registered session ID.
        last_poll: Timestamp of the last poll.
    """

    active: bool = False
    session_id: str = ""
    last_poll: float = 0.0


_ROUND_TRIP_STATE = _RoundTripState()
_ROUND_TRIP_LOCK = threading.Lock()
_ROUND_TRIP_POLL_INTERVAL_S = 2.0


class AIM_OT_poll_pending(bpy.types.Operator):
    """Modal operator: polls Core for pending payloads (golden poses)."""

    bl_idname = "aim.poll_pending"
    bl_label = "Poll for Pending Poses"
    bl_description = "Poll the Core for pending golden poses to receive"

    _timer = None

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        """Handle timer events and poll for pending payloads."""
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        with _ROUND_TRIP_LOCK:
            if not _ROUND_TRIP_STATE.active:
                self._cleanup(context)
                return {"CANCELLED"}

        props = context.scene.aimation_actor
        base_url = _validated_base_url(props.core_url.strip())
        if base_url is None:
            with _ROUND_TRIP_LOCK:
                _ROUND_TRIP_STATE.active = False
            self._cleanup(context)
            self.report({"ERROR"}, "Core URL invalid")
            return {"CANCELLED"}

        token = config.session_token_from_env()
        client = CoreClient(UrllibTransport(base_url), base_url=base_url, token=token)

        with _ROUND_TRIP_LOCK:
            session_id = _ROUND_TRIP_STATE.session_id

        if not session_id:
            self._cleanup(context)
            return {"CANCELLED"}

        payload = client.poll_pending(session_id)
        if payload is not None:
            self._receive_poses(context, payload)

        return {"PASS_THROUGH"}

    def _receive_poses(self, context: bpy.types.Context, payload: dict[str, object]) -> None:
        """Create armature from received golden poses."""
        kind = payload.get("kind")
        if kind != "golden_poses":
            return

        motion = payload.get("motion")
        if not isinstance(motion, dict):
            return

        # Create armature from NeutralMotion skeleton
        try:
            from blender_addon.rig.armature import ensure_armature
            ensure_armature(motion)
            self.report({"INFO"}, "Golden poses received — armature created")
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to create armature: {exc}")

    def _cleanup(self, context: bpy.types.Context) -> None:
        """Unregister the timer."""
        if self._timer is not None:
            bpy.app.timers.unregister(self._timer)
            self._timer = None

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        """Start the modal polling."""
        props = context.scene.aimation_actor
        base_url = _validated_base_url(props.core_url.strip())
        if base_url is None:
            self.report({"ERROR"}, "Core URL must be http(s) on a loopback host")
            return {"CANCELLED"}

        # Get session ID from properties or register a new one
        session_id = props.session_id
        if not session_id:
            token = config.session_token_from_env()
            client = CoreClient(UrllibTransport(base_url), base_url=base_url, token=token)
            session_id = client.register_session()
            props.session_id = session_id

        with _ROUND_TRIP_LOCK:
            _ROUND_TRIP_STATE.active = True
            _ROUND_TRIP_STATE.session_id = session_id
            _ROUND_TRIP_STATE.last_poll = 0.0

        self._timer = bpy.app.timers.register(
            self.modal, first_interval=_ROUND_TRIP_POLL_INTERVAL_S
        )
        return {"FINISHED"}


class AIM_OT_stop_polling(bpy.types.Operator):
    """Stop the round-trip polling modal."""

    bl_idname = "aim.stop_polling"
    bl_label = "Stop Polling"
    bl_description = "Stop polling for pending poses"

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Stop the modal by setting active=False."""
        with _ROUND_TRIP_LOCK:
            _ROUND_TRIP_STATE.active = False
        self.report({"INFO"}, "Polling stopped")
        return {"FINISHED"}


class AIM_OT_submit_edited(bpy.types.Operator):
    """Capture current pose transforms and send back to Core."""

    bl_idname = "aim.submit_edited"
    bl_label = "Submit Edited Poses"
    bl_description = "Capture pose-mode edits and send them back to the Core"

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Read bone transforms from the active armature and submit."""
        props = context.scene.aimation_actor
        base_url = _validated_base_url(props.core_url.strip())
        if base_url is None:
            self.report({"ERROR"}, "Core URL must be http(s) on a loopback host")
            return {"CANCELLED"}

        session_id = props.session_id
        if not session_id:
            self.report({"ERROR"}, "No active session — poll for poses first")
            return {"CANCELLED"}

        # Get the active armature
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature in pose mode")
            return {"CANCELLED"}

        # Capture bone transforms
        try:
            motion = self._capture_transforms(obj)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to capture transforms: {exc}")
            return {"CANCELLED"}

        # Submit to Core
        token = config.session_token_from_env()
        client = CoreClient(UrllibTransport(base_url), base_url=base_url, token=token)

        success = client.submit_edited_poses(session_id, motion)
        if success:
            self.report({"INFO"}, "Edited poses submitted to Core")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to submit edited poses")
            return {"CANCELLED"}

    def _capture_transforms(self, obj: bpy.types.Object) -> dict[str, object]:
        """Capture bone transforms from an armature in pose mode.

        Returns a NeutralMotion-compatible dict with frame data.
        """
        import json
        from mathutils import Matrix

        armature = obj.data
        pose_bones = obj.pose.bones

        # Build skeleton hierarchy
        bones_data = []
        for bone in armature.bones:
            parent_name = bone.parent.name if bone.parent else ""
            bones_data.append({
                "name": bone.name,
                "parent": parent_name,
                "rest_matrix": [list(row) for row in bone.matrix_local],
            })

        # Capture current pose transforms
        transforms = {}
        for pb in pose_bones:
            # matrix_basis is the pose transform relative to rest pose
            mat = pb.matrix_basis
            loc, rot, scale = mat.decompose()
            transforms[pb.name] = {
                "translation": [loc.x, loc.y, loc.z],
                "rotation": [rot.w, rot.x, rot.y, rot.z],
                "scale": [scale.x, scale.y, scale.z],
            }

        # Build NeutralMotion-compatible structure
        motion = {
            "meta": {
                "version": "0.2",
                "fps": 24.0,
                "units": "cm",
                "up_axis": "Y",
                "source_type": "blender_edited",
            },
            "skeleton": {
                "bones": bones_data,
            },
            "frames": [
                {
                    "frame": 1,
                    "time": 0.0,
                    "pose": {
                        "transforms": transforms,
                    },
                    "confidence": 1.0,
                }
            ],
            "keyposes": [
                {"frame": 1, "weight": 1.0}
            ],
        }

        return motion


# Operator classes to register
ROUND_TRIP_OPERATORS = [
    AIM_OT_poll_pending,
    AIM_OT_stop_polling,
    AIM_OT_submit_edited,
]