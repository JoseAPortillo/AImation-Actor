"""Smoke test: the scaffolded package and its layers import cleanly."""

import aimation_actor
import aimation_actor.adapters
import aimation_actor.core
import aimation_actor.ports


def test_layers_import() -> None:
    assert aimation_actor is not None
