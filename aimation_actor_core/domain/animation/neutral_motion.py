"""NeutralMotion — the versioned, immutable animation contract.

This is the bridge format shared by the AI Core, the Tauri app, and the DCC
plugins (plan §9.5). Per SDD §5.3, it is an **immutable contract**: any change
requires a versioned migration strategy and an ADR (Sub_Agents.md §4.1).

The structure mirrors plan §10 tags: ``meta``, ``skeleton``, ``frames``,
``contacts``, ``keyposes``, ``tracking``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.domain.animation.entities import Frame
from aimation_actor_core.domain.animation.skeleton import Skeleton


class NeutralMeta(BaseModel):
    """Metadata about a :class:`NeutralMotion` document (plan §10 ``meta``)."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default="0.2")
    fps: float = Field(default=24.0, gt=0.0)
    units: str = Field(default="cm")
    up_axis: str = Field(default="Y", pattern=r"^[XYZ]$")
    source_type: str = Field(default="unknown")
    duration_frames: int = Field(default=0, ge=0)
    style: str = Field(default="realistic_v1")
    model_version: str = Field(default="")
    graph_hash: str = Field(default="", description="Hash of the generating graph (plan §9.5).")


class FootContact(BaseModel):
    """A foot-ground contact sample (plan §10 ``contacts``)."""

    model_config = ConfigDict(frozen=True)

    frame: int = Field(ge=1)
    contact: bool


class KeyPose(BaseModel):
    """A user-preserved key pose (plan §10 ``keyposes``)."""

    model_config = ConfigDict(frozen=True)

    frame: int = Field(ge=1)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class ContactFeed(BaseModel):
    """Named contact track, e.g. ``left_foot`` / ``right_foot``."""

    model_config = ConfigDict(frozen=True)

    samples: list[FootContact] = Field(default_factory=list)


class TrackingInfo(BaseModel):
    """Per-frame tracking confidence (plan §10 ``tracking``)."""

    model_config = ConfigDict(frozen=True)

    confidence_per_frame: list[float] = Field(default_factory=list)


class NeutralMotion(BaseModel):
    """The complete neutral animation document.

    Immutable (frozen). Composition:

    - :attr:`meta`: document metadata (fps, units, style, traceability).
    - :attr:`skeleton`: the neutral :class:`Skeleton` hierarchy.
    - :attr:`frames`: ordered per-frame poses (plan §10 ``frames``).
    - :attr:`contacts`: per-track foot contact info.
    - :attr:`keyposes`: preserved artistic key poses.
    - :attr:`tracking`: per-frame confidence.
    """

    model_config = ConfigDict(frozen=True)

    meta: NeutralMeta = Field(default_factory=NeutralMeta)
    skeleton: Skeleton = Field(default_factory=Skeleton)
    frames: list[Frame] = Field(default_factory=list)
    contacts: dict[str, ContactFeed] = Field(default_factory=dict)
    keyposes: list[KeyPose] = Field(default_factory=list)
    tracking: TrackingInfo = Field(default_factory=TrackingInfo)

    def validate_invariants(self) -> None:
        """Validate cross-field invariants of the document.

        Raises:
            ValueError: If frames are out of order, frame indices exceed the
                declared duration, or the skeleton hierarchy is invalid.
        """
        from itertools import pairwise

        self.skeleton.validate_hierarchy()

        frames = [f.frame for f in self.frames]
        if any(a >= b for a, b in pairwise(frames)):
            raise ValueError("frames must be strictly increasing by frame number")

        if self.meta.duration_frames and frames and max(frames) > self.meta.duration_frames:
            raise ValueError("a frame exceeds the declared duration_frames")
