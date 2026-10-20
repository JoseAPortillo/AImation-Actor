"""Tests for the M6 T1 seams: the ``InbetweeningPort`` contract and the Model
Factory (FR-GEN-02).

The inbetweening port consumes a whole ``TimelineState`` — the human keys are
its hard constraints — and returns a filled one. The factory is where the GUI
picks an engine by name; the layering suite already guarantees that swapping
engines never touches ``core/``, so here we pin the contract's shape, the
drop-in rule (LSP), and the typed unknown-engine failure.
"""

from __future__ import annotations

import pytest

from aimation_actor.adapters.ai.model_factory import (
    UnknownEngineError,
    capture_engine,
    inbetweening_engine,
)
from aimation_actor.core.models import TimelineState
from aimation_actor.core.production_skeleton import production_skeleton
from aimation_actor.ports.ai_port import AIPort, InbetweeningPort
from tests.fake_hmr2_worker import _CANNED_BIND_OFFSETS as _FAKE_BIND_OFFSETS


def _timeline() -> TimelineState:
    """A two-key timeline; the fake engine never has to interpret the pose."""
    skeleton = production_skeleton(_FAKE_BIND_OFFSETS)
    return TimelineState(skeleton=skeleton, frame_end=20)


# -- the port contract ---------------------------------------------------------- #


def test_inbetweening_is_its_own_port_not_a_capture_method() -> None:
    # FR-GEN consumes a whole timeline, not one frame (ports/ai_port.py:8-12):
    # forcing it onto AIPort would make extraction-only engines lie about
    # methods they must not have (Interface Segregation).
    assert not issubclass(InbetweeningPort, AIPort)


def test_the_port_cannot_be_instantiated_without_the_method() -> None:
    class Lazy(InbetweeningPort):
        pass

    with pytest.raises(TypeError):
        Lazy()


def test_a_fake_engine_can_implement_the_contract() -> None:
    class FakeInbetweening(InbetweeningPort):
        def inbetween(self, timeline: TimelineState) -> TimelineState:
            return timeline

    engine = FakeInbetweening()
    assert engine.inbetween(_timeline()).fps == 24.0


# -- the factory ----------------------------------------------------------------- #


def test_the_factory_builds_the_default_capture_engine() -> None:
    engine = capture_engine()
    assert isinstance(engine, AIPort)
    assert isinstance(engine, type(capture_engine("hmr2")))


def test_the_factory_builds_the_registered_inbetweening_engine() -> None:
    engine = inbetweening_engine("condmdi")
    assert isinstance(engine, InbetweeningPort)
    # CondMDI is the MVP default (FR-GEN-02): the no-name call picks it.
    assert inbetweening_engine() is not None


def test_an_unknown_engine_name_is_a_typed_failure() -> None:
    with pytest.raises(UnknownEngineError):
        inbetweening_engine("lafan1")
    with pytest.raises(UnknownEngineError):
        capture_engine("condmdi")
