"""Abstract contract for exchanging 3D animation files (.fbx).

Implemented by ``adapters/io/fbx_adapter.py``: writes with the in-repo binary
FBX writer and reads through a Blender subprocess. This module is part of the
interface layer: it may import the domain (``core``) but must not import any
adapter or third-party library.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from aimation_actor.core.models import TimelineState


class IOPort(ABC):
    """Reads and writes the tool's animation interchange format (binary FBX).

    The concrete adapter owns all format details; callers only ever see
    ``TimelineState``.
    """

    @abstractmethod
    def load(self, path: Path) -> TimelineState:
        """Read an ``.fbx`` animation into the domain timeline.

        Used for the Phase-3 "Refined FBX": only frames that carry keyframes
        become :class:`~aimation_actor.core.models.Keyframe` objects, and the
        source interpolation types (Bézier/Linear/...) are ignored.
        """

    @abstractmethod
    def save(self, state: TimelineState, path: Path) -> None:
        """Write ``state`` to a binary FBX (version 2014/2016) at ``path``.

        Keys are written only at the marked frames, with stepped (constant)
        tangents, and the production hierarchy rooted at ``Main``.
        """
