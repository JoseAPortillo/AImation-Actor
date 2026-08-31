"""Virtual (in-memory) seed graph nodes.

Concrete :class:`INode` implementations for the three seed node types:
``pass-through``, ``merge``, and ``frame-range``. They are stateless at the
contract level — all per-run state lives in :class:`ExecutionContext`. Port
types are pinned (D2) so port-typing validation is exercisable end-to-end.
"""

from __future__ import annotations

from typing import Any

from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    INode,
    NodeOutput,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.schema import (
    DataType,
    NodeCategory,
    NodeSchema,
    PortSpec,
)


class PassThroughNode(INode):
    """Relay node typed ``ANY -> ANY``: forwards its single input value."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="pass-through",
            category=NodeCategory.LOGIC,
            title="Pass Through",
            description="Forwards the input value unchanged (universal relay).",
            inputs=[PortSpec(name="input", data_type=DataType.ANY)],
            outputs=[PortSpec(name="output", data_type=DataType.ANY)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        return NodeOutput(values={"output": inputs.get("input")})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


class MergeNode(INode):
    """Concatenates two ``FRAMES`` inputs into one (D2)."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="merge",
            category=NodeCategory.LOGIC,
            title="Merge",
            description="Concatenates two frame streams into one.",
            inputs=[
                PortSpec(name="input_a", data_type=DataType.FRAMES),
                PortSpec(name="input_b", data_type=DataType.FRAMES),
            ],
            outputs=[PortSpec(name="merged", data_type=DataType.FRAMES)],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        left = inputs.get("input_a") or []
        right = inputs.get("input_b") or []
        return NodeOutput(values={"merged": list(left) + list(right)})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)


class FrameRangeNode(INode):
    """Source node emitting frame indices in the half-open range ``[start, end)``."""

    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="frame-range",
            category=NodeCategory.SOURCE,
            title="Frame Range",
            description="Emits frame indices in the half-open range [start, end).",
            outputs=[PortSpec(name="frames", data_type=DataType.FRAMES)],
            params=[
                PortSpec(name="start", data_type=DataType.NUMBER),
                PortSpec(name="end", data_type=DataType.NUMBER),
            ],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        start = int(params["start"])
        end = int(params["end"])
        return NodeOutput(values={"frames": list(range(start, end))})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        for name in ("start", "end"):
            if name not in params:
                errors.append(f"missing required param: {name}")
                continue
            value = params[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"param {name} must be a number")
        if not errors and int(params["start"]) > int(params["end"]):
            errors.append("param start must not exceed end")
        return ValidationResult(valid=not errors, errors=errors)
