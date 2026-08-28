"""Shared type aliases for the animation domain (SDD §2.2, :mod:`shared`).

Kept dependency-free on purpose: these are structural aliases that any layer
may import without violating the module dependency matrix (SDD §2.3).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

#: A length-3 float tuple, e.g. translation ``(x, y, z)`` or scale.
Vec3 = Annotated[tuple[float, float, float], Field(min_length=3, max_length=3)]

#: A length-4 float tuple, e.g. a quaternion ``(w, x, y, z)``.
Vec4 = Annotated[tuple[float, float, float, float], Field(min_length=4, max_length=4)]
