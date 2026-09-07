"""Retarget map model (SDD §14, task 2.6).

The validated, frozen preset document consumed by the retarget node: a
per-bone ``mapping`` of source (neutral) bone names to :class:`RetargetEntry`
configurations, plus the document-level toggle booleans. Plan §14.3 shorthand
``{LeftArm: arm_l_rig}`` promotes plain strings to entries whose target name
is the string (design D5). Unknown keys reject (``extra="forbid"``) and the
models are immutable; skeletons are validated explicitly via
:meth:`RetargetMap.validate_against` because the node validates against the
neutral skeleton while rig tests also hand a target rig (design D9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from aimation_actor_core.domain.animation.skeleton import Skeleton
from aimation_actor_core.shared.types import Vec3, Vec4


class RetargetEntry(BaseModel):
    """Per-bone retarget configuration (frozen, ``extra="forbid"``).

    Attributes:
        target_name: Bone name on the target rig the source bone drives.
        rotation_offset: LOCAL-space rotation offset ``(w, x, y, z)`` applied
            to the bone's motion (post-multiplied), identity by default.
        axis_correction: Optional global reorientation ``(w, x, y, z)``
            (pre-multiplied) transferring the bone from source to target axis
            conventions; ``None`` means no correction.
        scale: Optional per-bone scale factor ``(x, y, z)``, identity default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_name: str
    rotation_offset: Vec4 = (1.0, 0.0, 0.0, 0.0)
    axis_correction: Vec4 | None = None
    scale: Vec3 = (1.0, 1.0, 1.0)

    @model_validator(mode="before")
    @classmethod
    def _promote_shorthand(cls, data: object) -> object:
        """Plan §14.3 shorthand: a plain string means ``{"target_name": it}``."""
        if isinstance(data, str):
            return {"target_name": data}
        return data


class RetargetMap(BaseModel):
    """Validated retarget preset document (frozen, ``extra="forbid"``).

    Attributes:
        mapping: Per-source-bone entries; keys are neutral (source) bone names.
        use_root_translation: Whether the root (Hips) translation participates
            in height-ratio scaling.
        foot_ik: Enable the translation-only foot-ground pass on Hips Y.
        scale_source_height: Scale root* ratios by ``target_root_to_ground_cm``.
        preserve_keyframes: Keep original frame cadence (no resampling below).
        target_root_to_ground_cm: Target root→ground height for the ratio;
            ``None`` keeps height scaling inert.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping: dict[str, RetargetEntry]
    use_root_translation: bool = True
    foot_ik: bool = False
    scale_source_height: bool = False
    preserve_keyframes: bool = False
    target_root_to_ground_cm: float | None = None

    def validate_against(self, source: Skeleton, target: Skeleton | None = None) -> None:
        """Ensure every mapped bone exists in the skeletons.

        Raises:
            ValueError: A mapping key is absent from ``source``, or -- when a
                ``target`` rig is provided -- an entry's ``target_name`` is
                absent from it.
        """
        for source_name, entry in self.mapping.items():
            if source_name not in source.bones:
                raise ValueError(
                    f"source bone '{source_name}' is not in the source skeleton"
                )
            if target is not None and entry.target_name not in target.bones:
                raise ValueError(
                    f"target bone '{entry.target_name}' is not in the target skeleton"
                )