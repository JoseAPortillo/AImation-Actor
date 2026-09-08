"""Tests for BlockingInputNode (ADAPTER, REQ-03, blocking-input node).

Verifies the blocking-input SOURCE node: catalog schema is SOURCE with
``motion: NEUTRAL_ANIMATION`` output, ``validate`` rejects invalid payloads,
``execute`` emits a valid NeutralMotion that satisfies invariants, and
execution is deterministic (same payload → byte-identical output).

Written RED-first (TDD).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.blocking_input import (
    MAX_BLOCKING_PAYLOAD_CHARS,
    BlockingInputNode,
    BlockingPayloadError,
)


def _neutral_pose_for(bone_names: list[str]) -> dict[str, dict[str, object]]:
    """Build an all-neutral (identity) pose dict over the given bone names."""
    return {
        bone: {
            "translation": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        }
        for bone in bone_names
    }


def _payload(
    skeleton: dict[str, Any] | None = None,
    keyposes: list[dict[str, Any]] | None = None,
) -> str:
    """Build a valid blocking-input JSON string for tests."""
    bones = skeleton or {
        k: {"parent": v["parent"], "rest_position": v["rest_position"]}
        for k, v in DEFAULT_NEUTRAL_SKELETON.model_dump()["bones"].items()
    }
    keyposes = keyposes or [
        {"frame": 1, "pose": {}, "weight": 1.0},
    ]
    if not keyposes[0].get("pose"):
        keyposes[0]["pose"] = _neutral_pose_for(list(bones))
    return json.dumps({"skeleton": bones, "keyposes": keyposes})


def _minimal_valid_payload() -> str:
    """Minimal valid payload: no explicit skeleton (uses default), 1 keypose at frame 1."""
    pose = _neutral_pose_for(list(DEFAULT_NEUTRAL_SKELETON.bones.keys()))
    return json.dumps({"keyposes": [{"frame": 1, "pose": pose, "weight": 1.0}]})


class TestBlockingInputNodeSchema:
    """Test BlockingInputNode catalog schema."""

    def test_schema_type(self) -> None:
        schema = BlockingInputNode.get_schema()
        assert schema.type == "blocking-input"

    def test_schema_category(self) -> None:
        schema = BlockingInputNode.get_schema()
        assert schema.category == NodeCategory.SOURCE

    def test_schema_inputs_empty(self) -> None:
        """SOURCE nodes have no input ports."""
        schema = BlockingInputNode.get_schema()
        assert schema.inputs == []

    def test_schema_outputs_motion_neutral_animation(self) -> None:
        schema = BlockingInputNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "motion"
        assert schema.outputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_params_blocking_string(self) -> None:
        schema = BlockingInputNode.get_schema()
        assert len(schema.params) == 1
        assert schema.params[0].name == "blocking"
        assert schema.params[0].data_type == DataType.STRING
        assert schema.params[0].required is True


class TestBlockingInputNodeValidate:
    """Test BlockingInputNode.validate."""

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_blocking(self) -> None:
        """Missing 'blocking' param is rejected."""
        node = BlockingInputNode()
        result = await node.validate({})
        assert not result.valid
        assert any("blocking" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_string(self) -> None:
        node = BlockingInputNode()
        result = await node.validate({"blocking": ""})
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_rejects_non_json_string(self) -> None:
        node = BlockingInputNode()
        result = await node.validate({"blocking": "not-json"})
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_rejects_invalid_payload_structure(self) -> None:
        node = BlockingInputNode()
        result = await node.validate({"blocking": json.dumps({"bogus": True})})
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_accepts_valid_payload(self) -> None:
        node = BlockingInputNode()
        result = await node.validate({"blocking": _minimal_valid_payload()})
        assert result.valid
        assert result.errors == []


class TestBlockingInputNodeExecute:
    """Test BlockingInputNode.execute."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_returns_valid_neutral_motion(self, context: ExecutionContext) -> None:
        """Valid payload should produce a NeutralMotion with valid invariants."""
        node = BlockingInputNode()
        result = await node.execute(
            inputs={},
            params={"blocking": _minimal_valid_payload()},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        motion.validate_invariants()

    @pytest.mark.asyncio
    async def test_execute_emits_sparse_keyposes(self, context: ExecutionContext) -> None:
        """Output frames == keypose count, frame numbers match keypose frames."""
        node = BlockingInputNode()
        pose = _neutral_pose_for(list(DEFAULT_NEUTRAL_SKELETON.bones.keys()))
        payload = json.dumps({
            "keyposes": [
                {"frame": 1, "pose": pose, "weight": 1.0},
                {"frame": 5, "pose": pose, "weight": 0.8},
            ],
        })
        result = await node.execute(inputs={}, params={"blocking": payload}, context=context)
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        assert len(motion.frames) == 2
        assert [f.frame for f in motion.frames] == [1, 5]

    @pytest.mark.asyncio
    async def test_execute_uses_default_skeleton_when_omitted(
        self, context: ExecutionContext
    ) -> None:
        """Payload without explicit skeleton resolves to DEFAULT_NEUTRAL_SKELETON."""
        node = BlockingInputNode()
        result = await node.execute(
            inputs={}, params={"blocking": _minimal_valid_payload()}, context=context
        )
        motion = result.values["motion"]
        assert motion.skeleton == DEFAULT_NEUTRAL_SKELETON

    @pytest.mark.asyncio
    async def test_execute_deterministic(self, context: ExecutionContext) -> None:
        """Same payload yields byte-identical output."""
        node = BlockingInputNode()
        payload = _minimal_valid_payload()
        r1 = await node.execute(inputs={}, params={"blocking": payload}, context=context)
        r2 = await node.execute(inputs={}, params={"blocking": payload}, context=context)
        m1 = r1.values["motion"]
        m2 = r2.values["motion"]
        assert m1.model_dump_json() == m2.model_dump_json()

    @pytest.mark.asyncio
    async def test_execute_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Offloads conversion to a worker thread (design D7)."""
        import asyncio

        node = BlockingInputNode()
        original_to_thread = asyncio.to_thread
        calls: list[Any] = []

        async def mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            calls.append(func)
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
        try:
            result = await node.execute(
                inputs={}, params={"blocking": _minimal_valid_payload()}, context=context
            )
            assert len(calls) > 0
            assert calls[0].__name__ == "blocking_to_neutral_motion"
            assert isinstance(result.values["motion"], NeutralMotion)
        finally:
            monkeypatch.undo()


class TestBlockingInputNodeThreatModel:
    """Threat-model suite (SDD §4.3): boundary enforcement at the adapter.

    Verifies the defense-in-depth guards the node declares: oversized payloads
    are rejected before parsing, keypose count is bounded, non-finite and
    non-unit values never enter the domain, and the module never uses
    ``eval``/``exec``.
    """

    @pytest.fixture
    def context(self) -> ExecutionContext:
        return ExecutionContext(trace_id="threat-trace")

    def _oversized_payload(self) -> str:
        """Valid JSON whose size exceeds the adapter cap (padding a comment)."""
        pad = "x" * (MAX_BLOCKING_PAYLOAD_CHARS + 1)
        return f'{{"comment": "{pad}"}}'

    @pytest.mark.asyncio
    async def test_validate_rejects_oversized_payload(self) -> None:
        """Oversized payload is rejected by the size cap, not the JSON parser."""
        node = BlockingInputNode()
        result = await node.validate({"blocking": self._oversized_payload()})
        assert not result.valid
        assert any("size" in e.lower() or "large" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_execute_rejects_oversized_payload(self, context: ExecutionContext) -> None:
        """execute raises BlockingPayloadError before parsing an oversized payload."""
        node = BlockingInputNode()
        with pytest.raises(BlockingPayloadError):
            await node.execute(
                inputs={}, params={"blocking": self._oversized_payload()}, context=context
            )

    @pytest.mark.asyncio
    async def test_execute_rejects_more_than_max_keyposes(self, context: ExecutionContext) -> None:
        """MAX_KEYPOSES+1 keyposes never reach the converter (D4 bound)."""
        node = BlockingInputNode()
        bones = {"Root": {"parent": None, "rest_position": [0.0, 0.0, 0.0]}}
        pose = _neutral_pose_for(["Root"])
        keyposes = [
            {"frame": i + 1, "pose": pose, "weight": 1.0}
            for i in range(1001)  # MAX_KEYPOSES + 1
        ]
        payload = json.dumps({"skeleton": bones, "keyposes": keyposes})
        with pytest.raises(Exception):  # noqa: B017 — Pydantic rejection, type unknown here
            await node.execute(inputs={}, params={"blocking": payload}, context=context)

    @pytest.mark.asyncio
    async def test_validate_rejects_non_finite_translation(self) -> None:
        """Inf/NaN in a pose translation is rejected at the boundary (D4)."""
        import math

        node = BlockingInputNode()
        bones = {"Root": {"parent": None, "rest_position": [0.0, 0.0, 0.0]}}
        pose = {
            "Root": {
                "translation": [0.0, math.inf, 0.0],
                "rotation": [1.0, 0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        }
        payload = json.dumps({"skeleton": bones, "keyposes": [{"frame": 1, "pose": pose}]})
        result = await node.validate({"blocking": payload})
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_rejects_non_unit_quaternion(self) -> None:
        """A non-unit rotation quaternion is rejected at the boundary (D4)."""
        node = BlockingInputNode()
        bones = {"Root": {"parent": None, "rest_position": [0.0, 0.0, 0.0]}}
        pose = {
            "Root": {
                "translation": [0.0, 0.0, 0.0],
                "rotation": [2.0, 0.0, 0.0, 0.0],  # norm 2.0
                "scale": [1.0, 1.0, 1.0],
            }
        }
        payload = json.dumps({"skeleton": bones, "keyposes": [{"frame": 1, "pose": pose}]})
        result = await node.validate({"blocking": payload})
        assert not result.valid

    def test_adapter_module_uses_no_eval_or_exec(self) -> None:
        """Static check: no dynamic code execution anywhere in the adapter."""
        from pathlib import Path

        import aimation_actor_core.infrastructure.ai_models.blocking_input as adapter_module

        source = Path(adapter_module.__file__).read_text(encoding="utf-8")
        assert "eval(" not in source
        assert "exec(" not in source
