"""The preview clock's frame arithmetic (S1).

Playback must be independent of the animator's timeline, so the only thing
worth pinning is pure arithmetic — no ``bpy``, no wall clock. Whole-second
elapsed times keep the expectations exact in binary floating point.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon" / "aimation_transpose"


def _load(name: str) -> ModuleType:
    path = _ADDON / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"aimation_transpose_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


clock = _load("clock")


def test_frame_at_holds_the_starting_frame_before_any_time_passes() -> None:
    assert clock.frame_at(10.0, 10.0, 4, 24.0, 0, 20) == 4


def test_frame_at_advances_one_frame_per_tick() -> None:
    # Half a second at 24 fps is exactly 12 frames.
    assert clock.frame_at(10.5, 10.0, 0, 24.0, 0, 20) == 12


def test_frame_at_advances_slower_at_a_lower_rate() -> None:
    assert clock.frame_at(10.0 + 2.0, 10.0, 0, 12.0, 0, 40) == 24


def test_frame_at_truncates_partial_ticks() -> None:
    assert clock.frame_at(11.9, 10.0, 0, 1.0, 0, 20) == 1


def test_frame_at_wraps_inside_the_range() -> None:
    # 21 steps past the start of a 21-frame range returns to where it began.
    assert clock.frame_at(31.0, 10.0, 0, 1.0, 0, 20) == 0


def test_frame_at_wraps_a_range_that_does_not_start_at_zero() -> None:
    assert clock.frame_at(21.0, 10.0, 5, 1.0, 5, 15) == 5


def test_frame_at_starts_from_the_current_frame_not_the_range_start() -> None:
    assert clock.frame_at(13.0, 10.0, 7, 1.0, 0, 20) == 10


def test_frame_at_treats_a_negative_elapsed_as_zero() -> None:
    assert clock.frame_at(9.0, 10.0, 4, 24.0, 0, 20) == 4


@pytest.mark.parametrize("fps", [0.0, -24.0])
def test_frame_at_keeps_the_starting_frame_without_a_rate(fps: float) -> None:
    assert clock.frame_at(11.0, 10.0, 4, fps, 0, 20) == 4


def test_frame_at_returns_the_first_frame_of_an_empty_range() -> None:
    assert clock.frame_at(11.0, 10.0, 9, 24.0, 5, 4) == 5


def test_frame_at_holds_a_single_frame_capture() -> None:
    assert clock.frame_at(13.0, 10.0, 2, 24.0, 2, 2) == 2
