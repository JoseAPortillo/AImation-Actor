"""Public API of the animation domain package (SDD §2.2).

Re-exports the animation domain contracts so consumers import from
``aimation_actor_core.domain.animation`` rather than deep submodules.
"""

from aimation_actor_core.domain.animation.cleanup import (
    DEFAULT_BETA,
    DEFAULT_HEIGHT_THRESHOLD,
    DEFAULT_HYSTERESIS_FRAMES,
    DEFAULT_MIN_CUTOFF,
    DEFAULT_VELOCITY_THRESHOLD,
    CleanupParams,
    cleanup_motion,
)
from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.hierarchy import HierarchyError
from aimation_actor_core.domain.animation.inbetween import InbetweenParams, enrich_motion
from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.keypoints3d import Keypoint3D, Keypoints3D
from aimation_actor_core.domain.animation.mapping import COCO_TO_NEUTRAL
from aimation_actor_core.domain.animation.neutral_motion import (
    ContactFeed,
    FootContact,
    KeyPose,
    NeutralMeta,
    NeutralMotion,
    TrackingInfo,
    UnsupportedNeutralVersionError,
    migrate_neutral_motion,
)
from aimation_actor_core.domain.animation.quat import (
    quat_dot,
    quat_multiply,
    quat_negate,
    quat_normalize,
    slerp,
)
from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON

__all__ = [
    "Bone",
    "COCO_TO_NEUTRAL",
    "CleanupParams",
    "ContactFeed",
    "DEFAULT_BETA",
    "DEFAULT_HEIGHT_THRESHOLD",
    "DEFAULT_HYSTERESIS_FRAMES",
    "DEFAULT_MIN_CUTOFF",
    "DEFAULT_NEUTRAL_SKELETON",
    "DEFAULT_VELOCITY_THRESHOLD",
    "FootContact",
    "Frame",
    "HierarchyError",
    "InbetweenParams",
    "Keypoint",
    "Keypoint3D",
    "Keypoints2D",
    "Keypoints3D",
    "KeyPose",
    "NeutralMeta",
    "NeutralMotion",
    "Pose",
    "Skeleton",
    "TrackingInfo",
    "Transform3D",
    "UnsupportedNeutralVersionError",
    "cleanup_motion",
    "enrich_motion",
    "migrate_neutral_motion",
    "quat_dot",
    "quat_multiply",
    "quat_negate",
    "quat_normalize",
    "slerp",
]
