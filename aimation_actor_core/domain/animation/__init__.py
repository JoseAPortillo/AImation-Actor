"""Public API of the animation domain package (SDD §2.2).

Re-exports the animation domain contracts so consumers import from
``aimation_actor_core.domain.animation`` rather than deep submodules.
"""

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.hierarchy import HierarchyError
from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.neutral_motion import (
    ContactFeed,
    FootContact,
    KeyPose,
    NeutralMeta,
    NeutralMotion,
    TrackingInfo,
)
from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton

__all__ = [
    "Bone",
    "ContactFeed",
    "FootContact",
    "Frame",
    "HierarchyError",
    "Keypoint",
    "Keypoints2D",
    "KeyPose",
    "NeutralMeta",
    "NeutralMotion",
    "Pose",
    "Skeleton",
    "TrackingInfo",
    "Transform3D",
]
