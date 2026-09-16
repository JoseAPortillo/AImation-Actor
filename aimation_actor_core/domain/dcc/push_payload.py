"""Push payload schema for DCC session delivery (Phase B).

Defines the typed payloads that flow between Core and DCC plugins via the
session push/pull mechanism. Phase B uses ``golden_poses`` (Core→Addon) and
``edited_poses`` (Addon→Core).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion


class PushPayload(BaseModel):
    """A typed payload queued for delivery to a DCC session.

    Phase B delivers ``golden_poses`` (Core→Addon) and receives
    ``edited_poses`` (Addon→Core). Future phases may add new kinds.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["golden_poses", "edited_poses"] = Field(
        ...,
        description="Payload kind: golden_poses (Core→Addon) or edited_poses (Addon→Core)",
    )
    motion: NeutralMotion = Field(
        ...,
        description="The full NeutralMotion document with golden pose data",
    )
    source_frame_range: tuple[int, int] | None = Field(
        default=None,
        description="Optional frame range (start, end) for partial delivery",
    )
    request_id: str = Field(
        default="",
        description="Optional request ID for correlation",
    )
