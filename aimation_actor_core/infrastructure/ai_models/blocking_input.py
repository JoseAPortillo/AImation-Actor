"""Blocking-input node: payload-to-motion adapter (ADAPTER, REQ-03).

A deterministic, backend-less :class:`BlockingInputNode` that consumes a
``blocking`` JSON string (via a ``STRING`` param) and emits
``motion: NEUTRAL_ANIMATION``.  The actual domain math lives in
:mod:`domain.animation.blocking_input`; this node only adapts the
:class:`INode` contract to it — ``asyncio.to_thread`` offload, JSON parsing,
and strict Pydantic validation of the incoming payload.

Security (SDD §4.3):
  - The payload is validated at the adapter boundary via the Pydantic model
    (``extra="forbid"``, ``MAX_KEYPOSES`` cap, quaternion unit-norm + finite,
    weight [0, 1]).  No ``eval``/``exec`` anywhere in this module.
  - Oversized payloads are rejected by the ``MAX_BLOCKING_PAYLOAD_CHARS``
    character cap *before* any JSON parsing (bounded parse cost), and by the
    Pydantic ``max_length`` on ``keyposes`` (``MAX_KEYPOSES=1000``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aimation_actor_core.domain.animation.blocking_input import (
    BlockingInput,
    blocking_to_neutral_motion,
)
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
from aimation_actor_core.shared.errors import AImationError

#: Maximum length (in characters) of the ``blocking`` payload accepted at the
#: adapter boundary.  Generously above the worst-case *legal* payload
#: (1000 keyposes x 22 bones, compact JSON ~2.3M chars) while bounding the
#: cost of parsing before any ``json.loads`` runs (SDD §4.3).
MAX_BLOCKING_PAYLOAD_CHARS: int = 4_000_000


def _guard_payload_size(blocking: str) -> None:
    """Reject payloads over the character cap *before* any JSON parsing.

    ``len`` on a ``str`` is O(1), so this guards the parse cost without first
    materialising an encoded copy (defense-in-depth, shared with ``validate``
    so both entry points enforce the same boundary).
    """
    if len(blocking) > MAX_BLOCKING_PAYLOAD_CHARS:
        raise BlockingPayloadError(
            f"blocking payload too large: {len(blocking)} chars "
            f"(max {MAX_BLOCKING_PAYLOAD_CHARS})"
        )


class BlockingPayloadError(AImationError):
    """Raised when the ``blocking`` payload violates a boundary guard."""

    code = "blocking_payload_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class BlockingInputNode(INode):
    """SOURCE node: ``STRING`` param → ``NeutralMotion`` output.

    The ``blocking`` param carries a JSON-encoded :class:`BlockingInput`
    payload.  ``validate`` checks it is non-empty, parseable JSON, and
    model-validates against the :class:`BlockingInput` Pydantic schema.
    ``execute`` parses the JSON, runs the domain converter off the event loop,
    and returns the resulting :class:`NeutralMotion` under ``motion``.
    """

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="blocking-input",
            category=NodeCategory.SOURCE,
            title="Blocking Input",
            description="Convert a blocking payload into a neutral motion",
            inputs=[],
            outputs=[
                PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION),
            ],
            params=[
                PortSpec(
                    name="blocking",
                    data_type=DataType.STRING,
                    required=True,
                    widget="json",
                    description=(
                        "JSON-encoded blocking payload. The payload is a JSON "
                        "object with an optional `skeleton` (defaults to the "
                        "neutral skeleton when omitted) and a required "
                        "`keyposes` array (1-1000). Each keypose has: "
                        "`frame` (int >= 1, unique); `pose` (object naming "
                        "every bone of the resolved skeleton: "
                        "{bone_name: {translation: [x,y,z], rotation: "
                        "[w,x,y,z], scale: [x,y,z]}}); optional `weight` "
                        "([0,1], default 1.0). "
                        'Example: {"keyposes":[{"frame":1,"pose":{"hip":'
                        '{"translation":[0,0,0],"rotation":[1,0,0,0],'
                        '"scale":[1,1,1]}}}]'
                    ),
                ),
            ],
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute the blocking-to-motion conversion.

        Args:
            inputs: Empty (SOURCE node — no input ports).
            params: Must contain ``blocking``: a JSON string parseable as
                :class:`BlockingInput`.
            context: Execution context.

        Returns:
            NodeOutput with a :class:`NeutralMotion` under ``motion``.

        Raises:
            BlockingPayloadError: If the payload exceeds the size cap or fails
                domain validation (defense-in-depth, D6).
        """
        del context  # unused; kept for the INode contract
        blocking_str = params["blocking"]
        _guard_payload_size(blocking_str)
        payload = json.loads(blocking_str)
        blocking_input = BlockingInput.model_validate(payload)

        # Run the domain conversion off the event loop (design D7).
        motion = await asyncio.to_thread(blocking_to_neutral_motion, blocking_input)
        return NodeOutput(values={"motion": motion})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate the ``blocking`` param (defense-in-depth, D6).

        Must be a non-empty string, parseable as JSON, and model-valid against
        :class:`BlockingInput`.  All validation errors are collected and
        returned in one shot.
        """
        errors: list[str] = []
        blocking = params.get("blocking")
        if not isinstance(blocking, str) or not blocking.strip():
            errors.append("missing required param: blocking")
        elif len(blocking) > MAX_BLOCKING_PAYLOAD_CHARS:
            errors.append(
                f"blocking payload too large: {len(blocking)} chars "
                f"(max {MAX_BLOCKING_PAYLOAD_CHARS})"
            )
        else:
            try:
                data = json.loads(blocking)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"blocking is not valid JSON: {exc}")
            else:
                try:
                    BlockingInput.model_validate(data)
                except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
                    errors.append(f"blocking payload invalid: {exc}")
        return ValidationResult(valid=not errors, errors=errors)
