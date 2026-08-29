"""Tests for Pose2DNode."""

from typing import Any

import numpy as np
import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.pose_2d import Pose2DNode


class TestPose2DNodeSchema:
    """Test Pose2DNode schema."""

    def test_schema_type(self) -> None:
        """Should have correct type."""
        schema = Pose2DNode.get_schema()
        assert schema.type == "pose-2d"

    def test_schema_category(self) -> None:
        """Should be AI category."""
        schema = Pose2DNode.get_schema()
        assert schema.category == NodeCategory.AI

    def test_schema_inputs(self) -> None:
        """Should have frames input port."""
        schema = Pose2DNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "frames"
        assert schema.inputs[0].data_type == DataType.FRAMES

    def test_schema_outputs(self) -> None:
        """Should have keypoints output port."""
        schema = Pose2DNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "keypoints"
        assert schema.outputs[0].data_type == DataType.KEYPOINTS_2D

    def test_schema_params(self) -> None:
        """Should have model and confidence params."""
        schema = Pose2DNode.get_schema()
        assert len(schema.params) == 2

        param_names = [p.name for p in schema.params]
        assert "model" in param_names
        assert "confidence" in param_names

        model_param = next(p for p in schema.params if p.name == "model")
        assert model_param.data_type == DataType.STRING
        assert not model_param.required

        confidence_param = next(p for p in schema.params if p.name == "confidence")
        assert confidence_param.data_type == DataType.NUMBER
        assert not confidence_param.required


class TestPose2DNodeExecute:
    """Test Pose2DNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_with_synthetic_backend(self, context: ExecutionContext) -> None:
        """Should execute with synthetic backend."""
        node = Pose2DNode()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(3)]

        result = await node.execute(
            inputs={"frames": frames},
            params={"model": "synthetic"},
            context=context,
        )

        assert "keypoints" in result.values
        keypoints = result.values["keypoints"]
        assert isinstance(keypoints, list)
        assert len(keypoints) == 3
        assert all(isinstance(kp, Keypoints2D) for kp in keypoints)

    @pytest.mark.asyncio
    async def test_execute_default_model_is_synthetic(self, context: ExecutionContext) -> None:
        """Should use synthetic backend by default."""
        node = Pose2DNode()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        result = await node.execute(
            inputs={"frames": frames},
            params={},
            context=context,
        )

        assert "keypoints" in result.values
        assert len(result.values["keypoints"]) == 1

    @pytest.mark.asyncio
    async def test_execute_with_confidence_filter(self, context: ExecutionContext) -> None:
        """Should filter keypoints by confidence threshold."""
        node = Pose2DNode()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        # Synthetic backend produces keypoints with confidence=0.95
        # Filter with threshold 0.9 should keep them
        result = await node.execute(
            inputs={"frames": frames},
            params={"model": "synthetic", "confidence": 0.9},
            context=context,
        )

        keypoints = result.values["keypoints"]
        assert len(keypoints) == 1
        # All keypoints should have confidence >= 0.9
        for kp2d in keypoints:
            for kp in kp2d.keypoints:
                assert kp.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_execute_unknown_model_falls_back_to_synthetic(
        self, context: ExecutionContext
    ) -> None:
        """Should fall back to synthetic for unknown model."""
        node = Pose2DNode()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        result = await node.execute(
            inputs={"frames": frames},
            params={"model": "unknown_model"},
            context=context,
        )

        # Should not crash, should use synthetic backend
        assert "keypoints" in result.values
        assert len(result.values["keypoints"]) == 1

    @pytest.mark.asyncio
    async def test_execute_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Should offload inference to thread pool."""
        node = Pose2DNode()
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]

        # Patch asyncio.to_thread to verify it's called
        import asyncio

        original_to_thread = asyncio.to_thread
        calls = []

        async def mock_to_thread(func: Any, *args: Any) -> Any:  # noqa: ANN401
            calls.append((func, args))
            return await original_to_thread(func, *args)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)

        try:
            await node.execute(
                inputs={"frames": frames},
                params={"model": "synthetic"},
                context=context,
            )

            # Should have called to_thread at least once
            assert len(calls) > 0
        finally:
            monkeypatch.undo()


class TestPose2DNodeValidate:
    """Test Pose2DNode parameter validation.

    Finalized contract (tasks.md Task 4 reconciliation, per design):
    ``validate()`` requires the ``model`` param — when provided — to be a
    non-empty string (rejects empty / whitespace-only / non-string values).
    Unknown model *values* are accepted here because ``execute()`` falls back
    safely to the synthetic backend (spec REQ-3 scenario "Unknown model falls
    back safely").
    """

    @pytest.mark.asyncio
    async def test_validate_empty_params(self) -> None:
        """Should accept empty params (all params are optional)."""
        node = Pose2DNode()
        result = await node.validate({})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_synthetic_model(self) -> None:
        """Should accept the synthetic model value."""
        node = Pose2DNode()
        result = await node.validate({"model": "synthetic"})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_onnx_model(self) -> None:
        """Should accept the onnx model value."""
        node = Pose2DNode()
        result = await node.validate({"model": "onnx"})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_unknown_model_value_is_accepted(self) -> None:
        """Should accept unknown model values (execute() falls back safely)."""
        node = Pose2DNode()
        result = await node.validate({"model": "unknown_model"})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_model_string(self) -> None:
        """Should reject an empty model string when provided."""
        node = Pose2DNode()
        result = await node.validate({"model": ""})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_whitespace_only_model_string(self) -> None:
        """Should reject a whitespace-only model string when provided."""
        node = Pose2DNode()
        result = await node.validate({"model": "   "})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_string_model_value(self) -> None:
        """Should reject a non-string model value when provided."""
        node = Pose2DNode()
        result = await node.validate({"model": None})
        assert not result.valid
        assert result.errors
