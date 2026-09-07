"""NeutralMotion — the versioned, immutable animation contract.

This is the bridge format shared by the AI Core, the Tauri app, and the DCC
plugins (plan §9.5). Per SDD §5.3, it is an **immutable contract**: any change
requires a versioned migration strategy and an ADR (Sub_Agents.md §4.1).

The structure mirrors plan §10 tags: ``meta``, ``skeleton``, ``frames``,
``contacts``, ``keyposes``, ``tracking``.

Versioning (ADR-001): ``meta.version`` is ``"0.3"`` since the canonical
``Left…/Right…`` bone-name rename. Legacy ``"0.2"`` documents (abbreviated
``L…/R…`` names) are migrated deterministically on read via
:func:`migrate_neutral_motion`; any other version is rejected with
:class:`UnsupportedNeutralVersionError`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.domain.animation.entities import Frame
from aimation_actor_core.domain.animation.skeleton import Skeleton
from aimation_actor_core.domain.animation.skeleton_presets import LEGACY_BONE_RENAME_MAP


class NeutralMeta(BaseModel):
    """Metadata about a :class:`NeutralMotion` document (plan §10 ``meta``)."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default="0.3")
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


class UnsupportedNeutralVersionError(ValueError):
    """Raised when a document's ``meta.version`` is not ``0.2`` or ``0.3``.

    Attributes:
        version: The offending version value (or ``"<missing>"``).
    """

    def __init__(self, version: str) -> None:
        super().__init__(
            f"unsupported NeutralMotion version {version!r} (supported: '0.2', '0.3')"
        )
        self.version = version


def migrate_neutral_motion(raw: Any) -> NeutralMotion:  # noqa: ANN401
    """Coerce job-store input into a canonical version-``0.3`` NeutralMotion (ADR-001).

    This is the read-boundary coercion for NeutralMotion-consuming nodes: it
    accepts ``0.2`` documents (legacy ``L…/R…`` bone names) and deterministically
    renames the skeleton keys, ``Bone.name`` fields, parent references, and frame
    pose transforms to canonical ``Left…/Right…`` form via
    :data:`LEGACY_BONE_RENAME_MAP`, bumps ``meta.version`` to ``0.3``, and
    validates invariants. ``0.3`` input passes through unchanged (a
    ``NeutralMotion`` instance is returned by identity). Any other version —
    including a missing one on a serialized document — is rejected with
    :class:`UnsupportedNeutralVersionError`; stored documents are never silently
    corrupted.

    Args:
        raw: A :class:`NeutralMotion`, or a serialized document dict from the
            job-store path.

    Returns:
        A version-``0.3`` canonical-name :class:`NeutralMotion`.

    Raises:
        UnsupportedNeutralVersionError: If ``meta.version`` is not ``"0.2"`` or
            ``"0.3"`` (a missing version on a serialized document is rejected).
        pydantic.ValidationError: If ``raw`` is not a valid document shape.
    """
    if isinstance(raw, NeutralMotion):
        motion = raw
    else:
        # The version field is the authority (ADR-001): a serialized document
        # that omits it must not silently fall back to the 0.3 default.
        declared = raw.get("meta") if isinstance(raw, dict) else None
        version = declared.get("version") if isinstance(declared, dict) else None
        if version is None:
            raise UnsupportedNeutralVersionError("<missing>")
        motion = NeutralMotion.model_validate(raw)

    if motion.meta.version == "0.3":
        return motion
    if motion.meta.version != "0.2":
        raise UnsupportedNeutralVersionError(motion.meta.version)

    rename = LEGACY_BONE_RENAME_MAP

    renamed_bones: dict[str, Any] = {}
    for key, bone in motion.skeleton.bones.items():
        parent = rename.get(bone.parent, bone.parent) if bone.parent is not None else None
        renamed_bones[rename.get(key, key)] = bone.model_copy(
            update={"name": rename.get(bone.name, bone.name), "parent": parent}
        )

    renamed_frames = []
    for frame in motion.frames:
        renamed_transforms = {
            rename.get(key, key): transform
            for key, transform in frame.pose.transforms.items()
        }
        renamed_frames.append(
            frame.model_copy(
                update={"pose": frame.pose.model_copy(update={"transforms": renamed_transforms})}
            )
        )

    migrated = motion.model_copy(
        update={
            "meta": motion.meta.model_copy(update={"version": "0.3"}),
            "skeleton": Skeleton(bones=renamed_bones),
            "frames": renamed_frames,
        }
    )
    migrated.validate_invariants()
    return migrated