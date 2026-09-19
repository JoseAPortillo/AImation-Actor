"""Contracts for optional motion-generation backends."""

from __future__ import annotations

from typing import Any, Protocol

from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion


class MotionBackendUnavailable(RuntimeError):
    """The selected optional backend cannot be used in this environment."""


class MotionBackend(Protocol):
    """Generate a neutral motion from JSON-safe wizard conditioning."""

    def generate(self, conditioning: dict[str, Any]) -> NeutralMotion:
        """Return a validated neutral motion or raise a backend error."""
