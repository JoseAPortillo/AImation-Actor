"""Registry + graph-chain tests for RetargetMapNode (§13 / Phase 3).

Verifies the retarget-map node participates in the seeded node registry as the
10th seed with category ``RIGGING``, ``NEUTRAL_ANIMATION`` ports, and that the
extended canonical AI pipeline chain ``video-source → pose-2d → pose-3d →
video-to-motion → temporal-cleanup → inbetween-generation → retarget-map`` is a
valid connected graph. Written RED-first (fails until task 3.7 registers the
node).
"""

from __future__ import annotations

from aimation_actor_core.domain.pipeline.graph import (
    Edge,
    Graph,
    GraphNode,
    PortRef,
    validate_graph,
)
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.virtual.node_registry import (
    seeded_node_registry,
)


class TestSeededRegistry:
    """Test that the retarget node is a seeded registry citizen."""

    def test_registry_contains_retarget_map_with_neutral_animation_ports(
        self,
    ) -> None:
        """Should register retarget-map with the two NEUTRAL_ANIMATION ports."""
        registry = seeded_node_registry()
        schemas = {schema.type: schema for schema in registry.list_schemas()}
        assert "retarget-map" in schemas
        schema = schemas["retarget-map"]
        assert [port.name for port in schema.inputs] == ["motion"]
        assert [port.name for port in schema.outputs] == ["motion"]
        assert [port.data_type for port in schema.inputs] == [DataType.NEUTRAL_ANIMATION]
        assert [port.data_type for port in schema.outputs] == [DataType.NEUTRAL_ANIMATION]

    def test_registry_has_ten_seeds(self) -> None:
        """Should register exactly ten seed node types."""
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
        }

    def test_retarget_map_category_is_rigging(self) -> None:
        """Should declare NodeCategory.RIGGING."""
        registry = seeded_node_registry()
        schemas = {schema.type: schema for schema in registry.list_schemas()}
        assert schemas["retarget-map"].category == NodeCategory.RIGGING


class TestRetargetPipelineChain:
    """Test the 7-node AI pipeline chain validates as a connected DAG."""

    def test_retarget_chain_is_valid_connected_graph(self) -> None:
        """Should validate the full chain up to retarget-map as a
        connected, port-compatible graph."""
        registry = seeded_node_registry()
        graph = Graph(
            version="0.1",
            nodes=[
                GraphNode(id="video", type="video-source"),
                GraphNode(id="pose", type="pose-2d"),
                GraphNode(id="lift", type="pose-3d"),
                GraphNode(id="convert", type="video-to-motion"),
                GraphNode(id="cleanup", type="temporal-cleanup"),
                GraphNode(id="enrich", type="inbetween-generation"),
                GraphNode(id="retarget", type="retarget-map"),
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
                Edge(
                    id="e5",
                    source=PortRef(node="cleanup", port="motion"),
                    target=PortRef(node="enrich", port="motion"),
                ),
                Edge(
                    id="e6",
                    source=PortRef(node="enrich", port="motion"),
                    target=PortRef(node="retarget", port="motion"),
                ),
            ],
        )
        result = validate_graph(graph, registry)
        assert result.valid, result.errors