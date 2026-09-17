"""Registry + graph-chain tests for InbetweenGenerationNode (§12.5 / Phase 4).

Verifies the in-between generation node participates in the seeded node
registry as the 9th seed with category ``ENRICHMENT`` and
``NEUTRAL_ANIMATION`` ports, and that the canonical 6-node AI pipeline chain
``video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup →
inbetween-generation`` is a valid connected graph. Written RED-first: every
test here fails until the registry wiring registers ``inbetween-generation``
and the package re-export lands.
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
    """Test that the in-between node is a seeded registry citizen."""

    def test_registry_contains_inbetween_generation_with_neutral_animation_ports(
        self,
    ) -> None:
        """Should register inbetween-generation with the two NEUTRAL_ANIMATION ports."""
        registry = seeded_node_registry()
        schemas = {schema.type: schema for schema in registry.list_schemas()}
        assert "inbetween-generation" in schemas
        schema = schemas["inbetween-generation"]
        assert schema.category == NodeCategory.ENRICHMENT
        assert [port.name for port in schema.inputs] == ["motion"]
        assert [port.name for port in schema.outputs] == ["motion"]
        assert [port.data_type for port in schema.inputs] == [DataType.NEUTRAL_ANIMATION]
        assert [port.data_type for port in schema.outputs] == [DataType.NEUTRAL_ANIMATION]

    def test_registry_inbetween_node_declares_five_validation_params(self) -> None:
        """Should declare exactly the 5 params of this chain's 5-param adapter.

        Guards against the archived ``feat/Develop`` lineage whose adapter
        carried a 6th ``preserve_keyposes`` param that does not exist on this
        chain's domain.
        """
        registry = seeded_node_registry()
        schema = next(s for s in registry.list_schemas() if s.type == "inbetween-generation")
        param_names = [param.name for param in schema.params]
        assert param_names == [
            "interpolation_method",
            "target_fps",
            "easing",
            "euler_filter",
            "tangent_smoothing",
        ]
        defaults = {param.name: param.default for param in schema.params}
        assert defaults["interpolation_method"] == "cubic"
        assert defaults["target_fps"] == 30.0
        assert defaults["easing"] == "none"
        assert defaults["euler_filter"] is True
        assert defaults["tangent_smoothing"] == 0.0

    def test_registry_has_nine_seeds(self) -> None:
        """Should register exactly nine seed node types."""
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
        }

    def test_package_reexports_inbetween_generation_node(self) -> None:
        """Should re-export InbetweenGenerationNode from infrastructure.ai_models."""
        from aimation_actor_core.infrastructure.ai_models import (
            InbetweenGenerationNode as Reexported,
        )

        schema = Reexported.get_schema()
        assert schema.type == "inbetween-generation"


class TestInbetweenPipelineChain:
    """Test the 6-node AI pipeline chain validates as a connected DAG."""

    def test_inbetween_chain_is_valid_connected_graph(self) -> None:
        """Should validate the video-source->pose-2d->pose-3d->video-to-motion
        ->temporal-cleanup->inbetween-generation chain as a connected,
        port-compatible graph."""
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
            ],
        )
        result = validate_graph(graph, registry)
        assert result.valid, result.errors
