"""COCO → neutral bone mapping table (plan §14.2).

Bridges the estimator's COCO 17 keypoint labels to the §14.2 neutral skeleton.
The mapping is a read-only 13-row table of ``(coco_label, neutral_bone)``
distal-end landmarks. Every key is an EXACT estimator ``KEYPOINT_LABELS``
string (``left_shoulder``, NOT ``l_shoulder``) — otherwise the converter
silently falls back to the bone's rest offset (design D2).

Neutral values use the canonical ``Left…/Right…`` names (ADR-001).

Coverage beyond the 13 rows:
- Derived: ``Hips`` = midpoint of the two hip landmarks.
- Rest-only (no 1:1 COCO landmark, kept at the neutral offset): Spine, Chest,
  Neck, LeftHand, RightHand, LeftToeBase, RightToeBase.
- Pose-only labels (eyes, ears) and unknown labels map to no bone and are
  ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

#: Frozen COCO → neutral bone mapping (distal-end), canonical names (ADR-001).
COCO_TO_NEUTRAL: Mapping[str, str] = MappingProxyType(
    {
        "nose": "Head",
        "left_shoulder": "LeftShoulder",
        "right_shoulder": "RightShoulder",
        "left_elbow": "LeftArm",
        "right_elbow": "RightArm",
        "left_wrist": "LeftForeArm",
        "right_wrist": "RightForeArm",
        "left_hip": "LeftUpLeg",
        "right_hip": "RightUpLeg",
        "left_knee": "LeftLeg",
        "right_knee": "RightLeg",
        "left_ankle": "LeftFoot",
        "right_ankle": "RightFoot",
    }
)