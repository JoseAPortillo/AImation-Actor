"""Abstract contract for AI engines (GVHMR pose extraction, CondMDI inbetweening).

Implementations live in ``adapters/ai/``. This module is part of the interface
layer: it may import the domain (``core``) but must not import any adapter or
third-party library, so an engine can be swapped without touching ``core/``
(NFR-01).

The MVP contract is **single-frame pose extraction** (FR-CAP-05). Generative
inbetweening (``FR-GEN``) is a different capability with a different lifecycle —
it consumes a whole timeline, not one frame — so it gets its own port when it
lands. An engine that only extracts is then never forced to implement a method it
does not have.
"""

from abc import ABC, abstractmethod

from aimation_actor.core.models import FrameImage, WorldPose

__all__ = ["AIPort"]


class AIPort(ABC):
    """Extracts a 3D pose from a single frame.

    The concrete adapter owns every engine detail — checkpoints, device, dtype,
    preprocessing — while callers only ever see :class:`WorldPose`. Extraction is
    **blocking and single-frame** by contract: the caller owns the isolation (the
    capture UI runs it on a worker thread, NFR-02) and never batches.
    """

    @abstractmethod
    def extract_pose(self, image: FrameImage, *, frame_index: int) -> WorldPose:
        """Infer the world-space pose depicted in ``image``.

        ``frame_index`` is the frame the image came from; it is carried through
        so the result can be attributed back to its frame, and it never changes
        the inference. A failure is raised to the caller, which reports it as
        non-fatal and writes no key (FR-CAP-07).
        """
