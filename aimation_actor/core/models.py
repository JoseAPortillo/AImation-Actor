"""Domain entities for AImation Actor.

Pure Python: this module must import nothing outside the standard library, and
nothing from `ports/` or `adapters/`.

Conventions (see `AGENTS.md` and `docs/Plan_AImation_Actor_EN.md`):

- Global motion lives on the ``Main`` root joint, as a translation.
- The ``Pelvis`` carries only its height (translation ``z``); its local ``x``/``y``
  stay at zero.
- Every other joint carries rotation only, as a quaternion in ``(w, x, y, z)``
  order.
- Keyframes are sparse and stepped: they exist only at the exact frames the
  animator marked, and the gaps between them hold no keys.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vector3:
    """A 3D vector / translation, in centimeters (the FBX default unit)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True, slots=True)
class Quaternion:
    """A rotation as a unit quaternion, in ``(w, x, y, z)`` order."""

    w: float
    x: float
    y: float
    z: float

    @classmethod
    def identity(cls) -> "Quaternion":
        """The no-rotation quaternion ``(1, 0, 0, 0)``."""
        return cls(1.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class JointData:
    """One joint of the production skeleton.

    ``name``/``parent`` define the hierarchy; a ``None`` parent marks the root
    joint (always ``Main``). ``rest_translation`` is the joint's local bind
    offset from its parent.
    """

    name: str
    parent: str | None
    rest_translation: Vector3 = Vector3()


@dataclass(frozen=True, slots=True)
class Skeleton:
    """The joint hierarchy of a rig, ordered root-first (topological order)."""

    joints: tuple[JointData, ...]

    def names(self) -> tuple[str, ...]:
        """The joint names, in hierarchy order."""
        return tuple(joint.name for joint in self.joints)

    def root(self) -> JointData:
        """The root joint (the one with no parent); always ``Main``."""
        for joint in self.joints:
            if joint.parent is None:
                return joint
        raise ValueError("skeleton has no root joint (no parent-less joint)")


@dataclass(frozen=True, slots=True)
class JointPose:
    """A single joint's local transform within one keyframe."""

    rotation: Quaternion
    translation: Vector3 = Vector3()


@dataclass(frozen=True, slots=True)
class Keyframe:
    """A sparse, stepped pose at an exact frame index.

    ``pose`` maps joint name to that joint's local transform for this frame.
    """

    frame: int
    pose: Mapping[str, JointPose]


@dataclass(frozen=True, slots=True)
class WorldPose:
    """A raw, world-space pose as an AI backend reports it, before production mapping.

    ``translation`` is the actor's hip position in world space (centimetres,
    Z-up): its ``z`` is the ground-to-hip height, and it is the only component
    consumed by ``build_production_pose``. The horizontal components are the
    scene displacement the backend recovers, but they are deliberately **not**
    exported — world placement belongs to the animator. ``rotations`` maps a
    joint name to that joint's local rotation; a joint absent from the mapping
    keeps its bind rotation.
    """

    translation: Vector3
    rotations: Mapping[str, Quaternion]


@dataclass(frozen=True, slots=True)
class TimelineState:
    """The full animation state the UI and core operate on."""

    skeleton: Skeleton
    keyframes: tuple[Keyframe, ...] = ()
    fps: float = 24.0
    frame_start: int = 0
    frame_end: int = 0

    def frames(self) -> tuple[int, ...]:
        """The frame indices that actually carry a keyframe."""
        return tuple(keyframe.frame for keyframe in self.keyframes)
