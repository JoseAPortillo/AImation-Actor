"""Retargeting domain package (SDD §14, task 2.11).

Pure-stdlib retarget math: the validated :class:`RetargetMap` document, the
:func:`retarget_motion` pipeline, and the rotation rig helpers. Consumers
import from this package rather than the submodules.
"""

from aimation_actor_core.domain.retargeting.map import RetargetEntry, RetargetMap
from aimation_actor_core.domain.retargeting.retarget import retarget_motion
from aimation_actor_core.domain.retargeting.rotation import (
    apply_rotation,
    axis_correction_quat,
)

__all__ = [
    "RetargetEntry",
    "RetargetMap",
    "apply_rotation",
    "axis_correction_quat",
    "retarget_motion",
]