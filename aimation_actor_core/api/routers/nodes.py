"""Node catalog endpoints (plan §9.3 ``/nodes/types``).

Consumes the injected :class:`NodeRegistry`; the catalog is auto-derived from
each registered node's schema (SDD §3.4 living documentation).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from aimation_actor_core.api.deps import get_node_registry, require_token
from aimation_actor_core.domain.pipeline.registry import NodeRegistry
from aimation_actor_core.domain.pipeline.schema import NodeSchema

router = APIRouter(prefix="/nodes", tags=["nodes"], dependencies=[Depends(require_token)])


@router.get("/types", response_model=list[NodeSchema], summary="Node catalog")
def list_node_types(
    registry: NodeRegistry = Depends(get_node_registry),
) -> list[NodeSchema]:
    """Return the allowlisted node catalog with their schemas."""
    return registry.list_schemas()
