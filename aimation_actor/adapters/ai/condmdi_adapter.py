"""CondMDI adapter: generative inbetweening engine.

MVP engine for FR-GEN-02 (plan §6): the keyframe-conditioned motion diffusion
model trained on HumanML3D (Cohan et al., SIGGRAPH 2024; MIT code, checkpoint
user-supplied). It runs **out of process** — its stack pins Python 3.7-era
dependencies — over the same line-JSON worker protocol the HMR2.0 capture
engine uses (``hmr2_worker.py``). The worker, the protocol and the timeline
conversion arrive with M6 T3/T4; until then the factory can name this engine
but a run asks for the missing work, loudly.
"""

from __future__ import annotations

from aimation_actor.core.models import TimelineState
from aimation_actor.ports.ai_port import InbetweeningPort

__all__ = ["CondMDIAdapter"]


class CondMDIAdapter(InbetweeningPort):
    """Fills a ``TimelineState``'s gaps with CondMDI-generated motion."""

    def inbetween(self, timeline: TimelineState) -> TimelineState:
        raise NotImplementedError(
            "CondMDI inbetweening lands with M6 T3/T4 (worker + adapter); "
            "the factory registration ahead of the engine is intentional"
        )
