"""E2E graph test: blocking-input -> inbetween-generation (E2E, REQ-03 + KEY-LOCK).

Runs the two-node graph
``blocking-input (SOURCE) → inbetween-generation (ENRICHMENT, preserve_keyposes)``
through the :class:`SynchronousGraphExecutor` against the seeded registry and
asserts the E2E invariants:

- the output is a valid :class:`NeutralMotion`;
- the authored blocking key values are held exact at the locked output frames
  (key-lock survives the full pipeline, D5);
- the key-pose frame indices are remapped onto the 60fps output grid (REQ-06).

Written RED-first (TDD).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.graph import (
    Edge,
    Graph,
    GraphNode,
    PortRef,
)
from aimation_actor_core.infrastructure.virtual.executor import (
    SynchronousGraphExecutor,
)
from aimation_actor_core.infrastructure.virtual.node_registry import (
    seeded_node_registry,
)


def _identity_pose(root_y: float) -> dict[str, dict[str, Any]]:
    """Build an all-identity pose dict with a distinct Root translation."""
    return {
        bone: {
            "translation": [0.0, root_y if bone == "Root" else 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        }
        for bone in DEFAULT_NEUTRAL_SKELETON.bones.keys()
    }


def _blocking_payload() -> str:
    """Three authored blocking keys at 24fps (frames 1,2,3) with distinct Y."""
    return json.dumps({
        "keyposes": [
            {"frame": 1, "pose": _identity_pose(0.0), "weight": 1.0},
            {"frame": 2, "pose": _identity_pose(10.0), "weight": 1.0},
            {"frame": 3, "pose": _identity_pose(20.0), "weight": 1.0},
        ],
    })


def _graph() -> Graph:
    """The canonical blocking-input → inbetween-generation graph."""
    return Graph(
        version="0.1",
        nodes=[
            GraphNode(id="block", type="blocking-input", params={
                "blocking": _blocking_payload(),
            }),
            GraphNode(id="enrich", type="inbetween-generation", params={
                "target_fps": 60,
                "preserve_keyposes": True,
            }),
        ],
        edges=[
            Edge(
                id="e1",
                source=PortRef(node="block", port="motion"),
                target=PortRef(node="enrich", port="motion"),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_blocking_graph_executes_to_valid_neutral_motion() -> None:
    """Two-node graph runs end-to-end and yields a valid NeutralMotion."""
    registry = seeded_node_registry()
    result = await SynchronousGraphExecutor().run(_graph(), registry)
    motion = result.outputs["enrich"]["motion"]
    assert isinstance(motion, NeutralMotion)
    motion.validate_invariants()
    assert len(result.logs) == 2


@pytest.mark.asyncio
async def test_blocking_key_values_preserved_at_locked_frames() -> None:
    """Authored Root Y is held exact at every locked output frame (D5).

    3 source frames @24fps -> 6 output frames @60fps. Locks: src idx 0 ->
    out idx 0 (frame 1), src idx 1 -> out idx 2 (frame 3), src idx 2 ->
    out idx 5 (frame 6). Without key-lock these positions would be blends.
    """
    registry = seeded_node_registry()
    result = await SynchronousGraphExecutor().run(_graph(), registry)
    motion = result.outputs["enrich"]["motion"]
    assert isinstance(motion, NeutralMotion)
    ys = [f.pose.transforms["Root"].translation[1] for f in motion.frames]
    assert ys[0] == pytest.approx(0.0)
    assert ys[2] == pytest.approx(10.0)
    assert ys[5] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_blocking_keyposes_remapped_onto_output_grid() -> None:
    """Key-pose frame indices land on the 60fps grid, within duration (REQ-06)."""
    registry = seeded_node_registry()
    result = await SynchronousGraphExecutor().run(_graph(), registry)
    motion = result.outputs["enrich"]["motion"]
    assert isinstance(motion, NeutralMotion)
    keyposes = [(k.frame, k.weight) for k in motion.keyposes]
    assert keyposes == [(1, 1.0), (3, 1.0), (6, 1.0)]
    assert all(k.frame <= motion.meta.duration_frames for k in motion.keyposes)