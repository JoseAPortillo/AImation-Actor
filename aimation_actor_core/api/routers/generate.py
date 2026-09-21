"""Generate motion endpoint (Phase C — Generative MVP).

This endpoint takes golden poses + slider parameters and returns
a NeutralMotion document with generated frames between the poses.

Currently uses the InbetweenGenerationNode as a placeholder for the
real generative model (sMDM/MDM-style). Will be replaced when a real
model is integrated.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from aimation_actor_core.api.deps import get_motion_backend
from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.inbetween import (
    InbetweenParams,
    enrich_motion,
)
from aimation_actor_core.domain.animation.mapping import COCO_TO_NEUTRAL
from aimation_actor_core.domain.animation.motion_backend import (
    MotionBackend,
    MotionBackendUnavailable,
)
from aimation_actor_core.domain.animation.neutral_motion import (
    NeutralMeta,
    NeutralMotion,
)
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

router = APIRouter(tags=["generate"])

#: Person-height heuristic for converting normalized keypoints to cm.
_DEFAULT_PERSON_HEIGHT_CM = 172.0


class DetectedKeypoint(BaseModel):
    """A single detected keypoint from ONNX pose detection."""

    label: str
    x: float
    y: float
    confidence: float


class GoldenPose(BaseModel):
    """A single golden pose from the wizard."""

    frame: int
    label: str
    time: float = 0.0
    confidence: float | None = None
    detection: list[DetectedKeypoint] | None = None


class GenerateMotionRequest(BaseModel):
    """Request to generate motion between golden poses."""

    goldenPoses: list[GoldenPose] = Field(..., alias="goldenPoses")
    naturalidad: float = Field(50.0, ge=0, le=100, description="Naturalidad slider (0-100)")
    respetarPoses: float = Field(
        70.0, ge=0, le=100, description="Respetar mis poses slider (0-100)"
    )


_PREVIEW_CONNECTIONS = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
)


def _build_preview_metadata(golden_poses: list[GoldenPose]) -> dict[str, Any]:
    """Describe captured COCO topology without changing animation data."""
    labels = {
        kp.label
        for pose in golden_poses
        for kp in (pose.detection or [])
    }
    visible = {
        COCO_TO_NEUTRAL[label]
        for label in labels
        if label in COCO_TO_NEUTRAL
    }
    if {"left_hip", "right_hip"}.issubset(labels):
        visible.add("Hips")

    pairs = [
        {"parent": COCO_TO_NEUTRAL[parent], "child": COCO_TO_NEUTRAL[child]}
        for parent, child in _PREVIEW_CONNECTIONS
        if parent in labels and child in labels
    ]
    return {
        "joint_names": sorted(visible),
        "bone_pairs": pairs,
        "authored_frames": [pose.frame for pose in golden_poses],
    }


def _keypoints_to_bone_positions(
    keypoints: list[DetectedKeypoint],
    height: float,
) -> dict[str, tuple[float, float, float]]:
    """Convert detected COCO keypoints to local bone offsets.

    Step 1: Place detected keypoints at absolute positions (scaled by height, y-flipped).
    Step 2: Walk hierarchy to fill undetected bones using parent_abs + rest_position.
    Step 3: Convert ALL absolute positions to local offsets for the frame transforms.

    Returns dict of bone_name -> (local_x, local_y, local_z) ready for frame.pose.
    """
    kps = {kp.label: kp for kp in keypoints}

    # Step 1: Place detected keypoints at absolute positions
    detected_abs: dict[str, tuple[float, float, float]] = {}
    for coco_label, bone_name in COCO_TO_NEUTRAL.items():
        kp = kps.get(coco_label)
        if kp is not None:
            detected_abs[bone_name] = (
                kp.x * height,
                (1.0 - kp.y) * height,  # flip y-axis
                0.0,
            )

    # Derived Hips = midpoint of both hips
    left_hip = kps.get("left_hip")
    right_hip = kps.get("right_hip")
    if left_hip is not None and right_hip is not None:
        detected_abs["Hips"] = (
            (left_hip.x + right_hip.x) / 2.0 * height,
            ((1.0 - left_hip.y) + (1.0 - right_hip.y)) / 2.0 * height,
            0.0,
        )

    # Step 2: Walk ALL bones in parent-first order to compute absolute positions
    abs_positions: dict[str, tuple[float, float, float]] = {}
    for name, bone in DEFAULT_NEUTRAL_SKELETON.bones.items():
        if name in detected_abs:
            # Detected bone: use keypoint position
            abs_positions[name] = detected_abs[name]
        else:
            # Undetected bone: parent_abs + rest_position
            parent = bone.parent
            rx, ry, rz = bone.rest_position
            if parent is not None and parent in abs_positions:
                px, py, pz = abs_positions[parent]
                abs_positions[name] = (px + rx, py + ry, pz + rz)
            else:
                abs_positions[name] = (rx, ry, rz)

    # Step 3: Convert absolute positions to local offsets
    # Formula: local = abs - parentAbs - rest_position
    local_offsets: dict[str, tuple[float, float, float]] = {}
    for name, bone in DEFAULT_NEUTRAL_SKELETON.bones.items():
        ax, ay, az = abs_positions[name]
        rx, ry, rz = bone.rest_position
        parent = bone.parent
        if parent is not None and parent in abs_positions:
            px, py, pz = abs_positions[parent]
            local_offsets[name] = (ax - px - rx, ay - py - ry, az - pz - rz)
        else:
            local_offsets[name] = (ax - rx, ay - ry, az - rz)

    return local_offsets


def _build_motion_from_poses(golden_poses: list[GoldenPose]) -> NeutralMotion:
    """Build a NeutralMotion from golden poses with detected keypoints.

    Converts detected COCO keypoints to bone positions using COCO_TO_NEUTRAL,
    then interpolates between consecutive golden poses. Undetected bones
    keep their rest offset from parent.

    The bone_positions from _keypoints_to_bone_positions are stored as local
    offsets (already pre-subtracted for the frontend's absolutePositions).
    We interpolate these local offsets directly.
    """
    skeleton = DEFAULT_NEUTRAL_SKELETON
    _SOURCE_FPS_CAP = 8.0
    n_poses = len(golden_poses)

    # Convert each golden pose's keypoints to local bone offsets
    bone_positions: list[dict[str, tuple[float, float, float]]] = []
    for pose in golden_poses:
        if pose.detection:
            positions = _keypoints_to_bone_positions(
                pose.detection, _DEFAULT_PERSON_HEIGHT_CM
            )
        else:
            # No detection: use rest positions (all zeros for local offsets)
            positions = {name: (0.0, 0.0, 0.0) for name in skeleton.bones}
        bone_positions.append(positions)

    frames: list[Frame] = []
    for i in range(n_poses):
        # Interpolation factor: 0 at first pose, 1 at last pose
        t = i / max(n_poses - 1, 1)

        transforms: dict[str, Transform3D] = {}
        for bone_name, bone in skeleton.bones.items():
            # Get local offset for this bone at this pose
            pos_a = bone_positions[0].get(bone_name, (0.0, 0.0, 0.0))
            pos_b = bone_positions[-1].get(bone_name, (0.0, 0.0, 0.0))

            # Interpolate local offsets between first and last pose
            tx = pos_a[0] * (1 - t) + pos_b[0] * t
            ty = pos_a[1] * (1 - t) + pos_b[1] * t
            tz = pos_a[2] * (1 - t) + pos_b[2] * t

            transforms[bone_name] = Transform3D(
                translation=(tx, ty, tz),
                rotation=bone.rest_rotation,
            )

        frame = Frame(
            frame=golden_poses[i].frame,
            time=golden_poses[i].time,
            pose=Pose(transforms=transforms),
            confidence=golden_poses[i].confidence,
        )
        frames.append(frame)

    # Derive fps from actual time span, then cap it below the minimum
    # target_fps (12) so _resample always triggers.
    if len(frames) >= 2:
        actual_span = frames[-1].time - frames[0].time
        actual_fps = (len(frames) - 1) / actual_span if actual_span > 0 else 1.0
        source_fps = min(actual_fps, _SOURCE_FPS_CAP)
    else:
        source_fps = _SOURCE_FPS_CAP

    meta = NeutralMeta(
        duration_frames=max((f.frame for f in frames), default=0),
        fps=source_fps,
        source_type="wizard-generate",
    )

    return NeutralMotion(
        meta=meta,
        skeleton=skeleton,
        frames=frames,
    )


def _map_sliders_to_params(naturalidad: float, respetarPoses: float) -> InbetweenParams:
    """Map slider values (0-100) to InbetweenParams.

    - Naturalidad: higher = more easing and smoothing
    - RespetarPoses: higher = more interpolation (cubic) and higher fps
    """
    # Map naturalidad (0-100) to easing
    if naturalidad < 33:
        easing = "none"
    elif naturalidad < 66:
        easing = "ease-in-out"
    else:
        easing = "ease-out"

    # Map naturalidad to tangent_smoothing (0-1)
    tangent_smoothing = naturalidad / 100.0

    # Map respetarPoses to interpolation method
    interpolation_method = "cubic" if respetarPoses > 50 else "linear"

    # Map respetarPoses to target_fps (12-48)
    target_fps = 12.0 + (respetarPoses / 100.0) * 36.0

    return InbetweenParams(
        interpolation_method=interpolation_method,
        target_fps=target_fps,
        easing=easing,
        euler_filter=True,
        tangent_smoothing=tangent_smoothing,
    )


@router.post(
    "/generate-motion",
    status_code=status.HTTP_200_OK,
    summary="Generate motion between golden poses",
)
async def generate_motion(
    request: GenerateMotionRequest,
    backend: MotionBackend | None = Depends(get_motion_backend),
) -> dict[str, Any]:
    """Generate motion between golden poses using slider parameters.

    This is a placeholder implementation using the InbetweenGenerationNode.
    When a real generative model (sMDM/MDM-style) is integrated, this endpoint
    will be updated to use it instead.
    """
    if not request.goldenPoses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one golden pose is required",
        )

    # The model adapter is strictly opt-in. Any unavailable, malformed, timed-
    # out, or fidelity-rejected external result falls back to the procedural
    # path. AutoKeyframe and MIB both use the same authored-fidelity gate.
    fallback_reason: str | None = None
    if backend is not None:
        conditioning = {
            "duration_frames": 219,
            "fps": 24.0,
            "keyframes": [
                {"frame": pose.frame, "joints": {
                    kp.label: [kp.x, kp.y, 0.0] for kp in (pose.detection or [])
                }} for pose in request.goldenPoses
            ],
        }
        try:
            model_motion = await asyncio.to_thread(backend.generate, conditioning)
            params = _map_sliders_to_params(request.naturalidad, request.respetarPoses)
            response = enrich_motion(model_motion, params).model_dump()
            response["preview"] = _build_preview_metadata(request.goldenPoses)
            response["backend"] = getattr(backend, "name", "autokeyframe")
            return response
        except MotionBackendUnavailable as exc:
            fallback_reason = str(exc) if str(exc) == "authored keyframe fidelity check failed" \
                else "optional motion backend unavailable"
        except (ValueError, TypeError, KeyError, IndexError):
            fallback_reason = "optional motion backend unavailable"

    # Build motion from golden poses (uses detected keypoints if available)
    motion = _build_motion_from_poses(request.goldenPoses)

    # Map sliders to inbetween params
    params = _map_sliders_to_params(request.naturalidad, request.respetarPoses)

    # Run the enrichment chain (placeholder for real generative model)
    enriched_motion = enrich_motion(motion, params)

    # Convert to dict for JSON response
    response = enriched_motion.model_dump()
    response["preview"] = _build_preview_metadata(request.goldenPoses)
    response["backend"] = "procedural"
    if fallback_reason is not None:
        response["fallback_reason"] = fallback_reason
    return response
