"""Cross-cutting domain exception hierarchy.

Belongs to the ``shared`` layer (SDD §2.3): importable by every module,
imports nothing internal.
"""

from __future__ import annotations

from typing import Any


class AImationError(Exception):
    """Base class for all AImation Actor domain errors."""

    #: Stable machine-readable code for API consumers.
    code: str = "aimation_error"


class ValidationError(AImationError):
    """Input or configuration failed validation."""

    code = "validation_error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = context or {}


class ConfigurationError(AImationError):
    """Invalid or missing application configuration."""

    code = "configuration_error"


class NotFoundError(AImationError):
    """A requested entity does not exist."""

    code = "not_found"


class PermissionDeniedError(AImationError):
    """The caller lacks permission to perform an operation."""

    code = "permission_denied"


class NodeExecutionError(AImationError):
    """A graph node failed during execution."""

    code = "node_execution_error"

    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id: str | None = node_id
        self.__cause__ = cause


class ModelIntegrityError(AImationError):
    """An AI model failed integrity verification (SDD §4.2)."""

    code = "model_integrity_error"
