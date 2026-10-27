"""The Model Factory (FR-GEN-02): the one place engines are named and built.

The GUI asks by name; the concrete adapters never leak past this module, so
swapping an engine is a registry edit plus an adapter — never a ``core/`` edit
(the layering suite makes that rule mechanical, ``tests/test_layering.py``).
Every constructor here builds lazily and cheaply: no weights probing, no
spawning, no CUDA — engines pay for what they use on first call, exactly like
``Hmr2Adapter`` does at its first ``extract_pose``.
"""

from __future__ import annotations

from collections.abc import Callable

from aimation_actor.adapters.ai.condmdi_adapter import CondMDIAdapter
from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter
from aimation_actor.ports.ai_port import AIPort, InbetweeningPort

__all__ = ["UnknownEngineError", "capture_engine", "inbetweening_engine"]

_CAPTURE_ENGINES: dict[str, Callable[[], AIPort]] = {
    "hmr2": Hmr2Adapter,
}

_INBETWEENING_ENGINES: dict[str, Callable[[], InbetweeningPort]] = {
    "condmdi": CondMDIAdapter,
}


class UnknownEngineError(Exception):
    """A requested engine name is not registered with the factory."""


def capture_engine(name: str = "hmr2") -> AIPort:
    """Build the pose-extraction engine ``name`` (FR-CAP)."""
    try:
        constructor = _CAPTURE_ENGINES[name]
    except KeyError as error:
        raise UnknownEngineError(
            f"unknown capture engine {name!r}; registered: {sorted(_CAPTURE_ENGINES)}"
        ) from error
    return constructor()


def inbetweening_engine(name: str = "condmdi") -> InbetweeningPort:
    """Build the inbetweening engine ``name`` (FR-GEN-02: MVP = CondMDI)."""
    try:
        constructor = _INBETWEENING_ENGINES[name]
    except KeyError as error:
        raise UnknownEngineError(
            f"unknown inbetweening engine {name!r}; "
            f"registered: {sorted(_INBETWEENING_ENGINES)}"
        ) from error
    return constructor()
