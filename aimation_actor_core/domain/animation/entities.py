"""Core geometric entities for the animation domain.

Belongs to the ``domain/animation`` layer (SDD §2.2). Pure Python + Pydantic
validation only — no heavy external dependencies (SDD §2.3 golden rule).

Tensors from :mod:`infrastructure` are NEVER exposed here; ML code converts
raw tensors into these domain entities at the infrastructure boundary
(Sub_Agents.md §4.2 / ml-engineer).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.shared.types import Vec3, Vec4


class Transform3D(BaseModel):
    """Local transform of a single joint/bone at a point in time.

    Attributes:
        translation: Local translation ``(x, y, z)`` in scene units.
        rotation: Local rotation as a unit quaternion ``(w, x, y, z)``.
        scale: Local scale ``(x, y, z)``; defaults to identity ``(1, 1, 1)``.
    """

    model_config = ConfigDict(frozen=True)

    translation: Vec3 = Field(default_factory=lambda: (0.0, 0.0, 0.0))
    rotation: Vec4 = Field(default=(1.0, 0.0, 0.0, 0.0))
    scale: Vec3 = Field(default_factory=lambda: (1.0, 1.0, 1.0))


class Pose(BaseModel):
    """A full body pose at a single instant: local transforms keyed by joint name.

    The key set corresponds to the neutral skeleton bone names (plan §14.2).
    """

    model_config = ConfigDict(frozen=True)

    transforms: dict[str, Transform3D] = Field(default_factory=dict)


class Frame(BaseModel):
    """One animation frame.

    Attributes:
        frame: 1-based frame number within the timeline.
        time: Time in seconds (``frame / fps``).
        pose: The :class:`Pose` for this frame.
        confidence: Optional per-frame tracking confidence in ``[0.0, 1.0]``.
    """

    model_config = ConfigDict(frozen=True)

    frame: int = Field(ge=1)
    time: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Time in seconds. Derived as frame/fps by producers; default 0.0 "
            "when not yet resolved at the document level."
        ),
    )
    pose: Pose = Field(default_factory=Pose)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
