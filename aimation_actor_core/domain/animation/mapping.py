"""COCO → neutral bone mapping table (plan §14.2).

Bridges the estimator's COCO 17 keypoint labels to the §14.2 neutral skeleton.
The mapping is a read-only 13-row table of ``(coco_label, neutral_bone)``
distal-end landmarks. Every key is an EXACT estimator ``KEYPOINT_LABELS``
string (``left_shoulder``, NOT ``l_shoulder``) — otherwise the converter
silently falls back to the bone's rest offset (design D2).

Coverage beyond the 13 rows:
- Derived: ``Hips`` = midpoint of the two hip landmarks.
- Rest-only (no 1:1 COCO landmark, kept at the neutral offset): Spine, Chest,
  Neck, LHand, RHand, LToeBase, RToeBase.
- Pose-only labels (eyes, ears) and unknown labels map to no bone and are
  ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

#: Frozen COCO → neutral bone mapping (distal-end).
COCO_TO_NEUTRAL: Mapping[str, str] = MappingProxyType(
    {
        "nose": "Head",
        "left_shoulder": "LShoulder",
        "right_shoulder": "RShoulder",
        "left_elbow": "LArm",
        "right_elbow": "RArm",
        "left_wrist": "LForeArm",
        "right_wrist": "RForeArm",
        "left_hip": "LUpLeg",
        "right_hip": "RUpLeg",
        "left_knee": "LLeg",
        "right_knee": "RLeg",
        "left_ankle": "LFoot",
        "right_ankle": "RFoot",
    }
)
