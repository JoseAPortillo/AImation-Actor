"""Public API of the model catalog/provisioning infrastructure.

Re-exports the catalog types and errors so callers import from
``aimation_actor_core.infrastructure.models`` rather than deep submodules
(SDD §2.2). Infrastructure-only: no API imports (SDD §2.3).
"""

from aimation_actor_core.infrastructure.models.provisioner import (
    ModelProvisioner,
    ModelProvisionError,
)
from aimation_actor_core.infrastructure.models.registry import (
    ModelManifestError,
    ModelNotFoundError,
    ModelRegistry,
    ModelSpec,
)

__all__ = [
    "ModelManifestError",
    "ModelNotFoundError",
    "ModelProvisionError",
    "ModelProvisioner",
    "ModelRegistry",
    "ModelSpec",
]