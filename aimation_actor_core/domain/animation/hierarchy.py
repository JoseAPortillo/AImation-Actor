"""Skeleton hierarchy validation logic (domain/animation).

Pure functions, no I/O. Kept separate from the :class:`Skeleton` data class
to honor single responsibility (SDD §3.2, SRP).
"""

from __future__ import annotations

from aimation_actor_core.domain.animation.skeleton import Skeleton


class HierarchyError(ValueError):
    """Raised when a skeleton does not form a valid hierarchy."""


def validate(skeleton: Skeleton) -> None:
    """Validate that a skeleton forms a single rooted tree.

    Checks (in order):
      1. No duplicate bone names (guaranteed by :class:`Skeleton` using a dict,
         but re-checked defensively).
      2. Every ``parent`` reference resolves to an existing bone.
      3. No self-loops (a bone cannot be its own parent).
      4. Exactly one root bone (parent is ``None``).
      5. No cycles (every bone is reachable from the root).

    Raises:
        HierarchyError: If any invariant is violated.
    """
    bones = skeleton.bones
    if not bones:
        raise HierarchyError("empty skeleton")

    for name, bone in bones.items():
        if bone.parent not in bones and bone.parent is not None:
            raise HierarchyError(
                f"bone '{name}' references unknown parent '{bone.parent}'"
            )
    for name, bone in bones.items():
        if bone.parent == name:
            raise HierarchyError(f"bone '{name}' is its own parent (self-loop)")

    roots = [name for name, bone in bones.items() if bone.parent is None]
    if len(roots) != 1:
        raise HierarchyError(
            f"skeleton must have exactly one root, found {len(roots)}: {roots}"
        )

    root = roots[0]
    visited: set[str] = set()
    stack: list[str] = [root]
    while stack:
        current = stack.pop()
        if current in visited:
            raise HierarchyError(f"cycle detected at bone '{current}'")
        visited.add(current)
        children = [
            name for name, bone in bones.items() if bone.parent == current
        ]
        stack.extend(children)

    if len(visited) != len(bones):
        orphaned = sorted(set(bones) - visited)
        raise HierarchyError(
            f"bones not reachable from root (cycle or orphan): {orphaned}"
        )
