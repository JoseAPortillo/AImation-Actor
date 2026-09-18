"""Generate motion endpoint (Phase C — Generative MVP).

This endpoint takes golden poses + slider parameters and returns
a NeutralMotion document with generated frames between the poses.

Currently uses the InbetweenGenerationNode as a placeholder for the
real generative model (sMDM/MDM-style). Will be replaced when a real
model is integrated.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aimation_actor_core.domain.animation.inbetween import (
    InbetweenParams,
    enrich_motion,
)
from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import (
    NeutralMeta,
    NeutralMotion,
)
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

router = APIRouter(tags=["generate"])


class GoldenPose(BaseModel):
    """A single golden pose from the wizard."""

    frame: int
    label: str
    confidence: float | None = None


class GenerateMotionRequest(BaseModel):
    """Request to generate motion between golden poses."""

    goldenPoses: list[GoldenPose] = Field(..., alias="goldenPoses")
    naturalidad: float = Field(50.0, ge=0, le=100, description="Naturalidad slider (0-100)")
    respetarPoses: float = Field(70.0, ge=0, le=100, description="Respetar mis poses slider (0-100)")


def _build_motion_from_poses(golden_poses: list[GoldenPose]) -> NeutralMotion:
    """Build a NeutralMotion from golden poses with actual transforms.

    Creates frames at the golden pose positions with transforms based on
    the default neutral skeleton rest positions.

    Source fps is capped at 8.0 — below the minimum target_fps (12) that
    ``_map_sliders_to_params`` can produce — so ``_resample`` always
    upsamples.  The cap also ensures a reasonable output frame count
    regardless of how close the golden poses are.
    """
    skeleton = DEFAULT_NEUTRAL_SKELETON
    _SOURCE_FPS_CAP = 8.0

    frames: list[Frame] = []
    for pose in golden_poses:
        # Create transforms from the skeleton's rest positions
        transforms: dict[str, Transform3D] = {}
        for bone_name, bone in skeleton.bones.items():
            transforms[bone_name] = Transform3D(
                translation=bone.rest_position,
                rotation=bone.rest_rotation,
            )

        frame = Frame(
            frame=pose.frame,
            time=(pose.frame - 1) / 24.0,
            pose=Pose(transforms=transforms),
            confidence=pose.confidence,
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
async def generate_motion(request: GenerateMotionRequest) -> dict[str, Any]:
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

    # Build motion from golden poses
    motion = _build_motion_from_poses(request.goldenPoses)

    # Map sliders to inbetween params
    params = _map_sliders_to_params(request.naturalidad, request.respetarPoses)

    # Run the enrichment chain (placeholder for real generative model)
    enriched_motion = enrich_motion(motion, params)

    # Convert to dict for JSON response
    return enriched_motion.model_dump()
