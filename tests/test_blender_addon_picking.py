"""Ray-to-bone picking for the transposition mapping (S4).

Pure geometry: the modal operator converts the click into a ray and must get
back the bone whose segment lies closest to it. Everything here runs without
Blender — the add-on package imports ``bpy``, so the module is loaded by path.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import ModuleType

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon" / "aimation_transpose"


def _load(name: str) -> ModuleType:
    path = _ADDON / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"aimation_transpose_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


picking = _load("picking")

ORIGIN = (0.0, 0.0, 0.0)


def test_the_nearest_bone_segment_wins() -> None:
    # ``far`` sits slightly off the ray: with both segments exactly on it the
    # distances tie and "nearest" would be undefined, not a ranking.
    segments = [
        ("far", (10.0, 0.3, 0.0), (20.0, 0.3, 0.0)),
        ("near", (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
    ]
    hit = picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None and hit[0] == "near" and hit[1] == 0.0


def test_a_bone_off_the_ray_by_less_than_the_cap_is_second_choice() -> None:
    segments = [
        ("straight", (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ("sideways", (1.0, 0.4, 0.0), (2.0, 0.4, 0.0)),
    ]
    hit = picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None and hit[0] == "straight" and hit[1] == 0.0


def test_a_bone_farther_than_the_cap_is_a_miss() -> None:
    segments = [("far", (10.0, 50.0, 0.0), (20.0, 50.0, 0.0))]
    assert picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0) is None


def test_an_empty_bone_list_is_a_miss() -> None:
    assert picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), (), max_distance=5.0) is None


def test_a_bone_behind_the_ray_is_never_picked() -> None:
    segments = [("behind", (-3.0, 0.0, 0.0), (-1.0, 0.0, 0.0))]
    assert picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=50.0) is None


def test_a_zero_length_segment_is_picked_as_a_point() -> None:
    segments = [("dot", (3.0, 0.0, 0.0), (3.0, 0.0, 0.0))]
    hit = picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None and hit[0] == "dot" and hit[1] == 0.0


def test_the_closest_point_can_be_mid_segment() -> None:
    # A skew segment whose perpendicular foot lands strictly inside it: the
    # closest point is (5, 0, 0.5), half-way along, 0.5 off the ray.
    segments = [("bar", (4.0, 0.5, 0.5), (6.0, -0.5, 0.5))]
    hit = picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None
    assert hit[0] == "bar"
    assert math.isclose(hit[1], 0.5, abs_tol=1e-6)


def test_the_ray_is_measured_from_its_origin_not_the_world() -> None:
    segments = [("ahead", (5.0, 0.3, 0.0), (9.0, 0.3, 0.0))]
    hit = picking.pick_bone((4.0, 0.0, 0.0), (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None and hit[0] == "ahead"
    assert math.isclose(hit[1], 0.3, abs_tol=1e-6)


def test_a_degenerate_direction_picks_nothing() -> None:
    segments = [("bone", (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))]
    assert picking.pick_bone(ORIGIN, (0.0, 0.0, 0.0), segments, max_distance=5.0) is None


def test_ties_keep_the_first_bone() -> None:
    segments = [
        ("first", (1.0, 0.5, 0.0), (2.0, 0.5, 0.0)),
        ("second", (1.0, -0.5, 0.0), (2.0, -0.5, 0.0)),
    ]
    hit = picking.pick_bone(ORIGIN, (1.0, 0.0, 0.0), segments, max_distance=5.0)
    assert hit is not None and hit[0] == "first"
