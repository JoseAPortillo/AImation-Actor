"""Unit tests for the pipeline domain contracts (SDD §3.3)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aimation_actor_core.domain.pipeline import (
    DataType,
    ExecutionContext,
    INode,
    NodeCategory,
    NodeOutput,
    NodeRegistry,
    NodeSchema,
    PortSpec,
    ValidationResult,
)


class DummyNode(INode):
    """Minimal INode implementation for exercising the protocol."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="DummyNode",
            category=NodeCategory.CLEANUP,
            title="Dummy",
            inputs=[PortSpec(name="in", data_type=DataType.POSE_3D)],
            outputs=[PortSpec(name="out", data_type=DataType.POSE_3D)],
            params=[PortSpec(name="strength", data_type=DataType.NUMBER, default=1.0)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        return NodeOutput(values={"out": inputs.get("in")})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


def test_inode_is_runtime_checkable() -> None:
    assert isinstance(DummyNode(), INode)


def test_node_schema_defaults() -> None:
    schema = NodeSchema(type="X", category=NodeCategory.AI, title="X")
    assert schema.inputs == []
    assert schema.outputs == []
    assert schema.params == []


def test_node_schema_table_round_trip() -> None:
    sym = DummyNode.get_schema()
    assert sym.type == "DummyNode"
    assert sym.category == NodeCategory.CLEANUP
    assert sym.outputs[0].data_type == DataType.POSE_3D


def test_node_schema_frozen() -> None:
    schema = NodeSchema(type="X", category=NodeCategory.AI, title="X")
    with pytest.raises(ValidationError):
        schema.title = "Y"  # type: ignore[misc]


def test_port_spec_required_default() -> None:
    p = PortSpec(name="n", data_type=DataType.NUMBER, default=2)
    assert p.required is True
    assert p.default == 2


def test_execution_context_min_trace() -> None:
    ctx = ExecutionContext(trace_id="abc", timeout_s=10.0)
    assert ctx.session_id is None
    assert ctx.timeout_s == 10.0


def test_execution_context_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValidationError):
        ExecutionContext(trace_id="abc", timeout_s=0)


class _FakeRegistry:
    """Structural stand-in matching NodeRegistry."""

    def __init__(self) -> None:
        self._schemas: dict[str, NodeSchema] = {n.type: n for n in [DummyNode.get_schema()]}

    def get(self, node_type: str) -> INode | None:  # pragma: no cover
        return DummyNode() if node_type in self._schemas else None

    def list_schemas(self) -> list[NodeSchema]:
        return list(self._schemas.values())

    def contains(self, node_type: str) -> bool:
        return node_type in self._schemas


def test_registry_protocol_structurally_satisfied() -> None:
    registry: NodeRegistry = _FakeRegistry()
    assert registry.contains("DummyNode")
    assert not registry.contains("Nope")
    assert len(registry.list_schemas()) == 1
