"""Public API of the pipeline domain package (SDD §2.2).

Re-exports the node-graph domain contracts. Concrete node implementations are
NOT re-exported here — they live in :mod:`infrastructure` and are injected via
the registry at the composition root.
"""

from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    INode,
    NodeOutput,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory, NodeSchema, PortSpec

__all__ = [
    "DataType",
    "ExecutionContext",
    "INode",
    "NodeCategory",
    "NodeOutput",
    "NodeRegistry",
    "NodeSchema",
    "PortSpec",
    "ValidationResult",
]
