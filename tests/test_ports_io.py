"""Tests for the FBX I/O port contract."""

import pytest

from aimation_actor.ports.io_port import IOPort


def test_io_port_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        IOPort()  # type: ignore[abstract]


def test_io_port_declares_load_and_save() -> None:
    assert {"load", "save"} <= IOPort.__abstractmethods__
