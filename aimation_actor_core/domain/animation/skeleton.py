"""Neutral skeleton hierarchy for the animation domain.

Implements the internal neutral skeleton contract (plan §14.2): a fixed
reference hierarchy that AI output, retargeting presets, and DCC plugins all
share. Bone transforms are LOCAL to each bone's parent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.shared.types import Vec3, Vec4


class Bone(BaseModel):
    """A single bone/joint in the neutral skeleton.

    Attributes:
        name: Unique bone identifier, e.g. ``"LeftArm"`` (plan §14.2).
        parent: Name of the parent bone, or ``None`` for the root.
        rest_position: Rest (bind) position relative to the parent.
        rest_rotation: Rest rotation as a unit quaternion ``(w, x, y, z)``.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    parent: str | None = None
    rest_position: Vec3 = Field(default_factory=lambda: (0.0, 0.0, 0.0))
    rest_rotation: Vec4 = Field(default=(1.0, 0.0, 0.0, 0.0))


class Skeleton(BaseModel):
    """An ordered collection of :class:`Bone` forming a hierarchy.

    Validation guarantees a single root, no duplicate names, and that every
    ``parent`` reference resolves to a bone in the collection (single tree).
    """

    model_config = ConfigDict(frozen=True)

    bones: dict[str, Bone] = Field(default_factory=dict)

    @property
    def root(self) -> str | None:
        """Name of the root bone, or ``None`` if the skeleton is empty."""
        for name, bone in self.bones.items():
            if bone.parent is None:
                return name
        return None

    def validate_hierarchy(self) -> None:
        """Validate that ``self.bones`` forms a single rooted tree.

        Raises:
            ValueError: If there is no unique root, a dangling parent
                reference, a self-loop, or a cycle.
        """
        from aimation_actor_core.domain.animation import hierarchy

        hierarchy.validate(self)
