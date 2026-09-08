"""Registry + graph-chain tests for TemporalCleanupNode (§12.4 / Phase 4).

Verifies the temporal cleanup node participates in the seeded node registry as
the 8th seed and that the canonical AI pipeline chain
``video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup`` is a
valid connected graph. Written RED-first: both tests fail until the registry
wiring (Phase 3) registers ``temporal-cleanup``.
"""

from __future__ import annotations

from aimation_actor_core.domain.pipeline.graph import (
    Edge,
    Graph,
    GraphNode,
    PortRef,
    validate_graph,
)
from aimation_actor_core.domain.pipeline.schema import DataType
from aimation_actor_core.infrastructure.virtual.node_registry import (
    seeded_node_registry,
)


class TestSeededRegistry:
    """Test that the cleanup node is a seeded registry citizen."""

    def test_registry_contains_temporal_cleanup_with_neutral_animation_ports(
        self,
    ) -> None:
        """Should register temporal-cleanup with the two NEUTRAL_ANIMATION ports."""
        registry = seeded_node_registry()
        schemas = {schema.type: schema for schema in registry.list_schemas()}
        assert "temporal-cleanup" in schemas
        schema = schemas["temporal-cleanup"]
        assert [port.name for port in schema.inputs] == ["motion"]
        assert [port.name for port in schema.outputs] == ["motion"]
        assert [port.data_type for port in schema.inputs] == [DataType.NEUTRAL_ANIMATION]
        assert [port.data_type for port in schema.outputs] == [DataType.NEUTRAL_ANIMATION]

    def test_registry_has_eleven_seeds(self) -> None:
        """Should register exactly eleven seed node types."""
        registry = seeded_node_registry()
        types = {schema.type for schema in registry.list_schemas()}
        assert types == {
            "pass-through",
            "merge",
            "frame-range",
            "video-source",
            "pose-2d",
            "pose-3d",
            "video-to-motion",
            "temporal-cleanup",
            "inbetween-generation",
            "retarget-map",
            "blocking-input",
        }


class TestCleanupPipelineChain:
    """Test the 5-node AI pipeline chain validates as a connected DAG."""

    def test_cleanup_chain_is_valid_connected_graph(self) -> None:
        """Should validate the video-source->pose-2d->pose-3d->video-to-motion
        ->temporal-cleanup chain as a connected, port-compatible graph."""
        registry = seeded_node_registry()
        graph = Graph(
            version="0.1",
            nodes=[
                GraphNode(id="video", type="video-source"),
                GraphNode(id="pose", type="pose-2d"),
                GraphNode(id="lift", type="pose-3d"),
                GraphNode(id="convert", type="video-to-motion"),
                GraphNode(id="cleanup", type="temporal-cleanup"),
            ],
            edges=[
                Edge(
                    id="e1",
                    source=PortRef(node="video", port="frames"),
                    target=PortRef(node="pose", port="frames"),
                ),
                Edge(
                    id="e2",
                    source=PortRef(node="pose", port="keypoints"),
                    target=PortRef(node="lift", port="keypoints"),
                ),
                Edge(
                    id="e3",
                    source=PortRef(node="lift", port="keypoints_3d"),
                    target=PortRef(node="convert", port="keypoints_3d"),
                ),
                Edge(
                    id="e4",
                    source=PortRef(node="convert", port="motion"),
                    target=PortRef(node="cleanup", port="motion"),
                ),
            ],
        )
        result = validate_graph(graph, registry)
        assert result.valid, result.errors
