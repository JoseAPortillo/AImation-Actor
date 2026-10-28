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
    Z-up). ``root_translation`` is an optional absolute root-position estimate
    in the same frame; the controller subtracts the first captured value before
    production mapping. ``rotations`` maps a joint name to that joint's local
    rotation; a joint absent from the mapping keeps its bind rotation.
    ``projected`` is the optional projection the engine computed for its own
    joints onto the captured frame, joint name to full-frame ``(x, y)``
    pixels — video-overlay data, never animation data. Engines without one
    leave it ``None`` and their poses simply stay unprojected.
    """

    translation: Vector3
    rotations: Mapping[str, Quaternion]
    #: Absolute/root-position estimate before the session origin is applied.
    #: It is optional because older engines may only report hip height.
    root_translation: Vector3 = Vector3()
    projected: Mapping[str, tuple[float, float]] | None = None


@dataclass(frozen=True, slots=True)
class FrameImage:
    """One decoded RGB frame, as an AI engine consumes it.

    ``rgb`` is a flat, row-major ``bytes`` buffer of ``width * height * 3``
    RGB888 samples, starting at the top-left pixel. A plain buffer — rather than
    a decoder handle — is what keeps ``ports/`` free of any third-party type: the
    video adapter converts its toolkit's frame into this, and the engine never
    has to know which toolkit produced it.
    """

    width: int
    height: int
    rgb: bytes

    def __post_init__(self) -> None:
        expected = self.width * self.height * 3
        if len(self.rgb) != expected:
            raise ValueError(
                f"rgb buffer holds {len(self.rgb)} bytes, expected {expected} "
                f"for {self.width}x{self.height}"
            )


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """A frame handed over for extraction, paired with the frame it belongs to.

    The pixels alone are not enough to key a pose: the timeline follows the
    backend's *position* events, which arrive far less often than frames, so
    after a playback the playhead can lag the pane by one to three frames.
    Pairing the image with the frame index the source can prove makes that
    mismatch impossible to write unnoticed — the key lands on the frame the
    animator was looking at, and the playhead is moved there.

    ``frame_index`` is ``None`` when the source cannot establish it (a backend
    reporting no timestamps, or an unknown frame rate); the caller then falls
    back to its own playhead rather than refusing the capture.
    """

    image: FrameImage
    frame_index: int | None = None


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
