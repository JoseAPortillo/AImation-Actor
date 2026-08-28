"""The node execution contract (SDD §5.1).

``INode`` is the protocol every graph node implements. Concrete nodes live in
:mod:`infrastructure` (Sub_Agents.md §4.2 / ml-engineer); this module only
defines the contract, so ``domain/`` never depends on implementations.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from aimation_actor_core.domain.pipeline.schema import NodeSchema


class ExecutionContext(BaseModel):
    """Runtime context handed to :meth:`INode.execute`.

    Attributes:
        trace_id: Correlation id for the whole graph run (observability,
            SDD §6.2). Never logs user content (SDD §4.3).
        session_id: Optional associated DCC session id.
        timeout_s: Per-node execution time budget (SDD §4.3).
    """

    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(min_length=1)
    session_id: str | None = None
    timeout_s: float = Field(default=30.0, gt=0.0)


class ValidationResult(BaseModel):
    """Outcome of :meth:`INode.validate` (SDD §5.1)."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    errors: list[str] = Field(default_factory=list)


class NodeOutput(BaseModel):
    """Structured result of :meth:`INode.execute`.

    Outputs are keyed by the node's declared output port names. Values are kept
    generic (``Any``) because concrete data types (frames, NeutralMotion, etc.)
    are defined per node; the schema in :class:`NodeSchema.outputs` narrows them.
    """

    model_config = ConfigDict(frozen=True)

    values: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class INode(Protocol):
    """Contract for a graph node (SDD §5.1).

    Implementations MUST be stateless at the contract level (all per-run state
    lives in :class:`ExecutionContext`), so the orchestrator can run them
    safely and isolate failures.
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the static catalog schema for this node type."""
        ...

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Run the node.

        Args:
            inputs: Values keyed by input port name.
            params: Validated parameter values keyed by param name.
            context: Per-run execution context.

        Returns:
            The node output keyed by output port name.
        """
        ...

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate the node's parameters before execution."""
        ...
