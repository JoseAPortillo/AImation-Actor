"""Ray-to-bone picking for the mapping surface (S4).

Deliberately free of ``bpy`` (and of ``mathutils``): the repository's pytest
run loads this module by path and covers it without Blender. A click becomes a
ray in the caller (``bpy_extras.view3d_utils``); this module answers *which*
bone segment lies closest to that ray and how far off it was, so the operator
can accept generous clicks on thin bones and ignore stray ones.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["pick_bone", "ray_segment_distance"]

#: The ray is walked as a very long segment, far past any skeleton the
#: application writes (a whole rig is ~170 units); this keeps the closed-form
#: segment/segment solve well inside float precision.
_RAY_REACH = 1e6

_EPSILON = 1e-12

Point = tuple[float, float, float]
Segment = tuple[str, Point, Point]


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Point, f: float) -> Point:
    return (a[0] * f, a[1] * f, a[2] * f)


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Point) -> float:
    return _dot(a, a) ** 0.5


def ray_segment_distance(
    origin: Point, direction: Point, head: Point, tail: Point
) -> float:
    """The shortest distance between a ray and a closed segment.

    Solved as closest points between two segments (Ericson, *Real-Time Collision
    Detection*, ch. 5): the ray is the segment ``origin -> origin + direction *
    _RAY_REACH``, and the clamping of both parameters to ``[0, 1]`` handles the
    three degenerate cases for free — a click "behind" the camera clamps onto
    the ray's origin, and a zero-length bone collapses onto a point.
    """
    p0, q0 = origin, _add(origin, _scale(direction, _RAY_REACH))
    d1, d2 = _sub(q0, p0), _sub(tail, head)
    r = _sub(p0, head)
    a, e = _dot(d1, d1), _dot(d2, d2)
    if a < _EPSILON:
        # Degenerate ray (a zero direction must pick nothing, never everything).
        return float("inf")
    if e < _EPSILON:
        return ray_point_distance(origin, direction, head)
    f = _dot(d2, r)
    s, t = 0.0, 0.0
    c, b = _dot(d1, r), _dot(d1, d2)
    denom = a * e - b * b
    s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom >= _EPSILON else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t = 0.0
        s = min(max(-c / a, 0.0), 1.0)
    elif t > 1.0:
        t = 1.0
        s = min(max((b - c) / a, 0.0), 1.0)
    closest_ray = _add(p0, _scale(d1, s))
    closest_bone = _add(head, _scale(d2, t))
    if _dot(_sub(closest_bone, origin), direction) <= 0.0:
        # The bone's nearest point sits behind the ray origin: not a click,
        # whatever the clamped distance says.
        return float("inf")
    return _length(_sub(closest_ray, closest_bone))


def ray_point_distance(origin: Point, direction: Point, point: Point) -> float:
    """The distance from ``point`` to the ray, ``inf`` behind the origin."""
    offset = _sub(point, origin)
    along = _dot(offset, direction)
    if along <= 0.0:
        # Behind the camera: never a click, whatever the distance is.
        return float("inf")
    foot = _add(origin, _scale(direction, along / _dot(direction, direction)))
    return _length(_sub(point, foot))


def pick_bone(
    origin: Point,
    direction: Point,
    segments: Iterable[Segment],
    max_distance: float,
) -> tuple[str, float] | None:
    """The bone segment closest to the ray, or ``None`` past ``max_distance``.

    ``segments`` yields ``(bone_name, head, tail)`` triples in armature space.
    Ties keep the first bone, so the caller controls priority by ordering.
    """
    best: tuple[str, float] | None = None
    for name, head, tail in segments:
        distance = ray_segment_distance(origin, direction, head, tail)
        if best is None or distance < best[1]:
            best = (name, distance)
    if best is None or best[1] > max_distance:
        return None
    return best
