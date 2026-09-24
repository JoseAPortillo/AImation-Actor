"""3D lifting contract (spec REQ-2).

``LiftingBackend`` is the framework-free boundary implemented in
``infrastructure.ai_models.lifters`` and injected through ``app.state``
(design D1). The domain owns the port so the API layer can depend on it
without importing infrastructure (SDD §2.3); it mirrors
``SingleFramePoseDetector`` in :mod:`aimation_actor_core.domain.animation.pose_detection`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D


@runtime_checkable
class LiftingBackend(Protocol):
    """Protocol for 3D lifting backends (spec REQ-2)."""

    def lift(self, keypoints_2d: list[Keypoints2D]) -> list[Keypoints3D]:
        """Lift 2D keypoints into normalized 3D keypoints.

        Args:
            keypoints_2d: Input frames, one :class:`Keypoints2D` per frame.

        Returns:
            One :class:`Keypoints3D` per input frame, minus confidence-filtered
            joints applied by the caller; empty input yields [].
        """
        ...
